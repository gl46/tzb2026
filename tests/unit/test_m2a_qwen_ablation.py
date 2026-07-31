from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_qwen_ablation_aggregates_paired_seeds(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "qrm_lite"
        / "summarize_qwen_ablation.py"
    )
    off_paths = []
    on_paths = []
    for seed, off_accuracy, on_accuracy in (
        (20260731, 0.70, 0.80),
        (20260732, 0.72, 0.68),
    ):
        common = {
            "status": "PASS",
            "seed": seed,
            "n_train": 120,
            "n_eval": 50,
            "eval_split": "test",
            "labels": ["APPROACH", "REOBSERVE"],
        }
        off = {
            **common,
            "failure_context": "off",
            "eval_accuracy": off_accuracy,
            "eval_metrics": {"macro_f1": off_accuracy - 0.1},
        }
        on = {
            **common,
            "failure_context": "on",
            "eval_accuracy": on_accuracy,
            "eval_metrics": {"macro_f1": on_accuracy - 0.1},
        }
        off_path = tmp_path / f"off-{seed}.json"
        on_path = tmp_path / f"on-{seed}.json"
        off_path.write_text(json.dumps(off))
        on_path.write_text(json.dumps(on))
        off_paths.append(off_path)
        on_paths.append(on_path)
    output_json = tmp_path / "ablation.json"
    output_md = tmp_path / "ablation.md"
    command = [sys.executable, str(script)]
    for path in off_paths:
        command.extend(["--off-report", str(path)])
    for path in on_paths:
        command.extend(["--on-report", str(path)])
    command.extend(
        ["--report-json", str(output_json), "--report-md", str(output_md)]
    )

    subprocess.run(command, check=True, capture_output=True, text=True)

    report = json.loads(output_json.read_text())
    assert report["status"] == "PASS_WITH_LIMITATIONS"
    assert report["accuracy_deltas"]["per_seed"]["20260731"] == pytest.approx(0.1)
    assert report["accuracy_deltas"]["per_seed"]["20260732"] == pytest.approx(-0.04)
    assert report["accuracy_deltas"]["mean"] == pytest.approx(0.03)
    assert any("did not improve" in item for item in report["limitations"])
    assert report["teacher_used"] is False
    assert report["runtime_revisions"] == [""]
    assert len(report["training_source_sha256"]) == 64
