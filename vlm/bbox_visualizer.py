#!/usr/bin/env python3
# bbox_visualizer.py — Subscribe to /camera/camera/color/image_raw + /detections_output,
# draw bounding boxes, publish /annotated_image

import json

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray
from cv_bridge import CvBridge
import cv2

# Color per class (BGR)
COLORS = [
    (0, 255, 0),    # green
    (0, 128, 255),  # orange
    (255, 0, 128),  # pink
    (255, 255, 0),  # cyan
    (0, 0, 255),    # red
]

BEST_EFFORT_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)


class BboxVisualizer(Node):
    def __init__(self):
        super().__init__('bbox_visualizer')
        self.bridge = CvBridge()
        self.class_colors = {}
        self.latest_detections = []  # cache latest detections
        self.latest_target = {}

        self.create_subscription(
            Detection2DArray, '/detections_output',
            self.detections_cb, BEST_EFFORT_QOS,
        )
        self.create_subscription(
            String, '/vla/landmark_detection',
            self.target_cb, 10,
        )
        self.create_subscription(
            Image, '/padded_image',
            self.image_cb, BEST_EFFORT_QOS,
        )
        self.pub = self.create_publisher(Image, '/annotated_image', 10)
        self.frame_count = 0
        self.last_center_log_ns = 0
        self.create_timer(5.0, self.log_stats)
        self.get_logger().info('BboxVisualizer ready — publishing /annotated_image')

    def detections_cb(self, msg: Detection2DArray):
        self.latest_detections = msg.detections

    def target_cb(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            self.latest_target = payload

    def log_stats(self):
        self.get_logger().info(f'frames annotated: {self.frame_count}, cached detections: {len(self.latest_detections)}')

    def get_color(self, class_id: str):
        if class_id not in self.class_colors:
            idx = len(self.class_colors) % len(COLORS)
            self.class_colors[class_id] = COLORS[idx]
        return self.class_colors[class_id]

    def image_cb(self, img_msg: Image):
        frame = self.bridge.imgmsg_to_cv2(img_msg, desired_encoding='bgr8')
        center_reports = []

        for det in self.latest_detections:
            if not det.results:
                continue
            hyp = det.results[0].hypothesis
            class_id = hyp.class_id
            score = hyp.score

            cx = det.bbox.center.position.x
            cy = det.bbox.center.position.y
            w = det.bbox.size_x
            h = det.bbox.size_y

            x1 = int(cx - w / 2)
            y1 = int(cy - h / 2)
            x2 = int(cx + w / 2)
            y2 = int(cy + h / 2)
            cx_i = int(cx)
            cy_i = int(cy)

            color = self.get_color(class_id)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            # cv2.circle(frame, (cx_i, cy_i), 4, color, -1)

            label = f'{class_id} {score:.2f}'
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
        # 中心點座標
            center_reports.append(f'{class_id}@({cx_i},{cy_i}) s={score:.2f}')
        now_ns = self.get_clock().now().nanoseconds
        if center_reports and (now_ns - self.last_center_log_ns) >= 500_000_000:
            print('centers: ' + ' | '.join(center_reports), flush=True)
            self.last_center_log_ns = now_ns

        target_landmark = str(self.latest_target.get('target_landmark', ''))
        found = bool(self.latest_target.get('found', False))
        score = float(self.latest_target.get('score', 0.0))
        if target_landmark:
            banner = f'target={target_landmark} found={found} score={score:.2f}'
            cv2.rectangle(frame, (8, 8), (440, 38), (32, 32, 32), -1)
            cv2.putText(frame, banner, (14, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        bbox = self.latest_target.get('bbox', {}) if isinstance(self.latest_target, dict) else {}
        if found and isinstance(bbox, dict):
            cx = int(float(bbox.get('cx', 0.0)))
            cy = int(float(bbox.get('cy', 0.0)))
            cv2.drawMarker(frame, (cx, cy), (255, 255, 255),
                           markerType=cv2.MARKER_CROSS, markerSize=18, thickness=2)
            cv2.circle(frame, (cx, cy), 6, (255, 255, 255), 1)

        out_msg = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
        out_msg.header = img_msg.header
        self.pub.publish(out_msg)
        self.frame_count += 1


def main():
    rclpy.init()
    node = BboxVisualizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.try_shutdown()


if __name__ == '__main__':
    main()
