#!/usr/bin/env python3
# bbox_visualizer.py
#
# Subscribe:
#   /padded_image
#   /detections_output
#   /vla/landmark_detection
#
# Publish:
#   /annotated_image
#
# Main feature:
#   - draw_score_threshold: only draw bbox with score >= threshold
#   - target_filter: optionally draw only selected class / phrase
#   - label_alias_json: optionally map short label, e.g. "grey" -> "grey umbrella"

import json
from typing import Any

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray


# Color per class, BGR format
COLORS = [
    (0, 255, 0),      # green
    (0, 128, 255),    # orange
    (255, 0, 128),    # pink
    (255, 255, 0),    # cyan
    (0, 0, 255),      # red
    (255, 0, 0),      # blue
    (128, 255, 0),    # light green
    (128, 0, 255),    # purple
]


BEST_EFFORT_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)


class BboxVisualizer(Node):
    def __init__(self):
        super().__init__("bbox_visualizer")

        # -------------------------
        # ROS parameters
        # -------------------------
        self.declare_parameter("image_topic", "/padded_image")
        self.declare_parameter("detections_topic", "/detections_output")
        self.declare_parameter("target_topic", "/vla/landmark_detection")
        self.declare_parameter("annotated_topic", "/annotated_image")

        # 只畫出 score >= draw_score_threshold 的 bbox
        self.declare_parameter("draw_score_threshold", 0.75)

        # target banner / target cross marker 的最低分數
        self.declare_parameter("target_score_threshold", 0.75)

        # 可選：只顯示特定類別，例如：
        #   "grey umbrella"
        #   "grey umbrella,blue umbrella"
        # 空字串代表全部都畫
        self.declare_parameter("target_filter", "")

        # 是否顯示中心點座標 log
        self.declare_parameter("print_centers", True)

        # 是否在影像上畫 bbox 中心點
        self.declare_parameter("draw_centers", False)

        # 是否顯示 score
        self.declare_parameter("show_score", True)

        # 文字大小、線寬
        self.declare_parameter("font_scale", 0.6)
        self.declare_parameter("box_thickness", 2)

        # label 顯示修正：
        # 若 Grounding DINO 輸出 class_id="grey"，但你想顯示 "grey umbrella"，
        # 可以用這個 mapping。
        #
        # 注意：這只改「顯示文字」，不會改 detection 本身的語意。
        self.declare_parameter(
            "label_alias_json",
            json.dumps(
                {
                    "grey": "grey umbrella",
                    "gray": "grey umbrella",
                    "blue": "blue umbrella",
                    "red": "red umbrella",
                    "yellow": "yellow umbrella",
                    "black": "black umbrella",
                    "white": "white umbrella",
                }
            ),
        )

        self.image_topic = str(self.get_parameter("image_topic").value)
        self.detections_topic = str(self.get_parameter("detections_topic").value)
        self.target_topic = str(self.get_parameter("target_topic").value)
        self.annotated_topic = str(self.get_parameter("annotated_topic").value)

        self.draw_score_threshold = float(
            self.get_parameter("draw_score_threshold").value
        )
        self.target_score_threshold = float(
            self.get_parameter("target_score_threshold").value
        )
        self.target_filter = str(self.get_parameter("target_filter").value)

        self.print_centers = bool(self.get_parameter("print_centers").value)
        self.draw_centers = bool(self.get_parameter("draw_centers").value)
        self.show_score = bool(self.get_parameter("show_score").value)

        self.font_scale = float(self.get_parameter("font_scale").value)
        self.box_thickness = int(self.get_parameter("box_thickness").value)

        self.label_alias = self._load_label_alias()

        # -------------------------
        # Runtime state
        # -------------------------
        self.bridge = CvBridge()
        self.class_colors: dict[str, tuple[int, int, int]] = {}
        self.latest_detections = []
        self.latest_target: dict[str, Any] = {}

        self.frame_count = 0
        self.last_center_log_ns = 0

        # -------------------------
        # ROS subscriptions / publisher
        # -------------------------
        self.create_subscription(
            Detection2DArray,
            self.detections_topic,
            self.detections_cb,
            BEST_EFFORT_QOS,
        )

        self.create_subscription(
            String,
            self.target_topic,
            self.target_cb,
            10,
        )

        self.create_subscription(
            Image,
            self.image_topic,
            self.image_cb,
            BEST_EFFORT_QOS,
        )

        self.pub = self.create_publisher(
            Image,
            self.annotated_topic,
            10,
        )

        self.create_timer(5.0, self.log_stats)

        self.get_logger().info(
            "BboxVisualizer ready. "
            f"image_topic={self.image_topic}, "
            f"detections_topic={self.detections_topic}, "
            f"annotated_topic={self.annotated_topic}, "
            f"draw_score_threshold={self.draw_score_threshold:.2f}, "
            f"target_filter='{self.target_filter or '*'}'"
        )

    # -------------------------
    # Parameter helpers
    # -------------------------
    def _load_label_alias(self) -> dict[str, str]:
        raw = str(self.get_parameter("label_alias_json").value)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.get_logger().warn(
                "Failed to parse label_alias_json. Using empty alias map."
            )
            return {}

        if not isinstance(data, dict):
            self.get_logger().warn(
                "label_alias_json should be a JSON object. Using empty alias map."
            )
            return {}

        alias: dict[str, str] = {}
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            alias[key.strip().lower()] = value.strip()
        return alias

    def _target_filters(self) -> list[str]:
        if not self.target_filter:
            return []

        # 支援逗號與分號分隔
        raw_items = self.target_filter.replace(";", ",").split(",")
        return [item.strip().lower() for item in raw_items if item.strip()]

    def _matches_target_filter(self, class_id: str) -> bool:
        filters = self._target_filters()
        if not filters:
            return True

        class_lower = class_id.strip().lower()
        display_lower = self._display_class_id(class_id).strip().lower()

        for target in filters:
            if target in class_lower:
                return True
            if target in display_lower:
                return True
            if class_lower in target:
                return True
            if display_lower in target:
                return True

        return False

    def _display_class_id(self, class_id: str) -> str:
        key = class_id.strip().lower()
        return self.label_alias.get(key, class_id)

    # -------------------------
    # ROS callbacks
    # -------------------------
    def detections_cb(self, msg: Detection2DArray):
        # 這裡先保留原始 detections。
        # 實際畫圖時再依照 draw_score_threshold 過濾。
        self.latest_detections = msg.detections

    def target_cb(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        if isinstance(payload, dict):
            self.latest_target = payload

    def log_stats(self):
        self.get_logger().info(
            f"frames annotated: {self.frame_count}, "
            f"cached detections: {len(self.latest_detections)}, "
            f"draw_score_threshold: {self.draw_score_threshold:.2f}"
        )

    # -------------------------
    # Drawing helpers
    # -------------------------
    def get_color(self, class_id: str) -> tuple[int, int, int]:
        key = self._display_class_id(class_id)

        if key not in self.class_colors:
            idx = len(self.class_colors) % len(COLORS)
            self.class_colors[key] = COLORS[idx]

        return self.class_colors[key]

    def _best_result(self, det):
        if not det.results:
            return None

        return max(
            det.results,
            key=lambda result: float(result.hypothesis.score),
        )

    def _clamp_bbox(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        width: int,
        height: int,
    ) -> tuple[int, int, int, int]:
        x1 = max(0, min(x1, width - 1))
        y1 = max(0, min(y1, height - 1))
        x2 = max(0, min(x2, width - 1))
        y2 = max(0, min(y2, height - 1))
        return x1, y1, x2, y2

    def _draw_label(
        self,
        frame,
        x1: int,
        y1: int,
        label: str,
        color: tuple[int, int, int],
    ):
        font = cv2.FONT_HERSHEY_SIMPLEX
        thickness = 1

        (tw, th), baseline = cv2.getTextSize(
            label,
            font,
            self.font_scale,
            thickness,
        )

        label_y1 = max(0, y1 - th - baseline - 8)
        label_y2 = max(th + baseline + 8, y1)

        cv2.rectangle(
            frame,
            (x1, label_y1),
            (x1 + tw + 6, label_y2),
            color,
            -1,
        )

        text_y = label_y2 - baseline - 4
        cv2.putText(
            frame,
            label,
            (x1 + 3, text_y),
            font,
            self.font_scale,
            (0, 0, 0),
            thickness,
            cv2.LINE_AA,
        )

    def _make_label(self, class_id: str, score: float) -> str:
        display_class = self._display_class_id(class_id)

        if self.show_score:
            return f"{display_class} {score:.2f}"

        return display_class

    def _draw_detection(self, frame, det, center_reports: list[str]):
        result = self._best_result(det)
        if result is None:
            return

        hyp = result.hypothesis
        raw_class_id = str(hyp.class_id)
        score = float(hyp.score)

        # -------------------------
        # 核心：低於門檻就不畫
        # -------------------------
        if score < self.draw_score_threshold:
            return

        if not self._matches_target_filter(raw_class_id):
            return

        img_h, img_w = frame.shape[:2]

        cx = float(det.bbox.center.position.x)
        cy = float(det.bbox.center.position.y)
        w = float(det.bbox.size_x)
        h = float(det.bbox.size_y)

        x1 = int(cx - w / 2.0)
        y1 = int(cy - h / 2.0)
        x2 = int(cx + w / 2.0)
        y2 = int(cy + h / 2.0)

        x1, y1, x2, y2 = self._clamp_bbox(x1, y1, x2, y2, img_w, img_h)

        # 避免無效 bbox
        if x2 <= x1 or y2 <= y1:
            return

        cx_i = int(cx)
        cy_i = int(cy)

        color = self.get_color(raw_class_id)

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            color,
            self.box_thickness,
        )

        if self.draw_centers:
            cv2.circle(frame, (cx_i, cy_i), 4, color, -1)

        label = self._make_label(raw_class_id, score)
        self._draw_label(frame, x1, y1, label, color)

        center_reports.append(
            f"{self._display_class_id(raw_class_id)}@({cx_i},{cy_i}) s={score:.2f}"
        )

    def _draw_target_banner(self, frame):
        if not isinstance(self.latest_target, dict):
            return

        target_landmark = str(self.latest_target.get("target_landmark", ""))
        if not target_landmark:
            return

        found = bool(self.latest_target.get("found", False))
        score = float(self.latest_target.get("score", 0.0))

        # target score 太低時，不顯示 found=True
        if score < self.target_score_threshold:
            found = False

        banner = f"target={target_landmark} found={found} score={score:.2f}"

        cv2.rectangle(frame, (8, 8), (560, 42), (32, 32, 32), -1)
        cv2.putText(
            frame,
            banner,
            (14, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    def _draw_target_cross(self, frame):
        if not isinstance(self.latest_target, dict):
            return

        found = bool(self.latest_target.get("found", False))
        score = float(self.latest_target.get("score", 0.0))

        if not found:
            return

        if score < self.target_score_threshold:
            return

        bbox = self.latest_target.get("bbox", {})
        if not isinstance(bbox, dict):
            return

        try:
            cx = int(float(bbox.get("cx", 0.0)))
            cy = int(float(bbox.get("cy", 0.0)))
        except (TypeError, ValueError):
            return

        img_h, img_w = frame.shape[:2]
        if cx < 0 or cx >= img_w or cy < 0 or cy >= img_h:
            return

        cv2.drawMarker(
            frame,
            (cx, cy),
            (255, 255, 255),
            markerType=cv2.MARKER_CROSS,
            markerSize=18,
            thickness=2,
        )

        cv2.circle(
            frame,
            (cx, cy),
            6,
            (255, 255, 255),
            1,
        )

    def _log_centers(self, center_reports: list[str]):
        if not self.print_centers:
            return

        if not center_reports:
            return

        now_ns = self.get_clock().now().nanoseconds

        # 每 0.5 秒印一次，避免洗版
        if (now_ns - self.last_center_log_ns) < 500_000_000:
            return

        print("centers: " + " | ".join(center_reports), flush=True)
        self.last_center_log_ns = now_ns

    def image_cb(self, img_msg: Image):
        try:
            frame = self.bridge.imgmsg_to_cv2(
                img_msg,
                desired_encoding="bgr8",
            )
        except Exception as exc:
            self.get_logger().warn(f"Failed to convert image: {exc}")
            return

        center_reports: list[str] = []

        for det in self.latest_detections:
            self._draw_detection(frame, det, center_reports)

        self._log_centers(center_reports)

        self._draw_target_banner(frame)
        self._draw_target_cross(frame)

        out_msg = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        out_msg.header = img_msg.header
        self.pub.publish(out_msg)

        self.frame_count += 1


def main(args=None):
    rclpy.init(args=args)
    node = BboxVisualizer()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()