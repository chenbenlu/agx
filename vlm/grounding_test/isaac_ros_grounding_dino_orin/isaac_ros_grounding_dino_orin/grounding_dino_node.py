from __future__ import annotations

from pathlib import Path

from cv_bridge import CvBridge
import rclpy
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2D
from vision_msgs.msg import Detection2DArray
from vision_msgs.msg import ObjectHypothesisWithPose

from .modeling import (
    GroundingDINOModelRunner,
    default_grounding_dino_repo_path,
    draw_detections,
)


class GroundingDINOOrinNode(Node):
    def __init__(self) -> None:
        super().__init__("grounding_dino_orin_node")

        repo_path_guess = default_grounding_dino_repo_path()
        config_guess = repo_path_guess / "groundingdino/config/GroundingDINO_SwinT_OGC.py"
        weights_guess = Path(__file__).resolve().parents[2] / "weights/groundingdino_swint_ogc.pth"

        self.declare_parameter("grounding_dino_repo_path", str(repo_path_guess))
        self.declare_parameter("config_path", str(config_guess))
        self.declare_parameter("weights_path", str(weights_guess))
        self.declare_parameter("prompt", "person.")
        self.declare_parameter("box_threshold", 0.35)
        self.declare_parameter("text_threshold", 0.25)
        self.declare_parameter("device", "cuda")
        self.declare_parameter("use_fp16", False)
        self.declare_parameter("publish_annotated_image", True)

        self.prompt = self.get_parameter("prompt").get_parameter_value().string_value
        self.box_threshold = float(
            self.get_parameter("box_threshold").get_parameter_value().double_value
        )
        self.text_threshold = float(
            self.get_parameter("text_threshold").get_parameter_value().double_value
        )
        self.publish_annotated_image = bool(
            self.get_parameter("publish_annotated_image").get_parameter_value().bool_value
        )
        self.bridge = CvBridge()

        repo_path = self.get_parameter("grounding_dino_repo_path").value
        config_path = self.get_parameter("config_path").value
        weights_path = self.get_parameter("weights_path").value
        device = self.get_parameter("device").value
        use_fp16 = bool(self.get_parameter("use_fp16").value)

        self.get_logger().info(f"Loading GroundingDINO from {repo_path}")
        self.runner = GroundingDINOModelRunner(
            repo_path=repo_path,
            config_path=config_path,
            weights_path=weights_path,
            device=device,
            use_fp16=use_fp16,
        )
        self.get_logger().info("GroundingDINO model loaded.")

        qos = QoSPresetProfiles.SENSOR_DATA.value
        self.image_sub = self.create_subscription(
            Image,
            "image",
            self.image_callback,
            qos,
        )
        self.detections_pub = self.create_publisher(Detection2DArray, "detections_output", 10)
        self.annotated_pub = self.create_publisher(Image, "annotated_image", 10)
        self.add_on_set_parameters_callback(self.parameters_callback)

    def parameters_callback(self, params):
        for param in params:
            if param.name == "prompt" and param.type_ == param.Type.STRING:
                self.prompt = param.value
            elif param.name == "box_threshold":
                self.box_threshold = float(param.value)
            elif param.name == "text_threshold":
                self.text_threshold = float(param.value)
            elif param.name == "publish_annotated_image":
                self.publish_annotated_image = bool(param.value)
        return SetParametersResult(successful=True)

    def image_callback(self, msg: Image) -> None:
        image_bgr = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        detections = self.runner.predict(
            image_bgr=image_bgr,
            prompt=self.prompt,
            box_threshold=self.box_threshold,
            text_threshold=self.text_threshold,
        )

        detection_array = Detection2DArray()
        detection_array.header = msg.header

        for det in detections:
            result = Detection2D()
            result.header = msg.header

            x1, y1, x2, y2 = det.xyxy
            bbox_width = float(x2 - x1)
            bbox_height = float(y2 - y1)
            center_x = float(x1 + (bbox_width / 2.0))
            center_y = float(y1 + (bbox_height / 2.0))

            self._set_bbox_center(result, center_x=center_x, center_y=center_y)
            result.bbox.size_x = bbox_width
            result.bbox.size_y = bbox_height

            hypothesis = ObjectHypothesisWithPose()
            hypothesis.hypothesis.class_id = det.phrase
            hypothesis.hypothesis.score = float(det.score)
            result.results.append(hypothesis)
            detection_array.detections.append(result)

        self.detections_pub.publish(detection_array)

        if self.publish_annotated_image:
            annotated = draw_detections(image_bgr=image_bgr, detections=detections)
            annotated_msg = self.bridge.cv2_to_imgmsg(annotated, encoding="bgr8")
            annotated_msg.header = msg.header
            self.annotated_pub.publish(annotated_msg)

    def destroy_node(self) -> bool:
        self.get_logger().info("Shutting down GroundingDINO Orin node.")
        return super().destroy_node()

    @staticmethod
    def _set_bbox_center(result: Detection2D, center_x: float, center_y: float) -> None:
        center = result.bbox.center
        if hasattr(center, "position"):
            center.position.x = center_x
            center.position.y = center_y
        else:
            center.x = center_x
            center.y = center_y


def main() -> None:
    rclpy.init()
    node = GroundingDINOOrinNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
