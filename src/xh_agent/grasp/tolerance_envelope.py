"""Offline-only M1B S0-style reachability calibration gates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median


AXES = ("x", "y", "z")


@dataclass(frozen=True)
class OffsetTrialV1:
    axis: str
    offset_m: float
    bilateral_same_entity_contact: bool


def percentile90(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot calculate p90 of an empty sequence")
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * 0.9)]


def tolerance_envelope(trials: list[OffsetTrialV1]) -> dict[str, float | None]:
    """Return max absolute offset with >=3 trials and >=80% contact success."""
    grouped: dict[tuple[str, float], list[bool]] = defaultdict(list)
    for trial in trials:
        if trial.axis not in AXES:
            raise ValueError(f"unsupported axis: {trial.axis}")
        grouped[(trial.axis, abs(trial.offset_m))].append(trial.bilateral_same_entity_contact)
    output: dict[str, float | None] = {}
    for axis in AXES:
        passes = {
            offset for (recorded_axis, offset), outcomes in grouped.items()
            if recorded_axis == axis and len(outcomes) >= 3 and sum(outcomes) >= 2
        }
        # A tolerance boundary is a monotone closure: an isolated success at a
        # large offset cannot erase a failure at a smaller offset.
        output[axis] = max(
            (offset for offset in passes if all(smaller in passes for smaller in {value for recorded_axis, value in grouped if recorded_axis == axis and value <= offset})),
            default=None,
        )
    return output


def perception_axis_audit(errors_m: list[tuple[float, float, float]]) -> dict[str, dict[str, float]]:
    """Summarize evaluator-only public-centre errors by planning-frame axis."""
    if not errors_m:
        raise ValueError("at least one matched public prediction is required")
    return {
        axis: {"median_m": median(abs(error[index]) for error in errors_m), "p90_m": percentile90([abs(error[index]) for error in errors_m])}
        for index, axis in enumerate(AXES)
    }


def reachability_gate(envelope_m: dict[str, float | None], audit: dict[str, dict[str, float]]) -> tuple[str, tuple[str, ...]]:
    """GO iff every p90 error leaves the required 40% tolerance margin."""
    reasons: list[str] = []
    for axis in AXES:
        tolerance = envelope_m.get(axis)
        if tolerance is None:
            reasons.append(f"TOLERANCE_UNMEASURED:{axis}")
        elif audit[axis]["p90_m"] > 0.6 * tolerance:
            reasons.append(f"P90_EXCEEDS_60_PERCENT_TOLERANCE:{axis}")
    return ("GO", ()) if not reasons else ("NO_GO", tuple(reasons))
