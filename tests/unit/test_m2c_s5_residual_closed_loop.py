from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from m2c.summarize_s5_residual_closed_loop import (
    ResidualDispositionV1,
    S5ResidualEpisodeEvidenceV1,
    summarize_s5,
)
from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopDecisionV1,
    M2BClosedLoopEpisodeV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import physical_receipt_sha256
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2
from xh_agent.policy.qrm_lite.s5_evidence import (
    S5AcceptedGovernanceReceiptV1,
    S5PhysicalExecutionReceiptV1,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(root: Path, key: str, method: str, *, success: bool) -> S5ResidualEpisodeEvidenceV1:
    mode = "ZERO_RESIDUAL" if method == "QRM_COARSE_FC" else "MLP_RESIDUAL"
    skill_provisional = PhysicalSkillReceiptV2(
        receipt_id=f"{key}:{method}:physical-0",
        receipt_sha256="0" * 64,
        executed_skill="REGRASP",
        execution_source="MODEL_SELECTED_REGISTERED_SKILL",
        physically_executed=True,
        started_at_ns=100,
        completed_at_ns=200,
        schema_gate="PASS",
        stale_track_gate="PASS",
        frame_unit_gate="PASS",
        ik_gate="PASS",
        collision_gate="PASS",
        controller_gate="PASS",
        safety_gate="PASS",
    )
    skill_receipt = skill_provisional.model_copy(
        update={"receipt_sha256": physical_receipt_sha256(skill_provisional)}
    )
    receipt_digest = hashlib.sha256(f"{key}:{method}:receipt".encode()).hexdigest()
    receipt = {
        "schema_version": "M2CS5PhysicalExecutionReceiptV1",
        "evidence_origin": "FORMAL_ISAAC_S5_RESIDUAL_CLOSED_LOOP",
        "execution_mode": "REAL_PHYSICS_NO_MOCKS",
        "host": "labserver",
        "run_id": f"{key}:{method}",
        "collected_at_ns": 300,
        "episode_id": f"{key}:{method}",
        "matched_key": key,
        "method": method,
        "residual_mode": mode,
        "final_task_success": success,
        "qwen_world_model_bundle_sha256": receipt_digest,
        "residual_checkpoint_sha256": (
            None if method == "QRM_COARSE_FC" else hashlib.sha256(b"checkpoint").hexdigest()
        ),
        "nominal_action_sha256": hashlib.sha256(b"nominal").hexdigest(),
        "residual_input_sha256": (
            None if method == "QRM_COARSE_FC" else hashlib.sha256(b"input").hexdigest()
        ),
        "residual_output_sha256": hashlib.sha256(
            (b"zero" if method == "QRM_COARSE_FC" else b"mlp")
        ).hexdigest(),
        "residual_protocol_sha256": hashlib.sha256(b"protocol").hexdigest(),
        "residual_is_exact_zero": method == "QRM_COARSE_FC",
        "exact_execution_plan_sha256": hashlib.sha256(b"plan").hexdigest(),
        "executed_exact_execution_plan_sha256": hashlib.sha256(b"plan").hexdigest(),
        "physical_skill_receipts": [skill_receipt.model_dump(mode="json")],
        "r6d_residual_exact_zero": True,
        "gripper_residual_exact_zero": True,
        "real_physics": True,
        "synthetic": False,
        "mocked_physics": False,
        "world_model_mainline": True,
        "residual_refines_world_model_action": True,
        "residual_selects_or_replaces_skill": False,
        "b0_fallback_or_continuation_used": False,
        "collision_or_safety_violation": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = root / "physical-receipts" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    decision_digest = hashlib.sha256(f"{key}:{method}".encode()).hexdigest()
    decision = M2BClosedLoopDecisionV1(
        decision_id=f"{key}:{method}:0",
        step_id=0,
        selected_skill="REGRASP",
        previous_failed_skill="GRASP",
        model_decision=True,
        mapping_status="VALID",
        ik_gate="PASS",
        collision_gate="PASS",
        safety_gate="PASS",
        execution_source="MODEL_SELECTED_B0_SKILL",
        executed_skill="REGRASP",
        outcome="SUCCESS" if success else "FAILURE",
        registry_sha256=decision_digest,
        model_checkpoint_sha256=decision_digest,
        model_input_sha256=decision_digest,
        model_output_sha256=decision_digest,
        mapping_result_sha256=decision_digest,
        gate_evidence_sha256={
            "ik": decision_digest,
            "collision": decision_digest,
            "safety": decision_digest,
            "execution_outcome": digest,
        },
    )
    episode = M2BClosedLoopEpisodeV1(
        episode_id=f"{key}:{method}",
        matched_key=key,
        method=method,
        scene_seed=12_000 + int(key.rsplit("-", 1)[1]),
        failure_type="PATH_BLOCKED",
        initial_success=False,
        final_success=success,
        recovery_attempted=True,
        recovery_success=success,
        retries=0,
        task_time_s=2.0,
        decisions=[decision],
    )
    return S5ResidualEpisodeEvidenceV1(
        schema_version="M2CS5ResidualEpisodeEvidenceV1",
        episode=episode,
        physical_execution_receipt_sha256=digest,
        residual_mode=mode,
    )


def _governance() -> S5AcceptedGovernanceReceiptV1:
    return S5AcceptedGovernanceReceiptV1(
        schema_version="M2CS5AcceptedGovernanceReceiptV1",
        status="ACCEPTED_HUMAN_ADR",
        selected_option="A",
        adr={"path": "docs/decisions/ADR-TEST.md", "sha256": "a" * 64},
        approval_commit="b" * 40,
        world_model_mainline_mandatory=True,
        teacher_used=False,
        privileged_truth_policy_input=False,
        b0_changed=False,
        safety_or_execution_gate_changed=False,
    )


def _frozen(reason: str) -> ResidualDispositionV1:
    return ResidualDispositionV1(
        status="FROZEN_EXACT_ZERO",
        reason=reason,
        limitation="result covers translation residual only",
    )


def test_s5_replays_paired_real_receipts_and_reports_measurable_difference(
    tmp_path: Path,
) -> None:
    rows = []
    for index in range(4):
        key = f"key-{index}"
        rows.extend(
            [
                _row(tmp_path, key, "QRM_COARSE_FC", success=False),
                _row(tmp_path, key, "QRM_COARSE_FC_MLP", success=True),
            ]
        )
    report = summarize_s5(
        rows,
        r6d_disposition=_frozen("no physical r6d labels"),
        gripper_disposition=_frozen("no physical gripper labels"),
        evidence_root=tmp_path,
        governance=_governance(),
        resamples=100,
        seed=7,
    )
    assert report["status"] == "PASS_MEASURABLE_RESIDUAL_DIFFERENCE"
    assert report["comparison_metric"]["estimate"] == 1.0
    assert report["physical_execution_receipts"] == 8
    assert report["r6d_disposition"]["status"] == "FROZEN_EXACT_ZERO"


def test_s5_zero_difference_routes_to_d3_without_fabricating_effect(tmp_path: Path) -> None:
    rows = [
        _row(tmp_path, "key-0", "QRM_COARSE_FC", success=True),
        _row(tmp_path, "key-0", "QRM_COARSE_FC_MLP", success=True),
    ]
    report = summarize_s5(
        rows,
        r6d_disposition=_frozen("unsupported"),
        gripper_disposition=_frozen("unsupported"),
        evidence_root=tmp_path,
        governance=_governance(),
        resamples=20,
        seed=7,
    )
    assert report["status"] == "D3_GO_QRM_COARSE_ONLY"
    assert report["d3_triggered"] is True
    assert report["measurable_difference_observed"] is False


def test_s5_rejects_reused_or_missing_physical_receipts(tmp_path: Path) -> None:
    first = _row(tmp_path, "key-0", "QRM_COARSE_FC", success=False)
    second = _row(tmp_path, "key-0", "QRM_COARSE_FC_MLP", success=True)
    reused = second.model_copy(
        update={"physical_execution_receipt_sha256": first.physical_execution_receipt_sha256}
    )
    with pytest.raises(ValueError, match="reused"):
        summarize_s5(
            [first, reused],
            r6d_disposition=_frozen("unsupported"),
            gripper_disposition=_frozen("unsupported"),
            evidence_root=tmp_path,
            governance=_governance(),
            resamples=10,
        )

    missing = second.model_copy(update={"physical_execution_receipt_sha256": "0" * 64})
    with pytest.raises(ValueError, match="absent"):
        summarize_s5(
            [first, missing],
            r6d_disposition=_frozen("unsupported"),
            gripper_disposition=_frozen("unsupported"),
            evidence_root=tmp_path,
            governance=_governance(),
            resamples=10,
        )


def test_s5_rejects_unpaired_methods_and_active_dimension_without_evidence(
    tmp_path: Path,
) -> None:
    only = _row(tmp_path, "key-0", "QRM_COARSE_FC", success=False)
    with pytest.raises(ValueError, match="paired"):
        summarize_s5(
            [only],
            r6d_disposition=_frozen("unsupported"),
            gripper_disposition=_frozen("unsupported"),
            evidence_root=tmp_path,
            governance=_governance(),
            resamples=10,
        )
    with pytest.raises(ValueError, match="requires physical evidence"):
        ResidualDispositionV1(
            status="TRAINED_WITH_PHYSICAL_EVIDENCE",
            reason="claimed active",
            limitation="none",
        )


def test_s5_rejects_summary_without_separate_accepted_governance(tmp_path: Path) -> None:
    rows = [
        _row(tmp_path, "key-0", "QRM_COARSE_FC", success=False),
        _row(tmp_path, "key-0", "QRM_COARSE_FC_MLP", success=True),
    ]
    with pytest.raises(ValueError, match="separately accepted human ADR"):
        summarize_s5(
            rows,
            r6d_disposition=_frozen("unsupported"),
            gripper_disposition=_frozen("unsupported"),
            evidence_root=tmp_path,
        )


def test_s5_v1_rejects_option_b_and_active_frozen_dimensions(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        S5AcceptedGovernanceReceiptV1.model_validate(
            {**_governance().model_dump(mode="json"), "selected_option": "B"}
        )
    rows = [
        _row(tmp_path, "key-0", "QRM_COARSE_FC", success=False),
        _row(tmp_path, "key-0", "QRM_COARSE_FC_MLP", success=True),
    ]
    active_evidence = tmp_path / "r6d.json"
    active_evidence.write_text("{}\n", encoding="utf-8")
    active = ResidualDispositionV1(
        status="TRAINED_WITH_PHYSICAL_EVIDENCE",
        reason="claimed option-B supervision",
        limitation="not implemented by V1",
        evidence={"path": str(active_evidence), "sha256": _sha(active_evidence)},
    )
    with pytest.raises(ValueError, match="option A requires"):
        summarize_s5(
            rows,
            r6d_disposition=active,
            gripper_disposition=_frozen("unsupported"),
            evidence_root=tmp_path,
            governance=_governance(),
            resamples=10,
        )


def test_s5_receipt_rejects_nonzero_frozen_dimensions_and_teacher(
    tmp_path: Path,
) -> None:
    row = _row(tmp_path, "key-0", "QRM_COARSE_FC_MLP", success=True)
    path = tmp_path / "physical-receipts" / f"{row.physical_execution_receipt_sha256}.json"
    payload = json.loads(path.read_text())
    payload["r6d_residual_exact_zero"] = False
    with pytest.raises(ValidationError, match="r6d/gripper"):
        S5PhysicalExecutionReceiptV1.model_validate(payload)
    payload["r6d_residual_exact_zero"] = True
    payload["teacher_used"] = True
    with pytest.raises(ValidationError):
        S5PhysicalExecutionReceiptV1.model_validate(payload)
