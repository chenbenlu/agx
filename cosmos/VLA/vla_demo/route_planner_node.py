from __future__ import annotations

from collections import deque
from pathlib import Path
import subprocess
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse

import cv2
from cv_bridge import CvBridge
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .json_utils import dumps_json, extract_json_object, loads_json
from .prompting import build_route_planner_prompt
from .route_planning import coerce_route_plan_payload
from .schemas import MissionSpec, RouteRequestSpec, SchemaError
from .topics import CAMERA_IMAGE_TOPIC, ROUTE_PLAN_TOPIC, ROUTE_REQUEST_TOPIC, SET_MISSION_TOPIC

VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


class MockRoutePlannerBackend:
    def infer(
        self,
        request: RouteRequestSpec,
        prompt_text: str,
        media_flag: str,
        media_path: str,
    ) -> dict[str, Any]:
        del prompt_text, media_flag, media_path
        target_text = request.goal_text.strip() or "destination"
        return {
            "mission_id": request.mission_id,
            "mission_text": request.goal_text,
            "environment_id": request.environment_id,
            "camera_source": request.camera_source,
            "inference_interval_sec": request.inference_interval_sec,
            "steps": [
                {
                    "step_id": 1,
                    "instruction": "Move out from the current position and align with the main corridor.",
                    "visual_goal": "The main corridor fills most of the forward view.",
                    "scene_description": "A forward-facing corridor opens up ahead.",
                    "expected_landmarks": ["corridor"],
                    "primary_landmark": "corridor",
                    "grounding_prompt": "corridor.",
                    "control_primitive": "move_forward_until_recheck",
                    "votes_needed": 2,
                    "confidence_threshold": 0.7,
                    "min_dwell_sec": 1.5,
                    "timeout_sec": 10.0,
                    "fallback": "pause",
                },
                {
                    "step_id": 2,
                    "instruction": "Continue toward the most distinctive waypoint on the route.",
                    "visual_goal": f"A clear waypoint that leads toward {target_text} becomes visible.",
                    "scene_description": "The route should expose a distinctive waypoint or branch.",
                    "expected_landmarks": ["waypoint_marker"],
                    "primary_landmark": "waypoint marker",
                    "grounding_prompt": "waypoint marker.",
                    "control_primitive": "move_forward_until_recheck",
                    "votes_needed": 2,
                    "confidence_threshold": 0.7,
                    "min_dwell_sec": 1.5,
                    "timeout_sec": 12.0,
                    "fallback": "pause",
                },
                {
                    "step_id": 3,
                    "instruction": f"Approach the final destination area for {target_text}.",
                    "visual_goal": f"The destination area for {target_text} is centered ahead.",
                    "scene_description": "The target destination area is visible in front of the robot.",
                    "expected_landmarks": ["destination_area"],
                    "primary_landmark": "destination area",
                    "grounding_prompt": "destination area.",
                    "control_primitive": "approach_target_zone",
                    "votes_needed": 2,
                    "confidence_threshold": 0.75,
                    "min_dwell_sec": 1.5,
                    "timeout_sec": 12.0,
                    "fallback": "stop_and_hold",
                },
            ],
        }


class CosmosCLIBackend:
    def __init__(
        self,
        python_executable: str,
        inference_script: str,
        host: str,
        port: int,
        model: str,
        timeout_sec: float,
    ) -> None:
        self.python_executable = python_executable
        self.inference_script = inference_script
        self.host = host
        self.port = port
        self.model = model
        self.timeout_sec = timeout_sec

    def infer(
        self,
        request: RouteRequestSpec,
        prompt_text: str,
        media_flag: str,
        media_path: str,
    ) -> dict[str, Any]:
        del request
        cmd = [
            self.python_executable,
            self.inference_script,
            "online",
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--prompt",
            prompt_text,
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.extend([media_flag, media_path])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return extract_json_object(result.stdout)


class RoutePlannerNode(Node):
    def __init__(self) -> None:
        super().__init__("vla_route_planner")

        self.declare_parameter("backend_mode", "cosmos_cli")
        self.declare_parameter("python_executable", "python3")
        self.declare_parameter("inference_script", "/workspaces/cosmos_ws/inference.py")
        self.declare_parameter("host", "localhost")
        self.declare_parameter("port", 8000)
        self.declare_parameter("model", "")
        self.declare_parameter("backend_timeout_sec", 120.0)
        self.declare_parameter("max_buffer_sec", 20.0)
        self.declare_parameter("video_fps_fallback", 8.0)

        backend_mode = str(self.get_parameter("backend_mode").value)
        if backend_mode == "mock":
            self.backend = MockRoutePlannerBackend()
        else:
            self.backend = CosmosCLIBackend(
                python_executable=str(self.get_parameter("python_executable").value),
                inference_script=str(self.get_parameter("inference_script").value),
                host=str(self.get_parameter("host").value),
                port=int(self.get_parameter("port").value),
                model=str(self.get_parameter("model").value),
                timeout_sec=float(self.get_parameter("backend_timeout_sec").value),
            )

        self.bridge = CvBridge()
        self.frame_buffer: deque[tuple[float, Any]] = deque()
        self.camera_subscription = None
        self.camera_topic = ""

        self.route_plan_pub = self.create_publisher(String, ROUTE_PLAN_TOPIC, 10)
        self.set_mission_pub = self.create_publisher(String, SET_MISSION_TOPIC, 10)
        self.create_subscription(String, ROUTE_REQUEST_TOPIC, self._on_route_request, 10)
        self._ensure_camera_subscription(CAMERA_IMAGE_TOPIC)

        self.get_logger().info(
            f"Route planner ready in '{backend_mode}' mode. Listening on {ROUTE_REQUEST_TOPIC}."
        )

    def _ensure_camera_subscription(self, topic: str) -> None:
        normalized_topic = topic.strip() or CAMERA_IMAGE_TOPIC
        if normalized_topic == self.camera_topic and self.camera_subscription is not None:
            return
        if self.camera_subscription is not None:
            self.destroy_subscription(self.camera_subscription)
        self.frame_buffer.clear()
        self.camera_topic = normalized_topic
        self.camera_subscription = self.create_subscription(
            Image,
            normalized_topic,
            self._on_image,
            10,
        )
        self.get_logger().info(f"Route planner camera source set to {normalized_topic}")

    def _on_image(self, msg: Image) -> None:
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        if stamp <= 0:
            stamp = self._now()
        self.frame_buffer.append((stamp, frame))
        max_buffer_sec = float(self.get_parameter("max_buffer_sec").value)
        while self.frame_buffer and (stamp - self.frame_buffer[0][0]) > max_buffer_sec:
            self.frame_buffer.popleft()

    def _on_route_request(self, msg: String) -> None:
        try:
            payload = loads_json(msg.data, "route_request")
            request = RouteRequestSpec.from_dict(payload)
            if request.source_mode == "live_camera":
                self._ensure_camera_subscription(request.camera_source)
                with tempfile.TemporaryDirectory(prefix="vla_route_media_") as tempdir:
                    media_flag, media_path = self._prepare_live_media(request, Path(tempdir))
                    prompt_text = build_route_planner_prompt(request)
                    raw_plan = self.backend.infer(request, prompt_text, media_flag, media_path)
            else:
                media_flag, media_path = self._prepare_uri_media(request.video_uri)
                prompt_text = build_route_planner_prompt(request)
                raw_plan = self.backend.infer(request, prompt_text, media_flag, media_path)
            normalized_plan = coerce_route_plan_payload(raw_plan, request)
            MissionSpec.from_dict(normalized_plan)
        except (OSError, RuntimeError, SchemaError, ValueError) as exc:
            self.get_logger().error(f"Route planning failed: {exc}")
            return

        output = String()
        output.data = dumps_json(normalized_plan)
        self.route_plan_pub.publish(output)
        self.set_mission_pub.publish(output)
        self.get_logger().info(
            f"Published route plan '{normalized_plan['mission_id']}' with "
            f"{len(normalized_plan['steps'])} steps."
        )

    def _prepare_uri_media(self, video_uri: str) -> tuple[str, str]:
        resolved = self._resolve_uri(video_uri)
        if resolved.startswith("http://") or resolved.startswith("https://"):
            suffix = Path(urlparse(resolved).path).suffix.lower()
        else:
            suffix = Path(resolved).suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            return "--images", resolved
        return "--videos", resolved

    def _prepare_live_media(
        self,
        request: RouteRequestSpec,
        temp_root: Path,
    ) -> tuple[str, str]:
        now = self._now()
        window_start = now - float(request.clip_duration_sec)
        frames = [(stamp, frame) for stamp, frame in self.frame_buffer if stamp >= window_start]
        if not frames:
            raise RuntimeError(
                f"No buffered frames available on {request.camera_source} for live route planning"
            )
        if len(frames) == 1:
            path = temp_root / "frame.jpg"
            cv2.imwrite(str(path), frames[-1][1])
            return "--images", str(path)

        path = temp_root / "clip.mp4"
        height, width = frames[0][1].shape[:2]
        fps = self._estimate_fps([stamp for stamp, _ in frames])
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        for _, frame in frames:
            writer.write(frame)
        writer.release()
        return "--videos", str(path)

    def _estimate_fps(self, stamps: list[float]) -> float:
        if len(stamps) < 2:
            return float(self.get_parameter("video_fps_fallback").value)
        intervals = [
            current - previous
            for previous, current in zip(stamps[:-1], stamps[1:])
            if (current - previous) > 0
        ]
        if not intervals:
            return float(self.get_parameter("video_fps_fallback").value)
        average_interval = sum(intervals) / len(intervals)
        if average_interval <= 0:
            return float(self.get_parameter("video_fps_fallback").value)
        return max(1.0, 1.0 / average_interval)

    def _resolve_uri(self, video_uri: str) -> str:
        parsed = urlparse(video_uri)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).expanduser()
            if not path.exists():
                raise OSError(f"Route planner media path does not exist: {path}")
            return str(path)
        if parsed.scheme in {"http", "https"}:
            return video_uri
        path = Path(video_uri).expanduser()
        if not path.exists():
            raise OSError(f"Route planner media path does not exist: {path}")
        return str(path.resolve())

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = RoutePlannerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
