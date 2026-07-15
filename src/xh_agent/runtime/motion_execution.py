"""Evidence model for distinguishing plans from executed robot motion."""

from __future__ import annotations

from dataclasses import dataclass

from .continuity import ContinuityResult


@dataclass(frozen=True)
class MotionSegmentEvidence:
    """Recorded S1 evidence for one standard-action trajectory segment."""

    planned: bool
    dispatched: bool
    action_endpoint: str | None
    action_goal_uuid: str | None
    controller_result: str | None
    duration_s: float | None
    max_final_joint_error_rad: float | None
    ee_position_error_m: float | None
    ee_orientation_error_rad: float | None
    continuity: ContinuityResult | None
    gazebo_set_pose_or_joint_called: bool
    moveit_model_matches_gazebo: bool
    scene_collision_objects: tuple[str, ...]


def evaluate_motion_segment(
    evidence: MotionSegmentEvidence,
    *,
    max_final_joint_error_rad: float = 0.05,
    max_ee_position_error_m: float = 0.02,
    max_ee_orientation_error_rad: float = 0.15,
    minimum_duration_s: float = 0.25,
) -> tuple[str, tuple[str, ...]]:
    """Return an exact non-inflated execution status plus failure reasons."""

    reasons: list[str] = []
    if not evidence.planned:
        reasons.append("NOT_PLANNED")
    if not evidence.dispatched or not evidence.action_endpoint or not evidence.action_goal_uuid:
        reasons.append("TRAJECTORY_NOT_DISPATCHED")
    if not evidence.moveit_model_matches_gazebo:
        reasons.append("MOVEIT_GAZEBO_MODEL_MISMATCH")
    if not {"table", "bin_a"}.issubset(set(evidence.scene_collision_objects)):
        reasons.append("PLANNING_SCENE_INCOMPLETE")
    if evidence.controller_result != "SUCCEEDED":
        reasons.append("CONTROLLER_NOT_SUCCEEDED")
    if evidence.duration_s is None or evidence.duration_s < minimum_duration_s:
        reasons.append("EXECUTION_DURATION_TOO_SHORT")
    if evidence.max_final_joint_error_rad is None or evidence.max_final_joint_error_rad > max_final_joint_error_rad:
        reasons.append("FINAL_JOINT_ERROR_EXCEEDED")
    if evidence.ee_position_error_m is None or evidence.ee_position_error_m > max_ee_position_error_m:
        reasons.append("EE_POSITION_ERROR_EXCEEDED")
    if evidence.ee_orientation_error_rad is None or evidence.ee_orientation_error_rad > max_ee_orientation_error_rad:
        reasons.append("EE_ORIENTATION_ERROR_EXCEEDED")
    if evidence.continuity is None or not evidence.continuity.passed:
        reasons.append("ANTI_TELEPORT_FAILED")
    if evidence.gazebo_set_pose_or_joint_called:
        reasons.append("GAZEBO_DIRECT_POSE_OR_JOINT_WRITE")

    if not evidence.planned:
        status = "BLOCKED"
    elif not evidence.dispatched:
        status = "PLAN_ONLY"
    elif reasons:
        status = "PARTIAL_EXECUTION_VERIFIED"
    else:
        status = "VERIFIED_MOVEIT_EXECUTION"
    return status, tuple(sorted(set(reasons)))
