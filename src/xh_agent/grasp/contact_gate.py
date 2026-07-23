"""Fail-closed attach gate for the explicitly constrained M1A fallback."""

from __future__ import annotations

from dataclasses import dataclass
import math


# A close against an object is intentionally different from a free-space
# finger command.  The controller may terminate successfully while the
# fingers remain open of the requested position, provided the remaining
# error is bounded by the measured contact surface plus the engine margin.
# Contact itself is still proved independently by the bilateral gate below.
CONTACT_STALL_ENGINE_MARGIN_M = 0.003
CONTACT_STALL_CONTRACT_MARGIN_M = 0.001
MAX_FINGER_POSITION_M = 0.040


def symmetric_contact_stall_goal_tolerance_m(
    *, command_per_finger_m: float, contact_surface_per_finger_m: float,
) -> float:
    """Return the explicit action tolerance for a symmetric physical close.

    A position-controlled close stops at a real object's surface rather than
    at its free-space target.  This function bounds that expected positive
    error to the measured contact surface, a 3 mm simulator-contact margin,
    and the existing 1 mm controller contract.  It is deliberately only an
    action tolerance: callers must still require bilateral same-entity
    contact, corridor, speed, and successful controller action evidence before
    attach.  The target-reference telemetry remains diagnostic because its
    sampling is not guaranteed for every short action.
    """

    values = (command_per_finger_m, contact_surface_per_finger_m)
    if not all(math.isfinite(value) and 0.0 <= value <= MAX_FINGER_POSITION_M for value in values):
        raise ValueError("finger positions must be finite and within [0.0, 0.04] m")
    return CONTACT_STALL_CONTRACT_MARGIN_M + max(
        0.0,
        contact_surface_per_finger_m + CONTACT_STALL_ENGINE_MARGIN_M - command_per_finger_m,
    )


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
