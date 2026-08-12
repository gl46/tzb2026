from __future__ import annotations

import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
    prompt_executed_intent_history_v2,
    reject_forbidden_history_payload_fields,
    validate_executed_intent_history_v2,
)


def _item(index: int) -> PublicExecutedIntentHistoryItemV2:
    return PublicExecutedIntentHistoryItemV2(
        decision_index=index,
        selected_skill="GRASP" if index == 0 else "LIFT",
        target_track_id=f"track-public-{index}",
        physical_receipt_sha256=f"{index + 1:064x}",
        execution_attribution="SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
    )


def _semantic_item(
    skill: str,
    *,
    target: str | None,
    destination: str | None,
) -> PublicExecutedIntentHistoryItemV2:
    return PublicExecutedIntentHistoryItemV2(
        decision_index=0,
        selected_skill=skill,
        target_track_id=target,
        destination_cell=destination,
        physical_receipt_sha256="1" * 64,
        execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
    )


def test_prompt_history_normalizes_attribution_but_preserves_public_facts() -> None:
    item = _item(0)
    payload = prompt_executed_intent_history_v2([item], expected_length=1)
    assert payload == [
        {
            "decision_index": 0,
            "selected_skill": "GRASP",
            "target_track_id": "track-public-0",
            "destination_cell": None,
            "physical_receipt_sha256": "1".zfill(64),
            "execution_attribution": "EXECUTED_PHYSICAL_SKILL",
        }
    ]


@pytest.mark.parametrize(
    "history",
    (
        [_item(1)],
        [_item(0), _item(0)],
        [_item(0), _item(2)],
    ),
)
def test_history_gap_reorder_future_or_duplicate_fails_closed(history) -> None:
    with pytest.raises(ValueError, match="gap|reorder|future|length"):
        validate_executed_intent_history_v2(
            history,
            expected_length=len(history),
        )


@pytest.mark.parametrize(
    "field",
    (
        "teacher_used",
        "privileged_truth_policy_input",
        "simulator_truth",
        "prim_path",
        "task_role",
        "expected_next_skill",
    ),
)
def test_untrusted_history_forbidden_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="forbidden fields"):
        reject_forbidden_history_payload_fields({field: False})


def test_schema_rejects_teacher_or_unknown_fields() -> None:
    payload = _item(0).model_dump(mode="json")
    payload["teacher_used"] = True
    with pytest.raises(ValidationError):
        PublicExecutedIntentHistoryItemV2.model_validate(payload)


def test_schema_rejects_unknown_skill() -> None:
    payload = _item(0).model_dump(mode="json")
    payload["selected_skill"] = "EXPECTED_NEXT_SKILL"
    with pytest.raises(ValidationError, match="unknown skill"):
        PublicExecutedIntentHistoryItemV2.model_validate(payload)


@pytest.mark.parametrize(
    ("skill", "target", "destination"),
    (
        ("REOBSERVE", "track-public-target", None),
        ("GRASP", None, None),
        ("MOVE", "track-public-target", None),
        ("PLACE", "track-public-target", None),
        ("LIFT", "track-public-target", "BIN_CELL_0"),
    ),
)
def test_skill_parameter_semantics_fail_closed(
    skill: str,
    target: str | None,
    destination: str | None,
) -> None:
    with pytest.raises(ValidationError, match="presence differs"):
        _semantic_item(skill, target=target, destination=destination)


def test_valid_reobserve_and_move_history_semantics() -> None:
    reobserve = _semantic_item("REOBSERVE", target=None, destination=None)
    move = _semantic_item(
        "MOVE",
        target="track-public-target",
        destination="BIN_CELL_0",
    )
    assert reobserve.target_track_id is None
    assert move.destination_cell == "BIN_CELL_0"
    payload = _item(0).model_dump(mode="json")
    payload["simulator_truth_role"] = "blocker"
    with pytest.raises(ValidationError):
        PublicExecutedIntentHistoryItemV2.model_validate(payload)
