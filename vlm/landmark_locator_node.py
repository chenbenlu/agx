#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

try:
    from isaac_ros_grounding_dino_interfaces.srv import SetPrompt
except ImportError:  # pragma: no cover - only available in the VLM container
    SetPrompt = None

from vla_demo.json_utils import dumps_json, loads_json
from vla_demo.landmark_logic import (
    build_landmark_detection_payload,
    normalize_grounding_prompt,
    select_best_detection,
)
from vla_demo.topics import CURRENT_STEP_TOPIC, LANDMARK_DETECTION_TOPIC

BEST_EFFORT_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)


class LandmarkLocatorNode(Node):
    def __init__(self) -> None:
        super().__init__("landmark_locator")

        self.active_step_payload: dict[str, Any] = {}
        self.active_target_landmark = ""
        self.active_prompt = ""
        self.last_prompt_key = ""
        self.pending_futures = []

        self.detection_pub = self.create_publisher(String, LANDMARK_DETECTION_TOPIC, 10)
        self.create_subscription(String, CURRENT_STEP_TOPIC, self._on_current_step, 10)
        self.create_subscription(
            Detection2DArray,
            "/detections_output",
            self._on_detections,
            BEST_EFFORT_QOS,
        )
        self.prompt_client = (
            self.create_client(SetPrompt, "/set_prompt") if SetPrompt is not None else None
        )

        self.get_logger().info(
            "Landmark locator ready. Listening for active VLA steps and Grounding DINO detections."
        )

    def _on_current_step(self, msg: String) -> None:
        try:
            payload = loads_json(msg.data, "current_step")
        except ValueError as exc:
            self.get_logger().warn(str(exc))
            return
        if not isinstance(payload, dict):
            self.get_logger().warn("Ignoring current step payload that is not a JSON object.")
            return

        step = payload.get("step") or {}
        if not isinstance(step, dict):
            self.active_step_payload = {}
            self.active_target_landmark = ""
            self.active_prompt = ""
            self.last_prompt_key = ""
            return

        self.active_step_payload = payload
        self.active_target_landmark = str(step.get("primary_landmark", "")).strip()
        self.active_prompt = normalize_grounding_prompt(
            str(step.get("grounding_prompt", "")),
            self.active_target_landmark,
        )
        prompt_key = f"{payload.get('mission_id', '')}:{step.get('step_id')}:{self.active_prompt}"
        if prompt_key != self.last_prompt_key:
            self.last_prompt_key = prompt_key
            self._push_prompt(self.active_prompt)

    def _push_prompt(self, prompt: str) -> None:
        if not prompt:
            return
        if self.prompt_client is None or SetPrompt is None:
            self.get_logger().warn("Grounding DINO SetPrompt service type is unavailable.")
            return
        if not self.prompt_client.wait_for_service(timeout_sec=0.3):
            self.get_logger().warn("/set_prompt service is not available yet.")
            return
        request = SetPrompt.Request()
        request.prompt = prompt
        future = self.prompt_client.call_async(request)
        future.add_done_callback(self._on_prompt_response)
        self.pending_futures.append(future)
        self.get_logger().info(f"Updated Grounding DINO prompt: {prompt}")

    def _on_prompt_response(self, future) -> None:
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"Failed to update Grounding DINO prompt: {exc}")
        finally:
            self.pending_futures = [item for item in self.pending_futures if item is not future]

    def _on_detections(self, msg: Detection2DArray) -> None:
        if not self.active_step_payload:
            return
        step = self.active_step_payload.get("step") or {}
        mission_id = str(self.active_step_payload.get("mission_id", "")).strip()
        step_id = int(step.get("step_id", -1))
        target_landmark = self.active_target_landmark
        if not target_landmark or step_id < 0:
            return

        detection_dicts = []
        for det in msg.detections:
            if not det.results:
                continue
            hypothesis = det.results[0].hypothesis
            detection_dicts.append(
                {
                    "class_id": str(hypothesis.class_id),
                    "score": float(hypothesis.score),
                    "cx": float(det.bbox.center.position.x),
                    "cy": float(det.bbox.center.position.y),
                    "w": float(det.bbox.size_x),
                    "h": float(det.bbox.size_y),
                }
            )

        best_detection = select_best_detection(detection_dicts, target_landmark)
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        if stamp <= 0:
            stamp = self.get_clock().now().nanoseconds / 1e9
        payload = build_landmark_detection_payload(
            mission_id=mission_id,
            step_id=step_id,
            target_landmark=target_landmark,
            best_detection=best_detection,
            image_frame=msg.header.frame_id or "padded_image",
            stamp=stamp,
        )
        output = String()
        output.data = dumps_json(payload)
        self.detection_pub.publish(output)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = LandmarkLocatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
