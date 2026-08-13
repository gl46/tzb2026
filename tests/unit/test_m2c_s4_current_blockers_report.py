from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/m2c-s4-current-blockers.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_current_s4_blocker_report_is_bound_and_unmeasured() -> None:
    report = json.loads(REPORT.read_bytes())

    assert report["schema_version"] == "M2CS4CurrentBlockersV1"
    assert report["status"] == "BLOCKED_UNMEASURED_HUMAN_DIRECTION_REQUIRED"
    assert report["q_a_state"] == "PASSED"
    assert report["q_b_state"] == "UNMEASURED"
    assert report["pure_model_success_episodes"] is None
    assert report["d1_triggered"] is False
    assert report["d2_triggered"] is False

    training = report["path_blocked_training"]
    assert training["unique_train_keys_attempted"] == 11
    assert training["raw_v3_eight_step_chains"] == 10
    assert training["training_samples_eligible"] == 0
    assert training["training_samples_packaged"] == 0
    assert not any(
        training[field]
        for field in (
            "training_executed",
            "model_rollout_executed",
            "formal_q_b_evaluation_executed",
            "batch_04_authorized",
            "public_track_reidentification_change_authorized",
        )
    )
    for binding in training["source_reports"]:
        path = ROOT / binding["path"]
        assert _sha256(path) == binding["sha256"]


def test_phase2_and_human_decisions_remain_fail_closed() -> None:
    report = json.loads(REPORT.read_bytes())
    phase2 = report["phase_2"]

    assert phase2["binding_addendum_generation_authorized"] is False
    assert phase2["source_binding_application_authorized"] is False
    assert phase2["exact_plan_preflight_formal_execution_eligible"] is False
    assert phase2["isaac_lula_production_query_callback_available"] is False
    assert all(
        phase2[field] is None
        for field in (
            "formal_physical_runner_binding",
            "formal_deployment_closure_binding",
            "frozen_b0_runtime_wrapper_binding",
            "offline_wire_authentication_verifier_binding",
        )
    )
    source = phase2["source_report"]
    assert _sha256(ROOT / source["path"]) == source["sha256"]

    assert {item["topic"] for item in report["human_decisions_required"]} == {
        "PUBLIC_TRACK_REIDENTIFICATION",
        "ACTIVE_SESSION_B0_FALLBACK",
    }
    for decision in report["human_decisions_required"]:
        assert decision["status"] == "NOT_APPROVED"
        assert decision["valid_choices"] == ["A", "B", "C"]
        assert _sha256(ROOT / decision["request_path"]) == decision["request_sha256"]


def test_current_s4_blocker_report_preserves_project_boundaries() -> None:
    governance = json.loads(REPORT.read_bytes())["governance"]
    assert governance == {
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "b0_changed": False,
        "safety_or_execution_gate_changed": False,
        "existing_evidence_reinterpreted": False,
        "additional_collection_executed_after_batch_03": False,
        "training_executed": False,
        "physical_smoke_executed": False,
        "formal_q_b_evaluation_executed": False,
    }
