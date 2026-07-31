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
