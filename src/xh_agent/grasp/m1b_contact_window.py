"""Actuation-internal bilateral-contact window for ADR-0013."""

from __future__ import annotations

from dataclasses import dataclass

from .m1b_broker import M1BContactBroker, M1BGraspFeedbackV1


@dataclass(frozen=True)
class M1BContactSampleV1:
    timestamp_s: float
    finger: str
    collision_pairs: tuple[tuple[str, str], ...]


def broker_from_window(samples: list[M1BContactSampleV1]) -> tuple[M1BGraspFeedbackV1, dict[str, str | bool | None]]:
    """Select a same-entity attach topic from >=3 matched 100 ms samples."""
    by_finger = {
        finger: [sample for sample in samples if sample.finger == finger]
        for finger in ("left", "right")
    }
    if not by_finger["left"] or not by_finger["right"]:
        return M1BContactBroker().select(left_entities=set(), right_entities=set(), bilateral_overlap_s=0.0, consecutive_samples=0)
    left = M1BContactBroker.cylinder_entities([pair for sample in by_finger["left"] for pair in sample.collision_pairs])
    right = M1BContactBroker.cylinder_entities([pair for sample in by_finger["right"] for pair in sample.collision_pairs])
    overlap_start = max(by_finger["left"][0].timestamp_s, by_finger["right"][0].timestamp_s)
    overlap_end = min(by_finger["left"][-1].timestamp_s, by_finger["right"][-1].timestamp_s)
    common_times = sorted({round(sample.timestamp_s, 6) for sample in by_finger["left"]} & {round(sample.timestamp_s, 6) for sample in by_finger["right"]})
    return M1BContactBroker().select(
        left_entities=left,
        right_entities=right,
        bilateral_overlap_s=max(0.0, overlap_end - overlap_start),
        consecutive_samples=len(common_times),
    )
