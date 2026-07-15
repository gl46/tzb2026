"""Semantic contact telemetry validation for the two Panda fingers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ContactEvent:
    timestamp_s: float
    finger: str
    target_id: str
    contact_pair: tuple[str, str]


def bilateral_contact_window(
    events: Iterable[ContactEvent],
    *,
    target_id: str,
    overlap_s: float = 0.100,
    minimum_consecutive_samples: int = 3,
) -> tuple[bool, tuple[str, ...], float, int]:
    """Return bilateral validity only for ordered, same-target finger contacts.

    Events are point samples; the valid overlap duration is measured from the
    first to last paired sample.  A table/bin pair never matches ``target_id``.
    """

    ordered = list(events)
    if any(later.timestamp_s < earlier.timestamp_s for earlier, later in zip(ordered, ordered[1:])):
        return False, ("CONTACT_TIME_REWIND",), 0.0, 0
    valid = [event for event in ordered if event.target_id == target_id]
    left = [event for event in valid if event.finger == "left"]
    right = [event for event in valid if event.finger == "right"]
    if not left:
        return False, ("LEFT_FINGER_TARGET_CONTACT_MISSING",), 0.0, 0
    if not right:
        return False, ("RIGHT_FINGER_TARGET_CONTACT_MISSING",), 0.0, 0

    paired_times: list[float] = []
    right_times = {event.timestamp_s for event in right}
    for event in left:
        if event.timestamp_s in right_times:
            paired_times.append(event.timestamp_s)
    if len(paired_times) < minimum_consecutive_samples:
        return False, ("INSUFFICIENT_BILATERAL_SAMPLES",), 0.0, len(paired_times)
    duration = paired_times[-1] - paired_times[0]
    if duration < overlap_s:
        return False, ("BILATERAL_OVERLAP_TOO_SHORT",), duration, len(paired_times)
    return True, (), duration, len(paired_times)
