from __future__ import annotations

from typing import Any

from .landmark_logic import landmark_display_name, normalize_grounding_prompt
from .schemas import RouteRequestSpec, SchemaError
from .topics import CAMERA_IMAGE_TOPIC


def _optional_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SchemaError(f"'{key}' must be a string when provided")
    return value.strip()


def _optional_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SchemaError(f"'{key}' must be a list of strings when provided")
    return [item.strip() for item in value if item.strip()]


def coerce_route_plan_payload(
    raw_payload: dict[str, Any],
    request: RouteRequestSpec,
) -> dict[str, Any]:
    if not isinstance(raw_payload, dict):
        raise SchemaError("Route plan output must be a JSON object")
    steps_raw = raw_payload.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise SchemaError("'steps' must be a non-empty list")

    mission_text = _optional_str(raw_payload, "mission_text") or request.goal_text
    camera_source = _optional_str(raw_payload, "camera_source") or request.camera_source
    if not camera_source:
        camera_source = CAMERA_IMAGE_TOPIC

    normalized_steps: list[dict[str, Any]] = []
    for index, step_raw in enumerate(steps_raw, start=1):
        if not isinstance(step_raw, dict):
            raise SchemaError("Each route plan step must be a JSON object")
        instruction = _optional_str(step_raw, "instruction")
        visual_goal = _optional_str(step_raw, "visual_goal")
        if not instruction:
            raise SchemaError(f"Step {index} is missing 'instruction'")
        if not visual_goal:
            raise SchemaError(f"Step {index} is missing 'visual_goal'")
        expected_landmarks = _optional_str_list(step_raw, "expected_landmarks")
        scene_description = _optional_str(step_raw, "scene_description") or visual_goal
        primary_landmark = _optional_str(step_raw, "primary_landmark")
        if not primary_landmark:
            if expected_landmarks:
                primary_landmark = expected_landmarks[0]
            else:
                primary_landmark = landmark_display_name(visual_goal)
        grounding_prompt = normalize_grounding_prompt(
            _optional_str(step_raw, "grounding_prompt"),
            primary_landmark,
        )
        step_id = step_raw.get("step_id", index)
        if not isinstance(step_id, int):
            raise SchemaError(f"Step {index} has invalid 'step_id'")
        normalized_steps.append(
            {
                "step_id": step_id,
                "instruction": instruction,
                "visual_goal": visual_goal,
                "scene_description": scene_description,
                "expected_landmarks": expected_landmarks,
                "primary_landmark": primary_landmark,
                "grounding_prompt": grounding_prompt,
                "control_primitive": _optional_str(step_raw, "control_primitive")
                or "move_forward_until_recheck",
                "votes_needed": step_raw.get("votes_needed", 3),
                "confidence_threshold": step_raw.get("confidence_threshold", 0.75),
                "min_dwell_sec": step_raw.get("min_dwell_sec", 2.0),
                "timeout_sec": step_raw.get("timeout_sec", 12.0),
                "fallback": _optional_str(step_raw, "fallback") or "pause",
            }
        )

    inference_interval_sec = raw_payload.get(
        "inference_interval_sec", request.inference_interval_sec
    )
    if not isinstance(inference_interval_sec, (int, float)):
        raise SchemaError("'inference_interval_sec' must be numeric")

    return {
        "mission_id": _optional_str(raw_payload, "mission_id") or request.mission_id,
        "mission_text": mission_text,
        "environment_id": _optional_str(raw_payload, "environment_id")
        or request.environment_id,
        "camera_source": camera_source,
        "inference_interval_sec": float(inference_interval_sec),
        "steps": normalized_steps,
    }
