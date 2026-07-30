"""Fail-closed M1B detachable-joint reset contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class M1BResetVerificationV1:
    object_name: str
    detach_topic: str
    grasp_state_topic: str
    detached_observed: bool
    state_lines: tuple[str, ...]


def validate_reset_records(records: list[M1BResetVerificationV1], expected_objects: list[str]) -> tuple[str, tuple[str, ...]]:
    """Return INVALID_RESET unless every generated detachable reports detached."""
    expected = tuple(sorted(expected_objects))
    names = tuple(sorted(record.object_name for record in records))
    if names != expected or len(set(names)) != len(names):
        return "INVALID_RESET", ("RESET_OBJECT_SET_MISMATCH",)
    missing = tuple(record.object_name for record in records if not record.detached_observed)
    if missing:
        return "INVALID_RESET", tuple(f"DETACH_STATE_UNOBSERVED:{name}" for name in missing)
    return "RESET_VERIFIED", ()
