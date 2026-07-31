"""Pure contracts for the optional M2A Isaac counterfactual probe."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


SHADOW_CANDIDATES = (
    "geometric_default",
    "alternate_joint_probe",
    "reobserve_hold",
)


def validate_initial_joint_position(values: Sequence[float]) -> tuple[float, ...]:
    """Validate a public nine-DOF Panda observation without remapping it."""

    parsed = tuple(float(value) for value in values)
    if len(parsed) != 9:
        raise ValueError(f"expected nine named Panda joints, got {len(parsed)}")
    if not all(math.isfinite(value) for value in parsed):
        raise ValueError("initial Panda joint position contains a non-finite value")
    # These are rejection bounds, not a controller mapping. The accepted public
    # Isaac observations are much tighter than these limits.
    if any(abs(value) > 4.0 for value in parsed[:7]):
        raise ValueError("public arm joint observation exceeds rejection bounds")
    if any(value < -0.001 or value > 0.05 for value in parsed[7:]):
        raise ValueError("public finger joint observation exceeds rejection bounds")
    return parsed


def shadow_target_positions(
    initial: Sequence[float],
    indices: Mapping[str, int],
    frame_index: int,
    worker_id: int,
    candidate: str,
) -> list[float]:
    """Return an explicit joint-space physics probe, never a model mapping."""

    if candidate not in SHADOW_CANDIDATES:
        raise ValueError(f"unknown shadow candidate: {candidate}")
    target = list(validate_initial_joint_position(initial))
    if candidate == "reobserve_hold":
        return target
    phase = 2.0 * math.pi * frame_index / 100.0 + worker_id * 0.37
    if candidate == "geometric_default":
        target[indices["panda_joint1"]] += 0.20 * math.sin(phase)
        target[indices["panda_joint2"]] += 0.10 * math.sin(phase * 0.7)
        target[indices["panda_joint4"]] += 0.12 * math.cos(phase * 0.5)
        target[indices["panda_joint6"]] += 0.15 * math.sin(phase * 0.9)
    else:
        target[indices["panda_joint1"]] -= 0.12 * math.sin(phase + 0.4)
        target[indices["panda_joint3"]] += 0.08 * math.sin(phase * 0.8)
        target[indices["panda_joint4"]] += 0.08 * math.cos(phase * 0.6)
        target[indices["panda_joint6"]] -= 0.10 * math.sin(phase * 0.9)
    return target
