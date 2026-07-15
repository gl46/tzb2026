"""Fail-closed attach gate for the explicitly constrained M1A fallback."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContactGateInput:
    target_id: str
    expected_target_id: str
    bilateral_contact_valid: bool
    gripper_width_m: float
    object_width_estimate_m: float | None
    target_in_grasp_corridor: bool
    relative_linear_speed_mean_mps: float
    relative_linear_speed_peak_mps: float
    seconds_since_close_command: float
    already_attached: bool
    prohibited_collision: bool
    controller_aborted: bool
    valid_sim_timestamps: bool


def evaluate_contact_gate(value: ContactGateInput) -> tuple[bool, tuple[str, ...]]:
    """Evaluate every S3 necessity; omissions fail closed and remain auditable."""

    reasons: list[str] = []
    if value.target_id != value.expected_target_id:
        reasons.append("TARGET_ID_MISMATCH")
    if not value.bilateral_contact_valid:
        reasons.append("BILATERAL_CONTACT_INVALID")
    if not 0.045 <= value.gripper_width_m <= 0.070:
        reasons.append("GRIPPER_WIDTH_OUT_OF_RANGE")
    if value.object_width_estimate_m is not None and abs(value.gripper_width_m - value.object_width_estimate_m) > 0.020:
        reasons.append("OBJECT_WIDTH_INCOMPATIBLE")
    if not value.target_in_grasp_corridor:
        reasons.append("TARGET_OUTSIDE_GRASP_CORRIDOR")
    if value.relative_linear_speed_mean_mps > 0.020 or value.relative_linear_speed_peak_mps > 0.040:
        reasons.append("RELATIVE_SPEED_TOO_HIGH")
    if value.seconds_since_close_command > 1.0:
        reasons.append("NO_RECENT_CLOSE_COMMAND")
    if value.already_attached:
        reasons.append("TARGET_ALREADY_ATTACHED")
    if value.prohibited_collision:
        reasons.append("PROHIBITED_COLLISION")
    if value.controller_aborted:
        reasons.append("CONTROLLER_ABORTED")
    if not value.valid_sim_timestamps:
        reasons.append("INVALID_SIM_TIMESTAMPS")
    return not reasons, tuple(reasons)
