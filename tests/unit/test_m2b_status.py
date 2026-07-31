from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_status_reports_missing_dataset_without_claiming_completion(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "m2b-s0-m2a-freeze.json").write_text('{"status":"PASS"}')
    (reports / "m2b-s1-physical-failure-smoke.json").write_text(
        json.dumps(
            {
                "status": "PASS_PUBLIC_FAILURES_AND_RECOVERIES",
                "accepted_failures": [
                    "EMPTY_GRASP",
                    "WRONG_OBJECT",
                    "RELEASE_FAILURE",
                ],
            }
        )
    )
    (reports / "m2b-s5-physical-runtime-gates.json").write_text(
        json.dumps(
            {
                "status": (
                    "PASS_PHYSICAL_POST_EXECUTION_RECEIPTS_NOT_FORMAL_MAPPING"
                ),
                "receipts_complete_and_passing": 6,
                "post_execution_gate_rate": 1.0,
                "prospective_planning_checks_complete": False,
            }
        )
    )
    output = tmp_path / "status.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/m2b/status.py",
            "--report-dir",
            str(reports),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(output.read_text())
    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert payload["teacher_used"] is False
    assert payload["dataset_v2_episodes_valid"] == 0
    assert payload["physical_runtime_receipts_complete_and_passing"] == 6
    assert payload["physical_runtime_post_execution_gate_rate"] == 1.0
    assert payload["prospective_runtime_planning_checks_complete"] is False
    assert (
        "at least 50 informative physical residual pairs are not packaged"
        in payload["blockers"]
    )


def test_status_rejects_present_but_nonformal_terminal_reports(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    fixtures = {
        "m2b-s0-m2a-freeze.json": {"status": "PASS"},
        "m2b-s1-physical-failure-smoke.json": {
            "status": "PASS_PUBLIC_FAILURES_AND_RECOVERIES",
            "accepted_failures": [
                "EMPTY_GRASP",
                "WRONG_OBJECT",
                "RELEASE_FAILURE",
            ],
        },
        "m2b-s2-dataset-v2.json": {
            "limited_coverage_gate_passed": True,
            "episodes_quarantined": 0,
            "failure_counts": {
                failure: 50
                for failure in (
                    "EMPTY_GRASP",
                    "WRONG_OBJECT",
                    "RELEASE_FAILURE",
                )
            },
            "successful_recovery_counts": {
                failure: 50
                for failure in (
                    "EMPTY_GRASP",
                    "WRONG_OBJECT",
                    "RELEASE_FAILURE",
                )
            },
        },
        "m2b-s3-residual-pairs.json": {
            "status": "PASS_INFORMATIVE_RESIDUAL_TARGETS",
            "valid_pairs": 50,
        },
        "m2b-s5-runtime-mapping-offline.json": {
            "runtime_mapping_rate": 1.0,
            "planning_checks_complete": True,
        },
        "m2b-s4-training.json": {
            "status": "PASS_ABLATION_COMPLETE",
            "formal_ablation": False,
        },
        "m2b-s5-closed-loop.json": {
            "status": "IN_PROGRESS_NOT_FORMAL",
            "formal_evaluation_ready": False,
            "qrm_model_decisions_executed": 50,
        },
    }
    for name, payload in fixtures.items():
        (reports / name).write_text(json.dumps(payload))
    output = tmp_path / "status.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/m2b/status.py",
            "--report-dir",
            str(reports),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(output.read_text())
    assert completed.returncode == 2
    assert payload["goal_complete"] is False
    assert "two-seed A100 NoFC/FC training has not run" in payload["blockers"]
    assert (
        "matched B0/QRM Isaac closed-loop evaluation has not run"
        in payload["blockers"]
    )
