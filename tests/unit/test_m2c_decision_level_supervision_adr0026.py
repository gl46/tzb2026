from __future__ import annotations

import copy

import pytest

from xh_agent.policy.qrm_lite.decision_level_supervision_v1 import (
    ADR0026_PATH,
    ADR0026_SHA256,
    DecisionGateSummaryV1,
    M2CS4DecisionLevelDatasetManifestV1,
    canonical_sha256,
    decide_adr0026_episode_eligibility,
)


def _gate(
    index: int,
    *,
    pointer: bool = True,
    controller: bool = True,
    terminal_status: str | None = None,
) -> DecisionGateSummaryV1:
    admitted = controller
    return DecisionGateSummaryV1(
        decision_index=index,
        canonical_decision_index=True,
        public_observation_fresh_and_unique=True,
        public_capture_unique=True,
        public_candidate_replay_passed=True,
        selected_target_encodable_in_k8=pointer,
        destination_contract_passed=True,
        exactly_one_canonical_physical_receipt=True,
        expected_skill_executed=True,
        physical_timing_passed=True,
        schema_gate_passed=True,
        stale_track_gate_passed=True,
        frame_unit_gate_passed=True,
        ik_gate_passed=True,
        collision_gate_passed=True,
        controller_gate_passed=controller,
        safety_gate_passed=True,
        collision_or_safety_violation=False,
        teacher_used=False,
        privileged_truth_policy_input=False,
        terminal_execution_status=terminal_status if index == 7 else None,
        terminal_step_physically_succeeded=(
            index == 7 and admitted and terminal_status == "LIFTED"
        ),
        all_adr0026_admission_gates_passed=admitted,
    )


def _eligibility(gates: list[DecisionGateSummaryV1], *, exclusion_reasons: list[str] | None = None):
    return decide_adr0026_episode_eligibility(
        episode_id="episode-1",
        matched_key="matched-1",
        evidence_revision="V4",
        episode_terminal_outcome="TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED",
        episode_final_task_success=False,
        decision_gates=gates,
        exclusion_reasons=exclusion_reasons or [],
    )


def test_adr0026_admits_prefix_and_masks_only_unencodable_pointer_head() -> None:
    gates = [_gate(index, pointer=index != 1) for index in range(7)]
    gates.append(_gate(7, controller=False, terminal_status="CONTACT_GATE_REJECTED"))
    result = _eligibility(gates)
    assert result.admitted_decision_indices == list(range(7))
    assert result.pointer_head_masked_decision_indices == [1]
    assert result.terminal_step_physically_succeeded is False
    assert result.episode_level_training_eligible is False
    assert result.decision_level_prefix_training_eligible is True


def test_adr0026_terminal_row_requires_a_passing_lifted_receipt() -> None:
    gates = [_gate(index) for index in range(7)]
    gates.append(_gate(7, terminal_status="LIFTED"))
    result = _eligibility(gates)
    assert result.admitted_decision_indices == list(range(8))
    assert result.terminal_step_physically_succeeded is True

    tampered = gates[7].model_dump(mode="json")
    tampered["terminal_execution_status"] = "CONTACT_GATE_REJECTED"
    with pytest.raises(ValueError, match="terminal physical success"):
        DecisionGateSummaryV1.model_validate(tampered)


def test_adr0026_rejects_entire_prefix_when_an_admission_gate_failed() -> None:
    gates = [_gate(index) for index in range(8)]
    gates[3] = _gate(3, controller=False)
    result = _eligibility(gates, exclusion_reasons=["STEP_3:CONTROLLER_GATE_NOT_PASSING"])
    assert result.admitted_decision_indices == []
    assert result.decision_level_prefix_training_eligible is False


def _manifest_payload() -> dict[str, object]:
    pointer_masked = [
        {
            "episode_id": f"episode-{index}",
            "matched_key": f"matched-{index}",
            "scene_seed": 19000 + index,
            "decision_index": 1,
            "reason": "PUBLIC_TARGET_OUTSIDE_REPLAYED_K8_POINTER_HEAD_MASKED",
        }
        for index in range(14)
    ]
    payload: dict[str, object] = {
        "schema_version": "M2CS4DecisionLevelDatasetManifestV1",
        "status": "PASS_ADR0026_DECISION_LEVEL_DATASET",
        "accepted_adr": {"path": ADR0026_PATH, "sha256": ADR0026_SHA256},
        "source_yield_audit": {"path": "reports/yield.json", "sha256": "a" * 64},
        "shards": [
            {
                "revision": "V3",
                "path": "artifacts/v3.jsonl",
                "sha256": "b" * 64,
                "byte_count": 1,
                "row_count": 71,
            },
            {
                "revision": "V4",
                "path": "artifacts/v4.jsonl",
                "sha256": "c" * 64,
                "byte_count": 1,
                "row_count": 273,
            },
        ],
        "replayed_complete_chains": 49,
        "qualifying_prefix_episodes": 49,
        "excluded_prefix_episodes": 0,
        "final_successful_episodes": 0,
        "final_failed_episodes": 49,
        "terminal_physically_successful_episodes": 1,
        "terminal_physically_failed_episodes": 48,
        "decision_rows_total": 344,
        "decision_rows_v3": 71,
        "decision_rows_v4": 273,
        "skill_head_supervised_rows": 344,
        "pointer_head_supervised_rows": 330,
        "pointer_head_masked_rows": 14,
        "destination_head_supervised_rows": 344,
        "decision_index_counts": {**{str(index): 49 for index in range(7)}, "7": 1},
        "terminal_outcome_episode_counts": {
            "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED": 31,
            "TERMINAL_PREGRASP_IK_GATE_REJECTED": 17,
            "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED": 1,
        },
        "terminal_outcome_row_counts": {
            "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED": 217,
            "TERMINAL_PREGRASP_IK_GATE_REJECTED": 119,
            "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED": 8,
        },
        "pointer_masked_decisions": pointer_masked,
        "training_executed": False,
        "model_rollout_executed": False,
        "formal_q_b_evaluation_executed": False,
        "q_b_success_definition_changed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "bundle_smoke_checkpoint_asia_shanghai": "2026-08-20",
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def test_manifest_locks_49_chains_344_rows_and_head_masks() -> None:
    manifest = M2CS4DecisionLevelDatasetManifestV1.model_validate(_manifest_payload())
    assert manifest.decision_rows_total == 344
    assert manifest.pointer_head_masked_rows == 14

    tampered = copy.deepcopy(_manifest_payload())
    tampered["pointer_head_supervised_rows"] = 331
    tampered["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValueError):
        M2CS4DecisionLevelDatasetManifestV1.model_validate(tampered)
