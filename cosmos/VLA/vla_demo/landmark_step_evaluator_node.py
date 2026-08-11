from __future__ import annotations

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .json_utils import dumps_json, loads_json
from .landmark_logic import evaluate_landmark_detection
from .topics import CURRENT_STEP_TOPIC, INFERENCE_RESULT_TOPIC, LANDMARK_DETECTION_TOPIC


class LandmarkStepEvaluatorNode(Node):
    def __init__(self) -> None:
        super().__init__("landmark_step_evaluator")

        self.current_step_payload: dict = {}
        self.result_pub = self.create_publisher(String, INFERENCE_RESULT_TOPIC, 10)
        self.create_subscription(String, CURRENT_STEP_TOPIC, self._on_current_step, 10)
        self.create_subscription(
            String,
            LANDMARK_DETECTION_TOPIC,
            self._on_landmark_detection,
            10,
        )

        self.get_logger().info(
            "Landmark step evaluator ready. Bridging landmark detections to /vla/inference_result."
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
        self.current_step_payload = payload

    def _on_landmark_detection(self, msg: String) -> None:
        if not self.current_step_payload:
            return
        try:
            payload = loads_json(msg.data, "landmark_detection")
        except ValueError as exc:
            self.get_logger().warn(str(exc))
            return
        if not isinstance(payload, dict):
            self.get_logger().warn(
                "Ignoring landmark detection payload that is not a JSON object."
            )
            return
        step = self.current_step_payload.get("step") or {}
        current_step_id = step.get("step_id")
        if payload.get("step_id") != current_step_id:
            return
        result = evaluate_landmark_detection(self.current_step_payload, payload)
        output = String()
        output.data = dumps_json(result)
        self.result_pub.publish(output)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = LandmarkStepEvaluatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
