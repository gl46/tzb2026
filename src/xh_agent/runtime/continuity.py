"""Anti-teleport checks over recorded /joint_states samples.

The module is intentionally ROS-independent so recorded evidence can be
validated locally without manufacturing feedback from a controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence


@dataclass(frozen=True)
class JointSample:
    """One joint-state sample in simulation time, in radians/metres as configured."""

    timestamp_s: float
    positions: Mapping[str, float]


@dataclass(frozen=True)
class ContinuityResult:
    passed: bool
    reasons: tuple[str, ...]
    sample_count: int
    max_adjacent_jump_rad: float
    max_velocity_ratio: float | None
    distinct_motion_samples: int


def check_joint_continuity(
    samples: Sequence[JointSample],
    *,
    velocity_limits_rad_s: Mapping[str, float] | None,
    expected_final_positions: Mapping[str, float] | None = None,
    minimum_samples: int = 20,
    maximum_adjacent_jump_rad: float = 0.08,
    maximum_velocity_limit_multiplier: float = 1.5,
    minimum_distinct_motion_samples: int = 5,
    moving_joint_threshold_rad: float = 0.10,
) -> ContinuityResult:
    """Validate monotonic feedback and reject direct final-value jumps.

    ``velocity_limits_rad_s`` may be absent only for velocity checking; the
    caller must record that limitation rather than claiming the check passed.
    """

    reasons: list[str] = []
    if len(samples) < minimum_samples:
        reasons.append("INSUFFICIENT_JOINT_STATE_SAMPLES")
    if not samples:
        return ContinuityResult(False, tuple(reasons or ["NO_JOINT_STATE_SAMPLES"]), 0, 0.0, None, 0)

    joints = tuple(samples[0].positions)
    if not joints:
        reasons.append("EMPTY_JOINT_STATE")
    for sample in samples:
        if tuple(sample.positions) != joints:
            reasons.append("JOINT_NAME_SET_CHANGED")
            break
        if not isfinite(sample.timestamp_s) or any(not isfinite(value) for value in sample.positions.values()):
            reasons.append("NONFINITE_JOINT_STATE")
            break

    max_jump = 0.0
    max_ratio: float | None = None
    for previous, current in zip(samples, samples[1:]):
        dt = current.timestamp_s - previous.timestamp_s
        if dt <= 0.0:
            reasons.append("NON_MONOTONIC_JOINT_STATE_TIME")
            continue
        for joint in joints:
            delta = abs(current.positions[joint] - previous.positions[joint])
            max_jump = max(max_jump, delta)
            if dt <= 0.1 and delta > maximum_adjacent_jump_rad:
                reasons.append("ADJACENT_JOINT_JUMP")
            if velocity_limits_rad_s is not None:
                limit = velocity_limits_rad_s.get(joint)
                if limit is None or limit <= 0.0:
                    reasons.append("MISSING_VELOCITY_LIMIT")
                    continue
                ratio = delta / dt / limit
                max_ratio = ratio if max_ratio is None else max(max_ratio, ratio)
                if ratio > maximum_velocity_limit_multiplier:
                    reasons.append("VELOCITY_LIMIT_EXCEEDED")

    distinct = 0
    if expected_final_positions:
        moving = [
            joint
            for joint, final in expected_final_positions.items()
            if joint in samples[0].positions
            and abs(final - samples[0].positions[joint]) > moving_joint_threshold_rad
        ]
        for joint in moving:
            values = {round(sample.positions[joint], 7) for sample in samples}
            if len(values) < minimum_distinct_motion_samples:
                reasons.append("INSUFFICIENT_INTERMEDIATE_MOTION")
            distinct = max(distinct, len(values))
    else:
        reasons.append("MISSING_EXPECTED_FINAL_POSITIONS")

    return ContinuityResult(
        passed=not reasons,
        reasons=tuple(sorted(set(reasons))),
        sample_count=len(samples),
        max_adjacent_jump_rad=max_jump,
        max_velocity_ratio=max_ratio,
        distinct_motion_samples=distinct,
    )
