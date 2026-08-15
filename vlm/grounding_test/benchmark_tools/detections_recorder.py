#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import rclpy
from rclpy.node import Node
from vision_msgs.msg import Detection2DArray


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", type=str, default="/detections_output")
    parser.add_argument("--output-csv", type=str, required=True)
    parser.add_argument("--summary-json", type=str, default="")
    parser.add_argument("--model-tag", type=str, required=True, help="e.g. grounding_dino / yolov8")
    return parser.parse_args()


def get_bbox_xyxy(bbox):
    center = bbox.center
    if hasattr(center, "position"):
        cx = float(center.position.x)
        cy = float(center.position.y)
    else:
        cx = float(center.x)
        cy = float(center.y)

    w = float(bbox.size_x)
    h = float(bbox.size_y)
    x1 = cx - w / 2.0
    y1 = cy - h / 2.0
    x2 = cx + w / 2.0
    y2 = cy + h / 2.0
    return x1, y1, x2, y2


def best_hypothesis(results):
    best_label = ""
    best_score = -1.0
    for r in results:
        if hasattr(r, "hypothesis"):
            hyp = r.hypothesis
            label = str(getattr(hyp, "class_id", getattr(hyp, "id", "")))
            score = float(getattr(hyp, "score", 0.0))
        else:
            label = str(getattr(r, "id", ""))
            score = float(getattr(r, "score", 0.0))
        if score > best_score:
            best_score = score
            best_label = label
    return best_label, best_score


class DetectionsRecorder(Node):
    def __init__(self, args):
        super().__init__("detections_recorder")
        self.args = args
        output_path = Path(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.fp = open(output_path, "w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.fp)
        self.writer.writerow(
            [
                "model",
                "frame_key",
                "stamp_sec",
                "stamp_nanosec",
                "label_raw",
                "score",
                "x1",
                "y1",
                "x2",
                "y2",
                "is_empty",
            ]
        )

        self.message_count = 0
        self.det_count = 0
        self.unique_frames = set()
        self.first_stamp = None
        self.last_stamp = None

        self.sub = self.create_subscription(
            Detection2DArray,
            args.topic,
            self.callback,
            10,
        )
        self.get_logger().info(f"Recording {args.topic} -> {args.output_csv}")

    def callback(self, msg: Detection2DArray):
        self.message_count += 1
        frame_key = msg.header.frame_id or f"stamp_{msg.header.stamp.sec}_{msg.header.stamp.nanosec}"
        self.unique_frames.add(frame_key)

        stamp_tuple = (msg.header.stamp.sec, msg.header.stamp.nanosec)
        if self.first_stamp is None:
            self.first_stamp = stamp_tuple
        self.last_stamp = stamp_tuple

        if len(msg.detections) == 0:
            self.writer.writerow(
                [
                    self.args.model_tag,
                    frame_key,
                    msg.header.stamp.sec,
                    msg.header.stamp.nanosec,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    1,
                ]
            )
            self.fp.flush()
            return

        for det in msg.detections:
            label_raw, score = best_hypothesis(det.results)
            x1, y1, x2, y2 = get_bbox_xyxy(det.bbox)

            self.writer.writerow(
                [
                    self.args.model_tag,
                    frame_key,
                    msg.header.stamp.sec,
                    msg.header.stamp.nanosec,
                    label_raw,
                    score,
                    x1,
                    y1,
                    x2,
                    y2,
                    0,
                ]
            )
            self.det_count += 1

        self.fp.flush()

    def destroy_node(self):
        if self.args.summary_json:
            summary_path = Path(self.args.summary_json)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary = {
                "model": self.args.model_tag,
                "topic": self.args.topic,
                "message_count": self.message_count,
                "det_count": self.det_count,
                "unique_frames": len(self.unique_frames),
                "first_stamp": self.first_stamp,
                "last_stamp": self.last_stamp,
            }
            summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        self.fp.close()
        super().destroy_node()


def main():
    args = parse_args()
    rclpy.init()
    node = DetectionsRecorder(args)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()