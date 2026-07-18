"""Fail-closed physical hand prerequisite for M1B contact experiments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class M1BHandPreflightV1:
    action_accepted: bool
    controller_succeeded: bool
    left_position_m: float | None
    right_position_m: float | None
    requested_position_m: float


def evaluate_hand_preflight(evidence: M1BHandPreflightV1) -> tuple[str, tuple[str, ...]]:
    """Require real endpoint feedback before any physical M1B grasp action."""
    reasons: list[str] = []
    if not evidence.action_accepted:
        reasons.append("HAND_ACTION_REJECTED")
    if not evidence.controller_succeeded:
        reasons.append("HAND_CONTROLLER_NOT_SUCCEEDED")
    if evidence.left_position_m is None or evidence.right_position_m is None:
        reasons.append("HAND_JOINT_FEEDBACK_UNAVAILABLE")
    else:
        if abs(evidence.left_position_m - evidence.requested_position_m) > 0.0011:
            reasons.append("LEFT_FINGER_ENDPOINT_ERROR")
        if abs(evidence.right_position_m - evidence.requested_position_m) > 0.0011:
            reasons.append("RIGHT_FINGER_ENDPOINT_ERROR")
        if abs(evidence.left_position_m - evidence.right_position_m) > 0.0011:
            reasons.append("FINGER_MIMIC_TRACKING_ERROR")
        if not all(0.0 <= value <= 0.04 for value in (evidence.left_position_m, evidence.right_position_m)):
            reasons.append("FINGER_STATE_OUTSIDE_PROTOCOL_LIMIT")
    return ("HAND_PREFLIGHT_VERIFIED", ()) if not reasons else ("HAND_ACTUATION_UNVERIFIED", tuple(reasons))
