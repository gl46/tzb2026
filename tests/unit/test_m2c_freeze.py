from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from m2c.freeze_m2b import build_report


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def test_freeze_report_verifies_baseline_b0_reports_and_local_artifacts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "reports").mkdir(parents=True)
    (repo / "artifacts/m2b").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "m2c@example.invalid")
    git(repo, "config", "user.name", "M2C Test")
    b0 = b"unchanged-b0\n"
    report = b'{"status":"PASS"}\n'
    (repo / "b0.py").write_bytes(b0)
    (repo / "reports/m2b-evidence.json").write_bytes(report)
    index = {
        "artifacts": [
            {"path": "b0.py", "sha256": digest(b0)},
            {
                "path": "reports/m2b-evidence.json",
                "sha256": digest(report),
            },
        ]
    }
    index_bytes = (json.dumps(index, sort_keys=True) + "\n").encode()
    (repo / "reports/m2b-artifact-index.json").write_bytes(index_bytes)
    git(repo, "add", "b0.py", "reports")
    git(repo, "commit", "-qm", "baseline")
    baseline = git(repo, "rev-parse", "HEAD")
    local = b"dataset\n"
    (repo / "artifacts/m2b/data.jsonl").write_bytes(local)
    manifest = {
        "baseline_commit": baseline,
        "b0_files": [
            {"path": "b0.py", "role": "baseline", "sha256": digest(b0)}
        ],
        "m2b_artifact_index": {
            "path": "reports/m2b-artifact-index.json",
            "sha256": digest(index_bytes),
        },
        "m2b_local_artifacts": [
            {"path": "artifacts/m2b/data.jsonl", "sha256": digest(local)}
        ],
    }
    result = build_report(repo, manifest, require_local_artifacts=True)
    assert result["status"] == "PASS"
    assert result["b0_files_match_m2b"] is True
    assert result["m2b_artifact_index"]["verified_entries"] == 2
    assert result["m2b_reports"]["mismatches"] == []
    assert result["local_artifacts_match_m2b"] is True


def test_freeze_report_rejects_a_weakened_working_tree_b0(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "reports").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "m2c@example.invalid")
    git(repo, "config", "user.name", "M2C Test")
    original = b"strong-b0\n"
    (repo / "b0.py").write_bytes(original)
    index_bytes = b'{"artifacts":[]}\n'
    (repo / "reports/m2b-artifact-index.json").write_bytes(index_bytes)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "baseline")
    baseline = git(repo, "rev-parse", "HEAD")
    (repo / "b0.py").write_text("weakened-b0\n")
    manifest = {
        "baseline_commit": baseline,
        "b0_files": [
            {
                "path": "b0.py",
                "role": "baseline",
                "sha256": digest(original),
            }
        ],
        "m2b_artifact_index": {
            "path": "reports/m2b-artifact-index.json",
            "sha256": digest(index_bytes),
        },
        "m2b_local_artifacts": [],
    }
    result = build_report(repo, manifest, require_local_artifacts=True)
    assert result["status"] == "FAIL"
    assert result["b0_files_match_m2b"] is False
    assert any("B0 freeze mismatch" in item for item in result["findings"])
