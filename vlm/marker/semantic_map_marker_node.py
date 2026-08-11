#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any

from builtin_interfaces.msg import Duration
from geometry_msgs.msg import PoseWithCovarianceStamped
import rclpy
from rclpy.duration import Duration as RclpyDuration
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from rclpy.time import Time
from std_msgs.msg import String
import tf2_ros
from vision_msgs.msg import Detection2DArray
from visualization_msgs.msg import Marker, MarkerArray

from detection_utils import DetectionRecord, canonicalize_class_id, records_from_detection_array
from detection_utils import target_matches
from marker_palette import ColorRegistry, RgbaColor
from pose_utils import MapPose, distance_xy, pose_from_amcl, pose_from_transform


BEST_EFFORT_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
)

MARKER_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=20,
)


class SemanticMapMarkerNode(Node):
    def __init__(self) -> None:
        super().__init__("semantic_map_marker")

        self.declare_parameter("detections_topic", "/detections_output")
        self.declare_parameter("markers_topic", "/semantic_map/markers")
        self.declare_parameter("observation_topic", "/semantic_map/observation")
        self.declare_parameter("target_filter", "")
        self.declare_parameter("score_threshold", 0.75)
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("base_frame", "base_footprint")
        self.declare_parameter("use_tf_first", True)
        self.declare_parameter("mark_once_per_class", True)
        self.declare_parameter("min_distance_m", 0.5)
        self.declare_parameter("cooldown_sec", 2.0)
        self.declare_parameter("marker_lifetime_sec", 0.0)
        self.declare_parameter("tf_timeout_sec", 0.1)
        self.declare_parameter("republish_period_sec", 1.0)

        self.detections_topic = str(self.get_parameter("detections_topic").value)
        self.markers_topic = str(self.get_parameter("markers_topic").value)
        self.observation_topic = str(self.get_parameter("observation_topic").value)
        self.target_filter = str(self.get_parameter("target_filter").value)
        self.score_threshold = float(self.get_parameter("score_threshold").value)
        self.map_frame = str(self.get_parameter("map_frame").value)
        self.base_frame = str(self.get_parameter("base_frame").value)
        self.use_tf_first = bool(self.get_parameter("use_tf_first").value)
        self.mark_once_per_class = bool(
            self.get_parameter("mark_once_per_class").value
        )
        self.min_distance_m = float(self.get_parameter("min_distance_m").value)
        self.cooldown_sec = float(self.get_parameter("cooldown_sec").value)
        self.marker_lifetime_sec = float(
            self.get_parameter("marker_lifetime_sec").value
        )
        self.tf_timeout_sec = float(self.get_parameter("tf_timeout_sec").value)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.latest_amcl_pose: PoseWithCovarianceStamped | None = None

        self.colors = ColorRegistry()
        self.marker_id = 1
        self.active_markers: list[Marker] = []
        self.poses_by_class: dict[str, list[MapPose]] = {}
        self.last_marker_time_by_class: dict[str, float] = {}
        self.last_pose_warn_at = 0.0

        self.marker_pub = self.create_publisher(MarkerArray, self.markers_topic, MARKER_QOS)
        self.observation_pub = self.create_publisher(String, self.observation_topic, 10)
        self.create_subscription(
            Detection2DArray,
            self.detections_topic,
            self._on_detections,
            BEST_EFFORT_QOS,
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self._on_amcl_pose,
            10,
        )
        self.create_timer(
            float(self.get_parameter("republish_period_sec").value),
            self._republish_markers,
        )

        self.get_logger().info(
            "Semantic map marker ready. "
            f"detections={self.detections_topic}, markers={self.markers_topic}, "
            f"map_frame={self.map_frame}, base_frame={self.base_frame}, "
            f"target_filter='{self.target_filter or '*'}'"
        )

    def _on_amcl_pose(self, message: PoseWithCovarianceStamped) -> None:
        self.latest_amcl_pose = message

    def _on_detections(self, message: Detection2DArray) -> None:
        records = [
            record
            for record in records_from_detection_array(message)
            if record.score >= self.score_threshold
            and target_matches(record.class_id, self.target_filter)
        ]
        if not records:
            return

        pose = self._current_map_pose()
        if pose is None:
            self._warn_missing_pose()
            return

        new_markers: list[Marker] = []
        for record in records:
            now_sec = self._now_sec()
            if not self._should_mark(record, pose, now_sec):
                continue
            new_markers.extend(self._build_markers(record, pose))
            self._remember_observation(record, pose, now_sec)
            self._publish_observation(record, pose, message)

        if new_markers:
            self.active_markers.extend(new_markers)
            self._republish_markers()

    def _current_map_pose(self) -> MapPose | None:
        if self.use_tf_first:
            pose = self._lookup_tf_pose()
            if pose is not None:
                return pose
        if self.latest_amcl_pose is not None:
            return pose_from_amcl(self.latest_amcl_pose, self.map_frame, self.base_frame)
        if not self.use_tf_first:
            return self._lookup_tf_pose()
        return None

    def _lookup_tf_pose(self) -> MapPose | None:
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.base_frame,
                Time(),
                timeout=RclpyDuration(seconds=self.tf_timeout_sec),
            )
        except (
            tf2_ros.LookupException,
            tf2_ros.ConnectivityException,
            tf2_ros.ExtrapolationException,
            tf2_ros.TimeoutException,
        ):
            return None
        return pose_from_transform(transform, self.map_frame, self.base_frame)

    def _warn_missing_pose(self) -> None:
        now_sec = self._now_sec()
        if now_sec - self.last_pose_warn_at < 2.0:
            return
        self.last_pose_warn_at = now_sec
        self.get_logger().warn(
            f"No map pose available from TF {self.map_frame}->{self.base_frame} "
            "or /amcl_pose; skipping semantic marker."
        )

    def _should_mark(self, record: DetectionRecord, pose: MapPose, now_sec: float) -> bool:
        key = record.canonical_class_id
        if self.mark_once_per_class and key in self.poses_by_class:
            return False
        last_time = self.last_marker_time_by_class.get(key)
        if last_time is not None and now_sec - last_time < self.cooldown_sec:
            return False
        for previous_pose in self.poses_by_class.get(key, []):
            if distance_xy(previous_pose, pose) < self.min_distance_m:
                return False
        return True

    def _remember_observation(
        self,
        record: DetectionRecord,
        pose: MapPose,
        now_sec: float,
    ) -> None:
        key = record.canonical_class_id
        self.last_marker_time_by_class[key] = now_sec
        self.poses_by_class.setdefault(key, []).append(pose)

    def _build_markers(self, record: DetectionRecord, pose: MapPose) -> list[Marker]:
        color = self.colors.color_for(record.class_id)
        stamp = self.get_clock().now().to_msg()
        namespace = f"semantic_map/{canonicalize_class_id(record.class_id).replace(' ', '_') or 'unknown'}"
        sphere_id = self.marker_id
        text_id = self.marker_id + 1
        self.marker_id += 2

        sphere = Marker()
        sphere.header.frame_id = self.map_frame
        sphere.header.stamp = stamp
        sphere.ns = namespace
        sphere.id = sphere_id
        sphere.type = Marker.SPHERE
        sphere.action = Marker.ADD
        sphere.pose.position.x = pose.x
        sphere.pose.position.y = pose.y
        sphere.pose.position.z = 0.08
        sphere.pose.orientation.w = 1.0
        sphere.scale.x = 0.28
        sphere.scale.y = 0.28
        sphere.scale.z = 0.16
        self._apply_color(sphere, color)
        sphere.lifetime = self._marker_lifetime()

        text = Marker()
        text.header.frame_id = self.map_frame
        text.header.stamp = stamp
        text.ns = namespace
        text.id = text_id
        text.type = Marker.TEXT_VIEW_FACING
        text.action = Marker.ADD
        text.pose.position.x = pose.x
        text.pose.position.y = pose.y
        text.pose.position.z = 0.45
        text.pose.orientation.w = 1.0
        text.scale.z = 0.24
        self._apply_color(text, color)
        text.text = f"{record.class_id} {record.score:.2f}"
        text.lifetime = self._marker_lifetime()
        return [sphere, text]

    def _apply_color(self, marker: Marker, color: RgbaColor) -> None:
        marker.color.r = color.r
        marker.color.g = color.g
        marker.color.b = color.b
        marker.color.a = color.a

    def _marker_lifetime(self) -> Duration:
        lifetime = Duration()
        if self.marker_lifetime_sec <= 0.0:
            return lifetime
        lifetime.sec = int(self.marker_lifetime_sec)
        lifetime.nanosec = int((self.marker_lifetime_sec - lifetime.sec) * 1e9)
        return lifetime

    def _publish_observation(
        self,
        record: DetectionRecord,
        pose: MapPose,
        detection_message: Detection2DArray,
    ) -> None:
        stamp = detection_message.header.stamp.sec + (
            detection_message.header.stamp.nanosec / 1e9
        )
        if stamp <= 0.0:
            stamp = self._now_sec()
        payload: dict[str, Any] = {
            "class_id": record.class_id,
            "score": record.score,
            "bbox": record.bbox,
            "pose": {
                "x": pose.x,
                "y": pose.y,
                "yaw": pose.yaw,
            },
            "map_frame": pose.map_frame,
            "base_frame": pose.base_frame,
            "stamp": stamp,
            "source": "grounding_dino_amcl",
            "pose_source": pose.source,
        }
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.observation_pub.publish(message)

    def _republish_markers(self) -> None:
        if not self.active_markers:
            return
        array = MarkerArray()
        array.markers = list(self.active_markers)
        stamp = self.get_clock().now().to_msg()
        for marker in array.markers:
            marker.header.stamp = stamp
        self.marker_pub.publish(array)

    def _now_sec(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SemanticMapMarkerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
