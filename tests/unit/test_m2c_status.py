from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from m2c.terminal_evidence import verify_final


def run_status(reports: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    output = reports / "m2c-status.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/m2c/status.py",
            "--report-dir",
            str(reports),
            "--output",
            str(output),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    return completed, json.loads(output.read_text())


def write(reports: Path, name: str, payload: dict) -> None:
    (reports / name).write_text(json.dumps(payload))


def common_report(**updates: object) -> dict:
    return {
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
        **updates,
    }


def complete_fixtures(reports: Path, *, pure: int = 2) -> None:
    write(
        reports,
        "m2c-s0-freeze.json",
        common_report(
            status="PASS",
            b0_files_match_m2b=True,
            m2b_evidence_readonly=True,
        ),
    )
    write(reports, "m2c-s1-deliverables.json", common_report(status="PASS"))
    write(
        reports,
        "m2c-s2-exploration-v4.json",
        common_report(
            status="Q_A_PASSED",
            decision={
                "q_a_passed": True,
                "physical_recoverability_established": True,
                "d1_triggered": False,
                "b0_final_task_success_rate": 0.0,
                "b0_headroom": 1.0,
            },
        ),
    )
    counts = {
        "EMPTY_GRASP": 101,
        "WRONG_OBJECT": 100,
        "RELEASE_FAILURE": 111,
    }
    write(
        reports,
        "m2c-s3-dataset-v3.json",
        common_report(
            status="PASS_S3_FULL_CLASS_COVERAGE",
            dataset_version="isaac-industrial-v3-headroom",
            full_class_coverage_gate_passed=True,
            episodes_valid=sum(counts.values()),
            episodes_quarantined=0,
            failure_counts=counts,
            successful_recovery_counts=counts,
            split_group_leakage=[],
            output_sha256="a" * 64,
            evidence_freeze={
                "evidence_tree_readonly": True,
                "ledger_sha256": "d" * 64,
                "files_hashed": 400,
            },
            worker_status_snapshots=[
                {
                    "status": "COMPLETE_ACCEPTED_TARGET",
                    "sha256": digest * 64,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                }
                for digest in ("e", "f")
            ],
            accepted_evidence_audit={
                "status": "PASS",
                "records_audited": 150,
                "counts_by_failure": {
                    "EMPTY_GRASP": 50,
                    "WRONG_OBJECT": 50,
                    "RELEASE_FAILURE": 50,
                },
                "evidence_sha256_matches": 150,
                "strict_physical_public_predicates_passed": 150,
                "public_predicate_results_checked": 300,
                "collision_gates_checked": 550,
                "collision_or_safety_violations": 0,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "acceptance_predicate": {
                    "path": "scripts/m2b/run_physical_failure_smoke.py",
                    "sha256": "7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865",
                    "public_rgbd_required": True,
                    "predicate": "m2b.run_physical_failure_smoke.accepted",
                },
                "records": [{} for _ in range(150)],
            },
        ),
    )
    write(
        reports,
        "m2c-s4-model-owned-recovery.json",
        common_report(
            status=("PASS_Q_B_PURE_MODEL_RECOVERY" if pure else "D2_GO_QRM_COARSE_ONLY"),
            human_expressivity_adr_committed=True,
            q_b_training_executed=True,
            q_b_evaluation_executed=True,
            pure_model_success_episodes=pure,
            d2_triggered=pure == 0,
        ),
    )
    if pure:
        write(
            reports,
            "m2c-s5-residual-closed-loop.json",
            common_report(
                status="PASS_MEASURABLE_RESIDUAL_DIFFERENCE",
                residual_closed_loop_executed=True,
                measurable_difference_observed=True,
                d3_triggered=False,
            ),
        )
    write(
        reports,
        "m2c-s6-matched.json",
        common_report(
            status="PASS_M2C_S6_FORMAL_MATCHED_EVALUATION",
            formal_evaluation_ready=True,
            complete_matched_keys=30,
            qrm_model_decisions_executed=90,
            collision_or_safety_violations=0,
            primary_metric={
                "name": "fc_gain_over_b0",
                "estimate": 0.2,
                "interval": [0.05, 0.35],
            },
            episodes_sha256="b" * 64,
            preregistration_sha256="c" * 64,
        ),
    )
    write(
        reports,
        "m2c-final-verification.json",
        {
            "status": "PASS",
            "tests": {"passed": 500, "failed": 0},
            "b0_freeze_recheck_passed": True,
            "m2b_evidence_readonly": True,
            "failures": [],
            "commands": ["pytest"],
        },
    )


def test_status_fails_closed_when_terminal_evidence_is_missing(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    completed, payload = run_status(reports)
    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["fc_gain_over_b0"] is None
    assert payload["pure_model_success_episodes"] is None
    assert payload["teacher_used"] is False
    assert payload["privileged_truth_policy_input"] is False
    assert payload["world_model_mainline_replaced"] is False
    assert payload["completion_gates"]["teacher_free"] is False
    assert payload["next_command"] == "M2B_EVIDENCE_READONLY=1 make m2c-s3-dataset"
    for name in (
        "m2c-status.md",
        "m2c-completion-audit.json",
        "m2c-completion-audit.md",
        "m2c-dataset-card.md",
        "m2c-reproducibility.md",
        "m2c-artifact-index.json",
    ):
        assert (reports / name).is_file()


def test_status_rejects_synthetic_terminal_summaries(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    complete_fixtures(reports)
    completed, payload = run_status(reports)
    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["status"] == "PARTIAL"
    assert payload["pure_model_success_episodes"] is None
    assert payload["fc_gain_over_b0"] is None
    assert payload["fc_gain_over_b0_confidence_interval"] is None
    assert payload["model_decisions_executed"] == 0
    assert payload["teacher_used"] is False
    assert payload["system_verdict"] == "EVIDENCE_PENDING"
    assert any("S4 terminal evidence failed closed" in item for item in payload["blockers"])
    assert any("S5 terminal evidence failed closed" in item for item in payload["blockers"])
    assert any("S6 terminal evidence failed closed" in item for item in payload["blockers"])
    assert any("final verification failed closed" in item for item in payload["blockers"])


def test_synthetic_d2_does_not_skip_s5_or_complete(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    complete_fixtures(reports, pure=0)
    completed, payload = run_status(reports)
    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["d2_triggered"] is False
    assert payload["system_verdict"] == "EVIDENCE_PENDING"
    assert payload["completion_gates"]["s4_q_b_governed_disposition"] is False
    assert payload["completion_gates"]["s5_residual_closed_loop_or_d2_disposition"] is False


def test_status_rejects_summary_only_underpowered_or_unsafe_s6(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    complete_fixtures(reports)
    s6_path = reports / "m2c-s6-matched.json"
    s6 = json.loads(s6_path.read_text())
    s6["qrm_model_decisions_executed"] = 49
    s6["collision_or_safety_violations"] = 1
    s6_path.write_text(json.dumps(s6))
    completed, payload = run_status(reports)
    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["completion_gates"]["s6_formal_four_method_matched_evaluation"] is False
    assert payload["matched_keys"] == 0
    assert payload["collision_or_safety_violations"] is None


def test_status_rejects_s3_without_frozen_evidence_ledger(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    complete_fixtures(reports)
    s3_path = reports / "m2c-s3-dataset-v3.json"
    s3 = json.loads(s3_path.read_text())
    s3["evidence_freeze"]["evidence_tree_readonly"] = False
    s3["worker_status_snapshots"][1]["status"] = "RUNNING_OR_PARTIAL"
    s3_path.write_text(json.dumps(s3))

    completed, payload = run_status(reports)

    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["completion_gates"]["s3_full_class_coverage"] is False


def test_status_rejects_s3_without_complete_strict_evidence_audit(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    complete_fixtures(reports)
    s3_path = reports / "m2c-s3-dataset-v3.json"
    s3 = json.loads(s3_path.read_text())
    s3["accepted_evidence_audit"]["records_audited"] = 149
    s3["accepted_evidence_audit"]["collision_or_safety_violations"] = 1
    s3_path.write_text(json.dumps(s3))

    completed, payload = run_status(reports)

    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["completion_gates"]["s3_full_class_coverage"] is False


def test_status_distinguishes_teacher_violation_from_missing_evidence(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    complete_fixtures(reports)
    s3_path = reports / "m2c-s3-dataset-v3.json"
    s3 = json.loads(s3_path.read_text())
    s3["teacher_used"] = True
    s3_path.write_text(json.dumps(s3))
    completed, payload = run_status(reports)
    assert completed.returncode == 2
    assert payload["teacher_used"] is True
    assert payload["completion_gates"]["teacher_free"] is False


def test_final_verifier_rejects_pytest_selection_flags() -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    result = verify_final(
        Path.cwd(),
        {
            "status": "PASS",
            "tests": {"passed": 1, "failed": 0},
            "terminal_evidence": {
                "schema_version": "M2CFinalVerificationBindingV1",
                "checked_head_commit": head,
                "full_test_command": [sys.executable, "-m", "pytest", "-q", "-k", "smoke"],
                "junit": {"path": "/absent/junit.xml", "sha256": "0" * 64},
                "b0_freeze_manifest_sha256": "0" * 64,
                "m2b_artifact_index_sha256": "0" * 64,
            },
        },
    )
    assert result.passed is False
    assert any("complete pytest suite" in blocker for blocker in result.blockers)
