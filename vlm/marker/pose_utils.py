from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class MapPose:
    x: float
    y: float
    yaw: float
    map_frame: str
    base_frame: str
    source: str


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def pose_from_transform(transform: Any, map_frame: str, base_frame: str) -> MapPose:
    translation = transform.transform.translation
    rotation = transform.transform.rotation
    return MapPose(
        x=float(translation.x),
        y=float(translation.y),
        yaw=quaternion_to_yaw(rotation.x, rotation.y, rotation.z, rotation.w),
        map_frame=map_frame,
        base_frame=base_frame,
        source="tf",
    )


def pose_from_amcl(message: Any, map_frame: str, base_frame: str) -> MapPose:
    pose = message.pose.pose
    orientation = pose.orientation
    return MapPose(
        x=float(pose.position.x),
        y=float(pose.position.y),
        yaw=quaternion_to_yaw(
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        ),
        map_frame=map_frame,
        base_frame=base_frame,
        source="amcl_pose",
    )


def distance_xy(first: MapPose, second: MapPose) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)
