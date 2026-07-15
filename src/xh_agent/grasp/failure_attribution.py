"""Closed failure taxonomy for bounded friction trials."""

from __future__ import annotations

from enum import Enum


class FailureClass(str, Enum):
    APPROACH_ALIGNMENT_FAILURE = "APPROACH_ALIGNMENT_FAILURE"
    CONTACT_CLOSURE_FAILURE = "CONTACT_CLOSURE_FAILURE"
    HOLD_TRANSPORT_FAILURE = "HOLD_TRANSPORT_FAILURE"
    RELEASE_PLACEMENT_FAILURE = "RELEASE_PLACEMENT_FAILURE"


def attribute_failure(
    *,
    fingertip_to_object_center_m: float,
    bilateral_contact: bool,
    lifted_m: float,
    held_s: float,
    released_explicitly: bool,
    object_stable_in_bin: bool,
) -> FailureClass | None:
    """Choose exactly one primary class for an unsuccessful completed trial."""

    if fingertip_to_object_center_m > 0.03:
        return FailureClass.APPROACH_ALIGNMENT_FAILURE
    if not bilateral_contact or lifted_m < 0.05:
        return FailureClass.CONTACT_CLOSURE_FAILURE
    if held_s < 1.0:
        return FailureClass.HOLD_TRANSPORT_FAILURE
    if not released_explicitly or not object_stable_in_bin:
        return FailureClass.RELEASE_PLACEMENT_FAILURE
    return None
