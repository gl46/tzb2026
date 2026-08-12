from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import m2c.freeze_s3_evidence as freeze_s3
from m2c.freeze_s3_evidence import (
    LEDGER_NAME,
    MANDATORY_FAILURES,
    freeze_evidence_tree,
    validate_worker_status,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_worker(root: Path, worker: str, *, corrupt_hash: bool = False) -> Path:
    worker_root = root / worker
    records = []
    counts: Counter[str] = Counter()
    for index, failure in enumerate(MANDATORY_FAILURES):
        evidence = worker_root / f"{failure.lower()}-{index}.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            json.dumps({"failure_type": failure, "worker": worker}) + "\n",
            encoding="utf-8",
        )
        digest = "0" * 64 if corrupt_hash and index == 0 else sha256(evidence)
        records.append(
            {
                "accepted": True,
                "failure_type": failure,
                "scene_seed": 10000 + index,
                "status": "PASS",
                "evidence": str(evidence),
                "evidence_sha256": digest,
            }
        )
        counts[failure] += 1
    status = {
        "schema_version": "M2BFailureEvidenceWorkerStatusV1",
        "status": "COMPLETE_ACCEPTED_TARGET",
        "accepted_target_per_failure": 1,
        "accepted_counts": dict(counts),
        "records": records,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    path = worker_root / "worker-status.json"
    path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def restore_write_modes(root: Path) -> None:
    root.chmod(0o755)
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)


def test_freeze_tree_hashes_every_file_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "s3-failure-evidence-v1"
    build_worker(root, "worker0")
    build_worker(root, "worker1")
    try:
        first = freeze_evidence_tree(root, accepted_target=1)
        second = freeze_evidence_tree(root, accepted_target=1)

        assert first["status"] == "PASS"
        assert first["already_frozen"] is False
        assert first["files_hashed"] == 8
        assert first["accepted_counts"] == {
            "EMPTY_GRASP": 2,
            "WRONG_OBJECT": 2,
            "RELEASE_FAILURE": 2,
        }
        assert second["already_frozen"] is True
        assert second["ledger_sha256"] == first["ledger_sha256"]
        assert (root / LEDGER_NAME).is_file()
        assert all(path.stat().st_mode & 0o222 == 0 for path in [root, *root.rglob("*")])
    finally:
        restore_write_modes(root)


def test_worker_status_rejects_evidence_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "s3-failure-evidence-v1"
    status = build_worker(root, "worker0", corrupt_hash=True)

    try:
        validate_worker_status(root, status, accepted_target=1)
    except ValueError as error:
        assert "SHA-256 mismatch" in str(error)
    else:
        raise AssertionError("worker evidence hash mismatch was accepted")


def test_worker_status_rejects_teacher_boundary_violation(tmp_path: Path) -> None:
    root = tmp_path / "s3-failure-evidence-v1"
    status = build_worker(root, "worker0")
    payload = json.loads(status.read_text())
    payload["teacher_used"] = True
    status.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_worker_status(root, status, accepted_target=1)
    except ValueError as error:
        assert "Teacher-free" in str(error)
    else:
        raise AssertionError("Teacher boundary violation was accepted")


def test_worker_status_rejects_counts_above_frozen_target(tmp_path: Path) -> None:
    root = tmp_path / "s3-failure-evidence-v1"
    status = build_worker(root, "worker0")
    payload = json.loads(status.read_text())
    payload["accepted_counts"]["EMPTY_GRASP"] = 2
    status.write_text(json.dumps(payload), encoding="utf-8")

    try:
        validate_worker_status(root, status, accepted_target=1)
    except ValueError as error:
        assert "do not equal frozen target" in str(error)
    else:
        raise AssertionError("accepted count above frozen target was accepted")


def test_local_freeze_report_drops_idempotence_execution_detail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "schema_version": "M2CS3EvidenceFreezeV1",
                "status": "PASS",
                "already_frozen": True,
            }
        )
        stderr = ""

    monkeypatch.setattr(
        freeze_s3.subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )
    source = tmp_path / "freeze.py"
    source.write_text("# synthetic source\n", encoding="utf-8")
    monkeypatch.setattr(freeze_s3, "__file__", str(source))

    report = freeze_s3._run_over_ssh(
        SimpleNamespace(
            host="root@labserver",
            root=freeze_s3.DEFAULT_REMOTE_ROOT,
            accepted_target=25,
        )
    )

    assert report["status"] == "PASS"
    assert report["host"] == "root@labserver"
    assert "already_frozen" not in report
