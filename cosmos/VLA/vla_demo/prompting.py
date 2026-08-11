from __future__ import annotations

from .landmark_logic import landmark_display_name
from .schemas import MissionSpec, RouteRequestSpec, StepSpec


def build_reasoner_prompt(mission: MissionSpec, step: StepSpec) -> str:
    landmarks = ", ".join(step.expected_landmarks) if step.expected_landmarks else "none"
    return (
        "You are verifying the current AMR mission step from a recent camera clip. "
        "Judge only the active step and return strict JSON. "
        f"Mission: {mission.mission_text}. "
        f"Current step_id: {step.step_id}. "
        f"Instruction: {step.instruction}. "
        f"Visual goal: {step.visual_goal}. "
        f"Scene description: {step.scene_description}. "
        f"Expected landmarks: {landmarks}. "
        f"Primary landmark: {step.primary_landmark}. "
        "Return exactly one JSON object with keys "
        "step_id, step_match, step_completed, observed_landmarks, confidence, reason. "
        "Do not include markdown fences or extra text."
    )


def build_route_planner_prompt(request: RouteRequestSpec) -> str:
    return (
        "You are planning a short AMR route from the current visual context. "
        "Use only landmarks that are visible and easy to detect in the provided video clip. "
        "Do not use placeholders such as '...', 'unknown', 'same as above', or single numbers. "
        "All text fields must contain concrete content grounded in the observed scene. "
        f"Goal: {request.goal_text}. "
        f"Set mission_id exactly to '{request.mission_id}'. "
        f"Environment ID: {request.environment_id}. "
        f"Set environment_id exactly to '{request.environment_id}'. "
        f"Set camera_source exactly to '{request.camera_source}'. "
        f"Set inference_interval_sec exactly to {request.inference_interval_sec}. "
        "Produce 3 to 6 steps unless the scene clearly supports fewer. "
        "Return exactly one JSON object with keys "
        "mission_id, mission_text, environment_id, camera_source, inference_interval_sec, steps. "
        "Each item in steps must be a JSON object with keys "
        "step_id, instruction, visual_goal, scene_description, expected_landmarks, "
        "primary_landmark, grounding_prompt, control_primitive, votes_needed, "
        "confidence_threshold, min_dwell_sec, timeout_sec, fallback. "
        "Keep primary_landmark as one short noun phrase and make grounding_prompt include that same phrase. "
        "Write mission_text, instruction, visual_goal, and scene_description as concrete scene-aware sentences. "
        "Use phrase-style prompts suitable for open-vocabulary detection, such as "
        f"'{landmark_display_name('traffic_cone')}. {landmark_display_name('person')}.' "
        "Do not include markdown fences or extra text."
    )
