"""Actuation-internal bilateral-contact window for ADR-0013."""

from __future__ import annotations

from dataclasses import dataclass

from .m1b_broker import M1BContactBroker, M1BGraspFeedbackV1


_MAX_LEFT_RIGHT_SYNC_S = 0.050
_MAX_CONSECUTIVE_SAMPLE_GAP_S = 0.060


@dataclass(frozen=True)
class M1BContactSampleV1:
    timestamp_s: float
    finger: str
    collision_pairs: tuple[tuple[str, str], ...]


def broker_from_window(
    samples: list[M1BContactSampleV1],
) -> tuple[M1BGraspFeedbackV1, dict[str, str | bool | float | int | list[str] | None]]:
    """Select a same-entity attach topic from >=3 near-synchronous samples.

    The two Gazebo-to-ROS bridges do not guarantee bit-identical message
    stamps.  Pair only bounded-nearest samples, then require each candidate
    entity itself to persist through a continuous 100 ms bilateral window.

    The returned record also carries this window's measured span and the
    thresholds it was judged against, so the evidence states the broker's own
    numbers instead of leaving them to be re-derived from the raw samples.
    """
    by_finger = {
        finger: [sample for sample in samples if sample.finger == finger]
        for finger in ("left", "right")
    }
    single_sided = {
        finger: len(finger_samples)
        for finger, finger_samples in by_finger.items()
    }
    if not by_finger["left"] or not by_finger["right"]:
        # One finger never reported.  Report which one, so a single-sided
        # contact is distinguishable in the evidence from a short window.
        feedback, internal = M1BContactBroker().select(
            left_entities=set(), right_entities=set(), bilateral_overlap_s=0.0, consecutive_samples=0
        )
        return feedback, {
            **internal,
            "observed_best_bilateral_overlap_s": 0.0,
            "observed_best_consecutive_samples": 0,
            "paired_bilateral_sample_count": 0,
            "candidate_entities": [],
            "left_right_pairing_window_s": _MAX_LEFT_RIGHT_SYNC_S,
            "max_consecutive_sample_gap_s": _MAX_CONSECUTIVE_SAMPLE_GAP_S,
            "per_finger_sample_count": single_sided,
        }
    paired: list[tuple[float, set[str]]] = []
    right_samples = sorted(by_finger["right"], key=lambda sample: sample.timestamp_s)
    for left_sample in sorted(by_finger["left"], key=lambda sample: sample.timestamp_s):
        right_sample = min(
            right_samples,
            key=lambda sample: abs(sample.timestamp_s - left_sample.timestamp_s),
        )
        if abs(right_sample.timestamp_s - left_sample.timestamp_s) > _MAX_LEFT_RIGHT_SYNC_S:
            continue
        common_entities = (
            M1BContactBroker.cylinder_entities(list(left_sample.collision_pairs))
            & M1BContactBroker.cylinder_entities(list(right_sample.collision_pairs))
        )
        if common_entities:
            paired.append(((left_sample.timestamp_s + right_sample.timestamp_s) / 2.0, common_entities))

    entity_times: dict[str, list[float]] = {}
    for timestamp_s, entities in paired:
        for entity in entities:
            entity_times.setdefault(entity, []).append(timestamp_s)

    valid_entities: set[str] = set()
    best_overlap_s = 0.0
    best_consecutive_samples = 0
    # Longest run seen at all, whether or not it cleared the threshold.  A
    # rejected trial otherwise reports a bare 0.0 and cannot be told apart
    # from "the fingers never touched the same object": the measured
    # small-offset failures sat at 0.075 s and 0.097 s, the latter missing by
    # 3 ms, which is what identified the observation window rather than the
    # physics as the cause.  Diagnostic only -- it never feeds the decision.
    observed_overlap_s = 0.0
    observed_consecutive_samples = 0
    for entity, timestamps in entity_times.items():
        run: list[float] = []
        for timestamp_s in sorted(set(timestamps)):
            if run and timestamp_s - run[-1] > _MAX_CONSECUTIVE_SAMPLE_GAP_S:
                run = []
            run.append(timestamp_s)
            overlap_s = run[-1] - run[0]
            observed_overlap_s = max(observed_overlap_s, overlap_s)
            observed_consecutive_samples = max(observed_consecutive_samples, len(run))
            if len(run) >= 3 and overlap_s >= 0.100:
                valid_entities.add(entity)
                best_overlap_s = max(best_overlap_s, overlap_s)
                best_consecutive_samples = max(best_consecutive_samples, len(run))

    feedback, internal = M1BContactBroker().select(
        left_entities=valid_entities,
        right_entities=valid_entities,
        bilateral_overlap_s=best_overlap_s,
        consecutive_samples=best_consecutive_samples,
    )
    return feedback, {
        **internal,
        "observed_best_bilateral_overlap_s": observed_overlap_s,
        "observed_best_consecutive_samples": observed_consecutive_samples,
        "paired_bilateral_sample_count": len(paired),
        "candidate_entities": sorted(entity_times),
        "left_right_pairing_window_s": _MAX_LEFT_RIGHT_SYNC_S,
        "max_consecutive_sample_gap_s": _MAX_CONSECUTIVE_SAMPLE_GAP_S,
        "per_finger_sample_count": single_sided,
    }
