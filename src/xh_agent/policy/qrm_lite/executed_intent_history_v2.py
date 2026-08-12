"""Public-only executed-intent history shared by M2C training and runtime."""

from __future__ import annotations

from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xh_agent.policy.qrm_lite.contracts import DestinationCellV2
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    M2C_Q012_V2_SKILL_LABELS,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
TRACK_ID_PATTERN = r"^track-[A-Za-z0-9._:-]+$"
ExecutionAttributionV2 = Literal[
    "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
    "MODEL_SELECTED_REGISTERED_SKILL",
]
PATH_BLOCKED_EXECUTED_SKILLS = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PublicExecutedIntentHistoryItemV2(StrictModel):
    """One already executed public skill; never a future/expected decision."""

    decision_index: int = Field(ge=0, le=6)
    selected_skill: str = Field(min_length=1)
    target_track_id: str | None = Field(default=None, pattern=TRACK_ID_PATTERN)
    destination_cell: DestinationCellV2 | None = None
    physical_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    execution_attribution: ExecutionAttributionV2

    @field_validator("selected_skill")
    @classmethod
    def selected_skill_is_registered(cls, value: str) -> str:
        if value not in M2C_Q012_V2_SKILL_LABELS:
            raise ValueError("executed-intent history has an unknown skill")
        if value not in PATH_BLOCKED_EXECUTED_SKILLS:
            raise ValueError("executed-intent history skill is outside the ADR chain")
        return value

    def model_post_init(self, __context: object) -> None:
        target_required = self.selected_skill != "REOBSERVE"
        if target_required != (self.target_track_id is not None):
            raise ValueError("executed-intent history target presence differs from skill semantics")
        destination_required = self.selected_skill in {"MOVE", "PLACE"}
        if destination_required != (self.destination_cell is not None):
            raise ValueError(
                "executed-intent history destination presence differs from skill semantics"
            )


def validate_executed_intent_history_v2(
    history: Sequence[PublicExecutedIntentHistoryItemV2],
    *,
    expected_length: int,
) -> tuple[PublicExecutedIntentHistoryItemV2, ...]:
    if not 0 <= expected_length <= 7:
        raise ValueError("executed-intent expected length is outside 0..7")
    items = tuple(history)
    if len(items) != expected_length:
        raise ValueError("executed-intent history length is not the exact prior prefix")
    if [item.decision_index for item in items] != list(range(expected_length)):
        raise ValueError("executed-intent history has a gap, reorder, or future item")
    for item in items:
        if item.selected_skill not in M2C_Q012_V2_SKILL_LABELS:
            raise ValueError("executed-intent history has an unknown skill")
    receipts = [item.physical_receipt_sha256 for item in items]
    if len(receipts) != len(set(receipts)):
        raise ValueError("executed-intent history reuses a physical receipt")
    return items


def prompt_executed_intent_history_v2(
    history: Sequence[PublicExecutedIntentHistoryItemV2],
    *,
    expected_length: int,
) -> list[dict[str, int | str | None]]:
    """Normalize source attribution while preserving the public executed facts."""

    items = validate_executed_intent_history_v2(
        history,
        expected_length=expected_length,
    )
    return [
        {
            "decision_index": item.decision_index,
            "selected_skill": item.selected_skill,
            "target_track_id": item.target_track_id,
            "destination_cell": item.destination_cell,
            "physical_receipt_sha256": item.physical_receipt_sha256,
            "execution_attribution": "EXECUTED_PHYSICAL_SKILL",
        }
        for item in items
    ]


def reject_forbidden_history_payload_fields(
    payload: Mapping[str, object],
) -> None:
    """Explicit fail-closed helper for untrusted runtime/dataset dictionaries."""

    forbidden_fragments = (
        "teacher",
        "privileged",
        "truth",
        "oracle",
        "prim",
        "role",
        "expected_next",
        "next_skill",
        "task_target",
    )
    forbidden = sorted(
        str(key)
        for key in payload
        if any(fragment in str(key).lower() for fragment in forbidden_fragments)
    )
    if forbidden:
        raise ValueError(f"executed-intent history contains forbidden fields: {forbidden}")
