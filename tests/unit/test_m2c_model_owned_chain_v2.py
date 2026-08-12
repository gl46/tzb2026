from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    EXPECTED_PATH_BLOCKED_CHAIN,
    ModelOwnedChainEpisodeV2,
    validate_model_owned_chain_episode,
)


DIGEST = "a" * 64
BLOCKER = "track-public-blocker"
TARGET = "track-public-task-target"


def _episode_payload() -> dict[str, object]:
    decisions: list[dict[str, object]] = []
    previous_completed = 100
    for step_index, skill in enumerate(EXPECTED_PATH_BLOCKED_CHAIN):
        observation_time = previous_completed + 10
        start_time = observation_time + 10
        completed_time = start_time + 10
        tracks = [BLOCKER, TARGET, "track-public-other"]
        pointer_slots = sorted(tracks)
        if step_index in {0, 1, 2, 3, 4}:
            target = BLOCKER
            target_provenance = "MODEL"
            pointer_class = pointer_slots.index(BLOCKER)
        elif step_index in {6, 7}:
            target = TARGET
            target_provenance = "MODEL"
            pointer_class = pointer_slots.index(TARGET)
        else:
            target = None
            target_provenance = "NONE"
            pointer_class = 8
        destination_required = step_index in {2, 3}
        decisions.append(
            {
                "decision_id": f"decision-{step_index}",
                "step_index": step_index,
                "observation": {
                    "observation_id": f"observation-{step_index}",
                    "captured_at_ns": observation_time,
                    "rgb_sha256": DIGEST,
                    "depth_sha256": "b" * 64,
                    "fresh": True,
                    "perception_track_ids": tracks,
                    "pointer_slots": pointer_slots,
                    "blocker_track_id": BLOCKER,
                    "task_target_track_id": TARGET,
                },
                "model_output_sha256": "c" * 64,
                "selected_skill": skill,
                "skill_provenance": "MODEL",
                "target_track_id": target,
                "target_pointer_class": pointer_class,
                "target_provenance": target_provenance,
                "destination_cell": "BIN_CELL_3" if destination_required else None,
                "destination_class": 3 if destination_required else 6,
                "destination_provenance": ("MODEL" if destination_required else "NONE"),
                "mapping_status": "VALID",
                "physical_skill_receipts": [
                    {
                        "receipt_id": f"receipt-{step_index}",
                        "receipt_sha256": f"{step_index + 1:064x}",
                        "executed_skill": skill,
                        "execution_source": "MODEL_SELECTED_REGISTERED_SKILL",
                        "physically_executed": True,
                        "started_at_ns": start_time,
                        "completed_at_ns": completed_time,
                        "schema_gate": "PASS",
                        "stale_track_gate": "PASS",
                        "frame_unit_gate": "PASS",
                        "ik_gate": "PASS",
                        "collision_gate": "PASS",
                        "controller_gate": "PASS",
                        "safety_gate": "PASS",
                    }
                ],
            }
        )
        previous_completed = completed_time
    return {
        "episode_id": "m2c-qb-green-chain",
        "failure_observed_at_ns": 100,
        "final_task_success": True,
        "decisions": decisions,
    }


def _validate(payload: dict[str, object]):
    return validate_model_owned_chain_episode(ModelOwnedChainEpisodeV2.model_validate(payload))


def _record_fallback(
    payload: dict[str, object],
    step: int,
    *,
    reason: str,
    source: str = "B0_FALLBACK",
) -> None:
    decision = payload["decisions"][step]  # type: ignore[index]
    receipt = decision["physical_skill_receipts"][0]  # type: ignore[index]
    receipt["execution_source"] = source
    receipt["fallback_reason"] = reason


def test_green_eight_step_chain_is_strict_pure_model_success() -> None:
    assert EXPECTED_PATH_BLOCKED_CHAIN == (
        "GRASP",
        "LIFT",
        "MOVE",
        "PLACE",
        "RELEASE",
        "REOBSERVE",
        "REASSOCIATE_TARGET",
        "REGRASP",
    )
    result = _validate(_episode_payload())

    assert result.strict_pure_model_success is True
    assert result.expected_chain == list(EXPECTED_PATH_BLOCKED_CHAIN)
    assert result.decisions_observed == 8
    assert result.physical_receipts_observed == 8
    assert result.fallback_events == []
    assert result.exclusion_reasons == []
    assert all(step.passed for step in result.steps)


def test_invalid_pointer_records_fallback_and_exclusion_reason() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][0]  # type: ignore[index]
    decision["target_pointer_class"] = 99
    decision["mapping_status"] = "INVALID_POINTER"
    _record_fallback(payload, 0, reason="INVALID_POINTER")

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-0:INVALID_POINTER" in result.exclusion_reasons
    assert "decision-0:B0_FALLBACK" in result.exclusion_reasons
    assert result.fallback_events[0].fallback_reason == "INVALID_POINTER"


def test_stale_track_records_fallback_and_exclusion_reason() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][2]  # type: ignore[index]
    observation = decision["observation"]  # type: ignore[index]
    observation["perception_track_ids"] = [TARGET, "track-public-other"]
    observation["pointer_slots"] = sorted(observation["perception_track_ids"])
    decision["mapping_status"] = "STALE_TRACK"
    _record_fallback(payload, 2, reason="STALE_TRACK")

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-2:STALE_TRACK" in result.exclusion_reasons
    assert any(event.decision_id == "decision-2" for event in result.fallback_events)


def test_invalid_destination_cell_records_fallback() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][2]  # type: ignore[index]
    decision["destination_cell"] = "FREE_FORM_XYZ"
    decision["mapping_status"] = "INVALID_CELL"
    _record_fallback(payload, 2, reason="INVALID_CELL")

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-2:INVALID_CELL" in result.exclusion_reasons
    assert result.fallback_events[0].fallback_reason == "INVALID_CELL"


def test_task_spec_target_fallback_is_never_pure() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][6]  # type: ignore[index]
    decision["target_provenance"] = "TASK_SPEC_FALLBACK"
    _record_fallback(payload, 6, reason="TASK_SPEC_FALLBACK")

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-6:TASK_SPEC_FALLBACK" in result.exclusion_reasons
    assert "decision-6:B0_FALLBACK" in result.exclusion_reasons


def test_b0_continuation_is_recorded_and_never_pure() -> None:
    payload = _episode_payload()
    _record_fallback(
        payload,
        6,
        reason="FIXED_RECOVERY_CONTINUATION",
        source="B0_CONTINUATION",
    )

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-6:B0_CONTINUATION" in result.exclusion_reasons
    assert result.fallback_events[0].execution_source == "B0_CONTINUATION"


def test_bad_mapping_without_fallback_receipt_is_explicitly_excluded() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][0]  # type: ignore[index]
    decision["mapping_status"] = "INVALID_POINTER"

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-0:FALLBACK_NOT_RECORDED" in result.exclusion_reasons


def test_each_step_needs_one_receipt_all_gates_and_fresh_observation() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][3]  # type: ignore[index]
    decision["physical_skill_receipts"] = []
    next_decision = payload["decisions"][4]  # type: ignore[index]
    next_decision["observation"]["observation_id"] = "observation-3"
    next_decision["physical_skill_receipts"][0]["ik_gate"] = "REJECTED"

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-3:PHYSICAL_RECEIPT_COUNT_NOT_ONE" in result.exclusion_reasons
    assert "decision-4:OBSERVATION_RECEIPT_REUSED" in result.exclusion_reasons
    assert "decision-4:IK_GATE_NOT_PASSING" in result.exclusion_reasons


def test_chain_order_and_parameter_none_provenance_are_strict() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][5]  # type: ignore[index]
    decision["selected_skill"] = "RELEASE"
    decision["target_provenance"] = "MODEL"
    decision["destination_cell"] = "BIN_CELL_0"

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert any("CHAIN_SKILL_MISMATCH" in item for item in result.exclusion_reasons)
    assert "decision-5:TARGET_PROVENANCE_NOT_NONE" in result.exclusion_reasons
    assert "decision-5:UNEXPECTED_DESTINATION_CELL" in result.exclusion_reasons


def test_privileged_identity_has_no_schema_field() -> None:
    payload = _episode_payload()
    observation = payload["decisions"][0]["observation"]  # type: ignore[index]
    observation["prim_path"] = "/World/secret-blocker"

    with pytest.raises(ValidationError, match="prim_path"):
        ModelOwnedChainEpisodeV2.model_validate(payload)


@pytest.mark.parametrize(
    "oracle_track_id",
    ["gazebo_perfect_cylinder_01", "cylinder_01", "/World/cylinder_01"],
)
def test_oracle_shaped_track_id_is_rejected(oracle_track_id: str) -> None:
    payload = _episode_payload()
    observation = payload["decisions"][0]["observation"]  # type: ignore[index]
    observation["perception_track_ids"][0] = oracle_track_id

    with pytest.raises(ValidationError, match=r"public track-\* identifiers"):
        ModelOwnedChainEpisodeV2.model_validate(payload)


def test_privileged_truth_flag_disqualifies_without_losing_journal() -> None:
    payload = deepcopy(_episode_payload())
    observation = payload["decisions"][0]["observation"]  # type: ignore[index]
    observation["privileged_truth_policy_input"] = True

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-0:PRIVILEGED_TRUTH_POLICY_INPUT" in result.exclusion_reasons


def test_physical_receipt_may_not_be_reused_across_steps() -> None:
    payload = _episode_payload()
    second_receipt = payload["decisions"][1]["physical_skill_receipts"][0]  # type: ignore[index]
    second_receipt["receipt_id"] = "receipt-0"

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-1:PHYSICAL_RECEIPT_REUSED" in result.exclusion_reasons


def test_physical_receipt_hash_may_not_be_reused_with_a_new_id() -> None:
    payload = _episode_payload()
    first_receipt = payload["decisions"][0]["physical_skill_receipts"][0]  # type: ignore[index]
    second_receipt = payload["decisions"][1]["physical_skill_receipts"][0]  # type: ignore[index]
    second_receipt["receipt_sha256"] = first_receipt["receipt_sha256"]

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-1:PHYSICAL_RECEIPT_REUSED" in result.exclusion_reasons


def test_task_spec_destination_fallback_is_explicitly_excluded() -> None:
    payload = _episode_payload()
    decision = payload["decisions"][2]  # type: ignore[index]
    decision["destination_provenance"] = "TASK_SPEC_FALLBACK"
    _record_fallback(payload, 2, reason="TASK_SPEC_FALLBACK")

    result = _validate(payload)

    assert result.strict_pure_model_success is False
    assert "decision-2:TASK_SPEC_FALLBACK" in result.exclusion_reasons
    assert "decision-2:DESTINATION_NOT_MODEL_PROVENANCE" in result.exclusion_reasons
