"""Protocol helpers for a contact-seeking terminal descent."""

from __future__ import annotations

import math


def descending_contact_seek_offsets_m(
    *, start_m: float, minimum_m: float, step_m: float,
) -> tuple[float, ...]:
    """Return an inclusive, bounded high-to-low contact-search schedule.

    The schedule is independent of any object pose.  A caller must use only
    its physical contact broker to decide whether to stop at a waypoint.
    """

    values = (start_m, minimum_m, step_m)
    if not all(math.isfinite(value) for value in values) or minimum_m < 0.0 or step_m <= 0.0:
        raise ValueError("contact-seek offsets must be finite, non-negative, and use a positive step")
    if start_m < minimum_m:
        raise ValueError("contact-seek start must not be below its minimum")
    count = math.ceil((start_m - minimum_m) / step_m)
    offsets = tuple(round(max(minimum_m, start_m - index * step_m), 6) for index in range(count + 1))
    return offsets if offsets[-1] == round(minimum_m, 6) else (*offsets, round(minimum_m, 6))
