#!/usr/bin/env python3
"""Freeze the completed M2C S3 remote evidence tree with a SHA-256 ledger."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any


DEFAULT_REMOTE_ROOT = Path("/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1")
DEFAULT_REPORT = (
    Path("reports/m2c-s3-evidence-freeze.json")
    if __file__ == "<stdin>"
    else Path(__file__).resolve().parents[2] / "reports/m2c-s3-evidence-freeze.json"
)
MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
WORKER_STATUS_RELATIVE_PATHS = (
    Path("worker0/worker-status.json"),
    Path("worker1/worker-status.json"),
)
LEDGER_NAME = "evidence-sha256.txt"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def validate_worker_status(
    root: Path,
    path: Path,
    *,
    accepted_target: int,
) -> tuple[dict[str, Any], list[Path]]:
    if path.is_symlink():
        raise ValueError(f"worker status may not be a symlink: {path}")
    raw = path.read_bytes()
    status = json.loads(raw)
    if status.get("schema_version") != "M2BFailureEvidenceWorkerStatusV1":
        raise ValueError(f"unsupported worker status schema: {path}")
    if status.get("status") != "COMPLETE_ACCEPTED_TARGET":
        raise ValueError(f"worker has not reached frozen accepted target: {path}")
    if status.get("teacher_used") is not False:
        raise ValueError(f"worker status is not explicitly Teacher-free: {path}")
    if status.get("privileged_truth_policy_input") is not False:
        raise ValueError(f"worker status used privileged truth as policy input: {path}")

    reported = status.get("accepted_counts", {})
    if any(int(reported.get(failure, 0)) < accepted_target for failure in MANDATORY_FAILURES):
        raise ValueError(f"worker accepted counts are below target: {path}")

    observed: Counter[str] = Counter()
    evidence_paths: list[Path] = []
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    root_resolved = root.resolve()
    for record in status.get("records", []):
        if record.get("accepted") is not True:
            continue
        failure = str(record.get("failure_type"))
        if failure not in MANDATORY_FAILURES:
            raise ValueError(f"unsupported accepted failure type in {path}: {failure}")
        declared_evidence = Path(str(record.get("evidence")))
        if declared_evidence.is_symlink():
            raise ValueError(f"accepted evidence may not be a symlink: {declared_evidence}")
        evidence = declared_evidence.resolve()
        try:
            evidence.relative_to(root_resolved)
        except ValueError as error:
            raise ValueError(f"accepted evidence escapes frozen root: {evidence}") from error
        expected = record.get("evidence_sha256")
        if not _is_sha256(expected):
            raise ValueError(f"malformed accepted evidence SHA-256: {evidence}")
        if evidence in seen_paths or str(expected) in seen_hashes:
            raise ValueError(f"duplicate accepted evidence binding: {evidence}")
        if not evidence.is_file() or evidence.is_symlink():
            raise ValueError(f"accepted evidence is missing or symlinked: {evidence}")
        actual = sha256_bytes(evidence.read_bytes())
        if actual != expected:
            raise ValueError(f"accepted evidence SHA-256 mismatch: {evidence}")
        observed[failure] += 1
        evidence_paths.append(evidence)
        seen_paths.add(evidence)
        seen_hashes.add(str(expected))

    for failure in MANDATORY_FAILURES:
        if observed[failure] != int(reported.get(failure, -1)):
            raise ValueError(
                f"accepted count does not match accepted records for {failure}: {path}"
            )
    snapshot = {
        "path": str(path),
        "sha256": sha256_bytes(raw),
        "status": status["status"],
        "accepted_counts": {failure: observed[failure] for failure in MANDATORY_FAILURES},
        "record_count": len(status.get("records", [])),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return snapshot, evidence_paths


def validate_all_worker_statuses(
    root: Path,
    *,
    accepted_target: int,
) -> tuple[list[dict[str, Any]], list[Path]]:
    snapshots = []
    accepted_paths: list[Path] = []
    for relative in WORKER_STATUS_RELATIVE_PATHS:
        snapshot, evidence = validate_worker_status(
            root,
            root / relative,
            accepted_target=accepted_target,
        )
        snapshots.append(snapshot)
        accepted_paths.extend(evidence)
    if len(set(accepted_paths)) != len(accepted_paths):
        raise ValueError("accepted evidence is duplicated across S3 workers")
    accepted_hashes = [sha256_bytes(path.read_bytes()) for path in accepted_paths]
    if len(set(accepted_hashes)) != len(accepted_hashes):
        raise ValueError("accepted evidence SHA-256 is duplicated across S3 workers")
    return snapshots, accepted_paths


def _tree_files(root: Path, ledger: Path) -> list[Path]:
    paths = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink forbidden in S3 evidence tree: {path}")
        if path.is_file() and path != ledger:
            paths.append(path)
        elif not path.is_dir() and path != ledger:
            raise ValueError(f"non-regular entry forbidden in S3 evidence tree: {path}")
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def _parse_ledger(root: Path, ledger: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not _is_sha256(digest) or not relative:
            raise ValueError(f"malformed S3 evidence ledger line: {line!r}")
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"ledger path escapes S3 evidence root: {relative}") from error
        if relative in entries:
            raise ValueError(f"duplicate S3 evidence ledger path: {relative}")
        entries[relative] = digest
    return entries


def _verify_ledger(root: Path, ledger: Path, files: list[Path]) -> None:
    entries = _parse_ledger(root, ledger)
    relative_files = {path.relative_to(root).as_posix(): path for path in files}
    if set(entries) != set(relative_files):
        raise ValueError("S3 evidence ledger file set does not match evidence tree")
    for relative, path in relative_files.items():
        if sha256_bytes(path.read_bytes()) != entries[relative]:
            raise ValueError(f"S3 evidence ledger hash mismatch: {path}")


def _tree_is_readonly(root: Path) -> bool:
    return all(
        not (path.stat().st_mode & stat.S_IWUSR)
        and not (path.stat().st_mode & stat.S_IWGRP)
        and not (path.stat().st_mode & stat.S_IWOTH)
        for path in [root, *root.rglob("*")]
    )


def freeze_evidence_tree(
    root: Path,
    *,
    accepted_target: int = 25,
) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"S3 evidence root is missing or symlinked: {root}")
    snapshots, accepted_paths = validate_all_worker_statuses(
        root,
        accepted_target=accepted_target,
    )

    ledger = root / LEDGER_NAME
    files = _tree_files(root, ledger)
    already_frozen = ledger.exists()
    if already_frozen:
        _verify_ledger(root, ledger, files)
    else:
        payload = "".join(
            f"{sha256_bytes(path.read_bytes())}  {path.relative_to(root).as_posix()}\n"
            for path in files
        )
        temporary = root / f".{LEDGER_NAME}.tmp-{os.getpid()}"
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(ledger)
        finally:
            if temporary.exists():
                temporary.unlink()
    try:
        final_snapshots, final_accepted_paths = validate_all_worker_statuses(
            root,
            accepted_target=accepted_target,
        )
        if final_snapshots != snapshots or final_accepted_paths != accepted_paths:
            raise ValueError("S3 worker evidence bindings changed during freeze")
    except (OSError, ValueError):
        if not already_frozen and ledger.exists():
            ledger.unlink()
        raise
    for path in [*_tree_files(root, ledger), ledger]:
        path.chmod(path.stat().st_mode & ~0o222)
    directories = sorted(
        [path for path in root.rglob("*") if path.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in [*directories, root]:
        directory.chmod(directory.stat().st_mode & ~0o222)
    final_files = _tree_files(root, ledger)
    _verify_ledger(root, ledger, final_files)
    if not _tree_is_readonly(root):
        raise ValueError("S3 evidence tree retained writable paths after freeze")

    combined = Counter()
    for snapshot in snapshots:
        combined.update(snapshot["accepted_counts"])
    return {
        "schema_version": "M2CS3EvidenceFreezeV1",
        "status": "PASS",
        "remote_root": str(root),
        "ledger": str(ledger),
        "ledger_sha256": sha256_bytes(ledger.read_bytes()),
        "files_hashed": len(files),
        "evidence_tree_readonly": True,
        "already_frozen": already_frozen,
        "worker_status_snapshots": snapshots,
        "accepted_counts": {failure: combined[failure] for failure in MANDATORY_FAILURES},
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }


def _assert_no_live_collection(root: Path) -> None:
    root_text = str(root)
    running_workers = []
    for process in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            command = process.read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if "run_failure_evidence_worker.py" in command and root_text in command:
            running_workers.append(command.strip())
    if running_workers:
        raise ValueError("S3 evidence worker is still running")

    completed = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    containers = [name for name in completed.stdout.splitlines() if name.startswith("m2c-s3-v1-")]
    if containers:
        raise ValueError(f"S3 collection containers are still running: {containers}")


def _run_remote_worker(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if root != DEFAULT_REMOTE_ROOT:
        raise SystemExit(f"refusing non-frozen S3 evidence root: {root}")
    if args.accepted_target != 25:
        raise SystemExit("refusing non-frozen S3 accepted target")
    try:
        _assert_no_live_collection(root)
        report = freeze_evidence_tree(root, accepted_target=args.accepted_target)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _run_over_ssh(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        args.host,
        "python3",
        "-",
        "--remote-worker",
        "--root",
        str(args.root),
        "--accepted-target",
        str(args.accepted_target),
    ]
    completed = subprocess.run(
        command,
        input=Path(__file__).read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(detail or "remote S3 evidence freeze failed")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit("remote S3 evidence freeze returned malformed JSON") from error
    report["host"] = args.host
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--root", type=Path, default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--accepted-target", type=int, default=25)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--remote-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.remote_worker:
        return _run_remote_worker(args)
    if os.environ.get("M2B_EVIDENCE_READONLY") != "1":
        raise SystemExit("M2B_EVIDENCE_READONLY=1 is required")
    if args.root != DEFAULT_REMOTE_ROOT:
        raise SystemExit(f"refusing non-frozen S3 evidence root: {args.root}")
    if args.accepted_target != 25:
        raise SystemExit("refusing non-frozen S3 accepted target")
    report = _run_over_ssh(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
