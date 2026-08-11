from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from m2c.s2_decision import (
    CandidateStatus,
    DomainCandidateDecision,
    S2Disposition,
    decide_s2_stop_loss,
)


PROJECT = Path(__file__).resolve().parents[2]
REPORT = PROJECT / "reports/m2c-s2-exploration-v4.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_report_passes_both_frozen_q_a_conditions() -> None:
    report = json.loads(REPORT.read_text())
    decision = report["decision"]
    b0 = report["b0_executions"]
    proofs = report["existence_proof_executions"]

    assert report["status"] == "Q_A_PASSED"
    assert all(item["classification"] == "ADMISSIBLE_B0_SAFE_REJECTION" for item in b0)
    assert all(item["public_target_valid"] is True for item in b0)
    assert sum(item["final_task_success"] for item in b0) == 0
    assert decision["b0_valid_matched_keys"] == len(b0) == 3
    assert decision["b0_final_task_success_rate"] == pytest.approx(0.0)
    assert decision["b0_headroom"] == pytest.approx(1.0)
    assert decision["b0_rate_below_0_8"] is True

    strict = [item for item in proofs if item["strict_complete_existence_proof"]]
    assert len(strict) == decision["complete_existence_proofs"] == 1
    assert strict[0]["scene_seed"] == 9077
    assert strict[0]["target_regrasp_executed"] is True
    assert set(strict[0]["public_regrasp_predicates"]) >= {
        "grasped=true",
        "lifted=true",
    }
    assert strict[0]["recovery_training_eligible"] is True
    assert strict[0]["collision_violations"] == 0
    assert decision["physical_recoverability_established"] is True
    assert decision["q_a_passed"] is True


def test_v4_report_excludes_every_non_strict_top_level_pass() -> None:
    report = json.loads(REPORT.read_text())
    excluded = [
        item
        for item in report["existence_proof_executions"]
        if not item["strict_complete_existence_proof"]
    ]
    assert len(excluded) == 2
    assert all(item["top_level_probe_status"] == "PASS" for item in excluded)
    assert all(item["exclusion_reasons"] for item in excluded)
    assert all(item["target_regrasp_executed"] is False for item in excluded)
    assert all(item["collision_violations"] == 0 for item in excluded)


def test_v4_report_hashes_frozen_sources_and_keeps_q_b_closed() -> None:
    report = json.loads(REPORT.read_text())
    manifest = PROJECT / report["candidate_manifest"]["path"]
    expressivity = PROJECT / report["q_b_expressivity_gate"]["preregistration"]
    runtime = report["frozen_runtime"]

    assert sha256(manifest) == report["candidate_manifest"]["sha256"]
    assert sha256(expressivity) == report["q_b_expressivity_gate"]["preregistration_sha256"]
    assert sha256(PROJECT / "scripts/isaac_m1b_actuation_probe.py") == runtime["b0_probe_sha256"]
    assert (
        sha256(PROJECT / "scripts/m2b/run_physical_failure_smoke.py") == runtime["b0_runner_sha256"]
    )
    assert runtime["b0_modified"] is False
    assert runtime["retries_changed"] is False
    assert runtime["evidence_file_count"] == 167
    assert runtime["evidence_tree_readonly"] is True
    assert len(runtime["evidence_sha256_ledger_sha256"]) == 64
    assert report["teacher_used"] is False
    assert report["privileged_truth_policy_input"] is False
    assert report["q_b_expressivity_gate"]["human_adr_committed"] is False
    assert report["q_b_expressivity_gate"]["q_b_blocked"] is True
    assert report["decision"]["q_b_training_or_evaluation_authorized"] is False


def test_v4_pass_closes_domain_iteration_without_d1() -> None:
    records = [
        DomainCandidateDecision(index, CandidateStatus.INVALID_PUBLIC_CONTRACT, "prior")
        for index in (1, 2, 3)
    ]
    records.append(DomainCandidateDecision(4, CandidateStatus.Q_A_PASSED, "passed"))
    decision = decide_s2_stop_loss(records)
    report = json.loads(REPORT.read_text())

    assert decision.disposition == S2Disposition.PASS_Q_A
    assert decision.next_candidate_number is None
    assert report["decision"]["stop_loss_disposition"] == decision.disposition.value
    assert report["decision"]["d1_triggered"] is False
    assert report["decision"]["v5_forbidden"] is True
