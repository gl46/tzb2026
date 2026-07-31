"""Shared public-observation prompt for QRM coarse training and inference."""

from __future__ import annotations

import json

from xh_agent.policy.qrm_lite.contracts import (
    FailureContextV1,
    QRMObservationV1,
)


def coarse_prompt(
    observation: QRMObservationV1,
    *,
    use_failure_context: bool,
    allowed_skills: list[str],
) -> str:
    tracks = [
        {
            "track_id": track.track_id,
            "category": track.category,
            "confidence": round(track.confidence, 4),
            "pose_xyzquat": track.pose_xyzquat,
        }
        for track in observation.perception_tracks
    ]
    context = (
        observation.failure_context.model_dump(mode="json")
        if use_failure_context
        else FailureContextV1().model_dump(mode="json")
    )
    payload = {
        "instruction": observation.instruction,
        "task_target_track_id": observation.task_target_track_id,
        "public_tracks": tracks,
        "joint_position": observation.joint_position,
        "gripper_state": observation.gripper_state,
        "current_skill_stage": observation.current_skill_stage,
        "failure_context": context,
        "allowed_skills": allowed_skills,
    }
    return (
        "Choose exactly one safe coarse industrial skill from allowed_skills. "
        "Simulator truth is unavailable. Context:\n"
        + json.dumps(payload, sort_keys=True)
    )
