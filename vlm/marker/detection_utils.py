from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class DetectionRecord:
    class_id: str
    score: float
    bbox: dict[str, float]

    @property
    def canonical_class_id(self) -> str:
        return canonicalize_class_id(self.class_id)


def canonicalize_class_id(value: str) -> str:
    text = value.strip().lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_target_filter(target_filter: str) -> set[str]:
    if not target_filter.strip():
        return set()
    parts = re.split(r"[;,\n.]+", target_filter)
    return {
        canonicalize_class_id(part)
        for part in parts
        if canonicalize_class_id(part)
    }


def target_matches(class_id: str, target_filter: str) -> bool:
    targets = split_target_filter(target_filter)
    if not targets:
        return True
    return canonicalize_class_id(class_id) in targets


def detection_to_record(detection: Any) -> DetectionRecord | None:
    if not getattr(detection, "results", None):
        return None
    hypothesis = detection.results[0].hypothesis
    class_id = str(getattr(hypothesis, "class_id", "")).strip()
    if not class_id:
        return None
    bbox = detection.bbox
    return DetectionRecord(
        class_id=class_id,
        score=float(getattr(hypothesis, "score", 0.0)),
        bbox={
            "cx": float(bbox.center.position.x),
            "cy": float(bbox.center.position.y),
            "w": float(bbox.size_x),
            "h": float(bbox.size_y),
        },
    )


def records_from_detection_array(message: Any) -> list[DetectionRecord]:
    records: list[DetectionRecord] = []
    for detection in getattr(message, "detections", []):
        record = detection_to_record(detection)
        if record is not None:
            records.append(record)
    return records
