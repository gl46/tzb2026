"""Positive release verification; cleanup detach is intentionally insufficient."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseEvidence:
    explicit_open_command: bool
    hand_controller_succeeded: bool
    gripper_width_m: float
    detach_after_open_s: float | None
    follows_end_effector_after_detach: bool
    object_in_bin: bool
    bin_settle_s: float
    bin_displacement_m: float
    cleanup_triggered_detach: bool
    direct_object_pose_write: bool


def evaluate_release(value: ReleaseEvidence) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if not value.explicit_open_command:
        reasons.append("MISSING_EXPLICIT_OPEN")
    if not value.hand_controller_succeeded:
        reasons.append("HAND_CONTROLLER_NOT_SUCCEEDED")
    if value.gripper_width_m < 0.070:
        reasons.append("GRIPPER_NOT_OPEN")
    if value.detach_after_open_s is None or value.detach_after_open_s > 0.500:
        reasons.append("DETACH_DEADLINE_MISSED")
    if value.follows_end_effector_after_detach:
        reasons.append("OBJECT_STILL_RIGIDLY_FOLLOWS_EE")
    if not value.object_in_bin:
        reasons.append("OBJECT_NOT_IN_BIN")
    if value.bin_settle_s < 1.0 or value.bin_displacement_m >= 0.01:
        reasons.append("BIN_NOT_STABLE")
    if value.cleanup_triggered_detach:
        reasons.append("CLEANUP_DETACH")
    if value.direct_object_pose_write:
        reasons.append("DIRECT_OBJECT_POSE_WRITE")
    return not reasons, tuple(reasons)
