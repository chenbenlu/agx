#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image


def parse_args():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", type=str, help="Path to input MP4/video")
    group.add_argument("--image", type=str, help="Path to single test image")

    parser.add_argument("--image-topic", type=str, default="/image")
    parser.add_argument("--camera-info-topic", type=str, default="/camera_info")
    parser.add_argument("--fps", type=float, default=0.0, help="Override video FPS. 0 = use file FPS")
    parser.add_argument("--frame-step", type=int, default=1, help="Publish every Nth frame")
    parser.add_argument("--loop-video", action="store_true", help="Loop video input")
    parser.add_argument("--image-rate", type=float, default=2.0, help="Image repeat rate in Hz")
    parser.add_argument("--frame-id-prefix", type=str, default="frame")
    parser.add_argument("--camera-frame", type=str, default="camera_frame")
    parser.add_argument("--manifest-csv", type=str, default="", help="Optional manifest CSV output")
    return parser.parse_args()


class BenchmarkMediaPublisher(Node):
    def __init__(self, args):
        super().__init__("benchmark_media_publisher")
        self.args = args
        self.bridge = CvBridge()
        self.image_pub = self.create_publisher(Image, args.image_topic, 10)
        self.camera_info_pub = self.create_publisher(CameraInfo, args.camera_info_topic, 10)

        self.manifest_fp = None
        self.manifest_writer = None
        if args.manifest_csv:
            manifest_path = Path(args.manifest_csv)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self.manifest_fp = open(manifest_path, "w", newline="", encoding="utf-8")
            self.manifest_writer = csv.writer(self.manifest_fp)
            self.manifest_writer.writerow(
                ["frame_key", "stamp_sec", "stamp_nanosec", "source_frame_index", "width", "height"]
            )

        self.video_mode = bool(args.video)
        self.current_source_frame = 0

        if self.video_mode:
            self.cap = cv2.VideoCapture(args.video)
            if not self.cap.isOpened():
                raise RuntimeError(f"Failed to open video: {args.video}")

            file_fps = float(self.cap.get(cv2.CAP_PROP_FPS))
            if args.fps > 0:
                self.pub_fps = args.fps
            elif file_fps > 0:
                self.pub_fps = file_fps
            else:
                self.pub_fps = 30.0

            self.timer = self.create_timer(1.0 / self.pub_fps, self.publish_video_frame)
            self.get_logger().info(
                f"Video mode. video={args.video}, publish_fps={self.pub_fps:.3f}, frame_step={args.frame_step}"
            )
        else:
            self.image_bgr = cv2.imread(args.image, cv2.IMREAD_COLOR)
            if self.image_bgr is None:
                raise RuntimeError(f"Failed to read image: {args.image}")
            self.timer = self.create_timer(1.0 / max(args.image_rate, 0.1), self.publish_single_image)
            self.get_logger().info(
                f"Image mode. image={args.image}, publish_rate={args.image_rate:.3f} Hz"
            )

    def destroy_node(self):
        if hasattr(self, "cap"):
            self.cap.release()
        if self.manifest_fp is not None:
            self.manifest_fp.close()
        super().destroy_node()

    def _publish(self, frame_bgr, source_frame_index: int):
        stamp = self.get_clock().now().to_msg()
        frame_key = f"{self.args.frame_id_prefix}_{source_frame_index:06d}"

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image_msg = self.bridge.cv2_to_imgmsg(frame_rgb, encoding="rgb8")
        image_msg.header.stamp = stamp
        image_msg.header.frame_id = frame_key

        cam_info = CameraInfo()
        cam_info.header = image_msg.header
        cam_info.width = frame_bgr.shape[1]
        cam_info.height = frame_bgr.shape[0]
        cam_info.distortion_model = "plumb_bob"
        cam_info.k = [0.0] * 9
        cam_info.p = [0.0] * 12
        cam_info.r = [0.0] * 9

        self.image_pub.publish(image_msg)
        self.camera_info_pub.publish(cam_info)

        if self.manifest_writer is not None:
            self.manifest_writer.writerow(
                [
                    frame_key,
                    stamp.sec,
                    stamp.nanosec,
                    source_frame_index,
                    frame_bgr.shape[1],
                    frame_bgr.shape[0],
                ]
            )
            self.manifest_fp.flush()

    def publish_video_frame(self):
        while True:
            ok, frame = self.cap.read()
            if not ok:
                if self.args.loop_video:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.current_source_frame = 0
                    ok, frame = self.cap.read()
                    if not ok:
                        self.get_logger().error("Failed to loop video.")
                        rclpy.shutdown()
                        return
                else:
                    self.get_logger().info("Video finished.")
                    rclpy.shutdown()
                    return

            self.current_source_frame += 1
            if self.current_source_frame % self.args.frame_step != 0:
                continue

            self._publish(frame, self.current_source_frame)
            return

    def publish_single_image(self):
        self._publish(self.image_bgr, 1)


def main():
    args = parse_args()
    rclpy.init()
    node = BenchmarkMediaPublisher(args)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()