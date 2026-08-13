from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/m2c-s4-current-blockers.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _recompute_collection_counts(
    source_bindings: list[dict[str, str]],
) -> tuple[int, int]:
    matched_keys: set[str] = set()
    raw_v3_eight_step_chains = 0
    for binding in source_bindings:
        source = json.loads((ROOT / binding["path"]).read_bytes())
        assert source["observed_counts"]["training_samples_eligible"] == 0
        assert source["observed_counts"]["training_samples_packaged"] == 0
        for attempt in source["attempts"]:
            matched_keys.add(attempt["identity"]["matched_key"])
            evidence = attempt["classification_evidence"]
            if evidence.get("chain_schema") == "M2CPathBlockedProbeChainV3":
                assert evidence["physical_chain_steps"] == 8
                raw_v3_eight_step_chains += 1
    return len(matched_keys), raw_v3_eight_step_chains


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
    assert {binding["path"] for binding in training["source_reports"]} == {
        "reports/m2c-s4-v3-path-blocked-train-collection.json",
        "reports/m2c-s4-v3-path-blocked-train-collection-batch03.json",
    }
    recomputed_unique_keys, recomputed_raw_chains = _recompute_collection_counts(
        training["source_reports"]
    )
    assert training["unique_train_keys_attempted"] == recomputed_unique_keys == 11
    assert training["raw_v3_eight_step_chains"] == recomputed_raw_chains == 10
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

    introduced_commit = _git(
        "log",
        "--diff-filter=A",
        "--format=%H",
        "--",
        str(REPORT.relative_to(ROOT)),
    ).splitlines()[0]
    checked_commit = report["checked_head_commit"]
    assert checked_commit in _git("show", "-s", "--format=%P", introduced_commit).split()
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", checked_commit, introduced_commit],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )


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
    assert {binding["path"] for binding in phase2["source_bindings"]} == {
        "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py",
        "src/xh_agent/policy/qrm_lite/isaac_lula_non_actuating_callbacks_v1.py",
    }
    for binding in phase2["source_bindings"]:
        path = ROOT / binding["path"]
        assert _sha256(path) == binding["sha256"]
        checked_bytes = subprocess.check_output(
            ["git", "show", f"{report['checked_head_commit']}:{binding['path']}"],
            cwd=ROOT,
        )
        assert hashlib.sha256(checked_bytes).hexdigest() == binding["sha256"]
    assert phase2["blockers"][0] == ("SOURCE_AUDIT_PRODUCTION_QUERY_CALLBACK_NOT_AVAILABLE")
    assert "COMPLETE_CONTINUOUS_SELF_COLLISION_QUERY_NOT_AVAILABLE" not in phase2["blockers"]

    assert {item["topic"] for item in report["human_decisions_required"]} == {
        "PUBLIC_TRACK_REIDENTIFICATION",
        "ACTIVE_SESSION_B0_FALLBACK",
        "A3_CONTINUOUS_SELF_COLLISION",
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
