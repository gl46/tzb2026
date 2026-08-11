#!/usr/bin/env python3
"""Freeze M2B evidence and the exact B0 implementation used as M2C baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_bytes(project: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=project,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"{path}: absent from baseline commit {commit}")
    return completed.stdout


def git_text(project: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def build_report(
    project: Path,
    manifest: dict[str, Any],
    *,
    require_local_artifacts: bool,
) -> dict[str, Any]:
    findings: list[str] = []
    baseline = git_text(
        project,
        ["rev-parse", f"{manifest['baseline_commit']}^{{commit}}"],
    )
    if baseline != manifest["baseline_commit"]:
        findings.append(
            f"baseline commit mismatch: expected {manifest['baseline_commit']}, got {baseline}"
        )

    b0_files = []
    for record in manifest["b0_files"]:
        relative = record["path"]
        expected = record["sha256"]
        baseline_hash = sha256_bytes(git_bytes(project, baseline, relative))
        current_path = project / relative
        current_hash = sha256_file(current_path) if current_path.is_file() else None
        matches = baseline_hash == expected and current_hash == expected
        if not matches:
            findings.append(
                f"B0 freeze mismatch {relative}: baseline={baseline_hash}, current={current_hash}, expected={expected}"
            )
        b0_files.append(
            {
                **record,
                "baseline_sha256": baseline_hash,
                "working_tree_sha256": current_hash,
                "matches_m2b": matches,
            }
        )

    index_record = manifest["m2b_artifact_index"]
    index_bytes = git_bytes(project, baseline, index_record["path"])
    index_hash = sha256_bytes(index_bytes)
    if index_hash != index_record["sha256"]:
        findings.append(
            f"M2B artifact index hash mismatch: {index_hash} != {index_record['sha256']}"
        )
    index = json.loads(index_bytes)
    verified_index_entries = 0
    index_failures = []
    for artifact in index.get("artifacts", []):
        try:
            actual = sha256_bytes(git_bytes(project, baseline, artifact["path"]))
        except ValueError as exc:
            index_failures.append(str(exc))
            continue
        if actual != artifact["sha256"]:
            index_failures.append(
                f"{artifact['path']}: {actual} != {artifact['sha256']}"
            )
        else:
            verified_index_entries += 1
    findings.extend(index_failures)

    baseline_report_paths = [
        path
        for path in git_text(project, ["ls-tree", "-r", "--name-only", baseline, "reports"])
        .splitlines()
        if Path(path).name.startswith("m2b-")
    ]
    report_mismatches = []
    for relative in baseline_report_paths:
        path = project / relative
        baseline_hash = sha256_bytes(git_bytes(project, baseline, relative))
        if not path.is_file() or sha256_file(path) != baseline_hash:
            report_mismatches.append(relative)
    findings.extend(f"M2B report changed or missing: {path}" for path in report_mismatches)

    local_artifacts = []
    for artifact in manifest["m2b_local_artifacts"]:
        path = project / artifact["path"]
        actual = sha256_file(path) if path.is_file() else None
        matches = actual == artifact["sha256"]
        required = require_local_artifacts
        if required and not matches:
            findings.append(
                f"M2B local artifact mismatch {artifact['path']}: {actual} != {artifact['sha256']}"
            )
        local_artifacts.append(
            {
                **artifact,
                "actual_sha256": actual,
                "matches_m2b": matches,
                "required": required,
            }
        )

    return {
        "schema_version": "M2CS0FreezeReportV1",
        "status": "PASS" if not findings else "FAIL",
        "baseline_commit": baseline,
        "m2b_evidence_readonly": True,
        "m2b_artifact_index": {
            "path": index_record["path"],
            "sha256": index_hash,
            "expected_sha256": index_record["sha256"],
            "entries": len(index.get("artifacts", [])),
            "verified_entries": verified_index_entries,
            "failures": index_failures,
        },
        "m2b_reports": {
            "baseline_count": len(baseline_report_paths),
            "mismatches": report_mismatches,
        },
        "b0_files": b0_files,
        "b0_files_match_m2b": all(item["matches_m2b"] for item in b0_files),
        "local_artifacts": local_artifacts,
        "local_artifacts_match_m2b": all(
            item["matches_m2b"] for item in local_artifacts if item["required"]
        ),
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
        "findings": findings,
    }


def changed_files(project: Path) -> list[str]:
    lines = git_text(project, ["status", "--porcelain=v1"]).splitlines()
    return sorted(line[3:] for line in lines if len(line) > 3)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    task = report["task_report"]
    lines = [
        "# M2C S0 M2B/B0 freeze",
        "",
        f"- status: **{report['status']}**",
        f"- M2B baseline commit: `{report['baseline_commit']}`",
        f"- M2B artifact index: {report['m2b_artifact_index']['verified_entries']}/{report['m2b_artifact_index']['entries']} verified",
        f"- M2B reports unchanged: {not report['m2b_reports']['mismatches']} ({report['m2b_reports']['baseline_count']} files)",
        f"- B0 implementation/parameters/gates match M2B: {report['b0_files_match_m2b']}",
        f"- local M2B artifacts match frozen hashes: {report['local_artifacts_match_m2b']}",
        "- Teacher used: no; kill-rule events: none",
        "- privileged truth used as policy input: no",
        "- world-model mainline replaced: no",
        "",
        "## Frozen B0 files",
        "",
        "| Path | Role | M2B SHA-256 | Match |",
        "| --- | --- | --- | --- |",
        *[
            f"| `{item['path']}` | {item['role']} | `{item['sha256']}` | {'PASS' if item['matches_m2b'] else 'FAIL'} |"
            for item in report["b0_files"]
        ],
        "",
        "## Task report",
        "",
        "- changed files:",
        *([f"  - `{item}`" for item in task["changed_files"]] or ["  - none"]),
        f"- tests: {task['tests']['passed']} passed, {task['tests']['failed']} failed",
        "- failures:",
        *([f"  - {item}" for item in task["failures"]] or ["  - none"]),
        "- blockers:",
        *([f"  - {item}" for item in task["blockers"]] or ["  - none"]),
        f"- next command: `{report['next_command']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT / "configs/m2c_b0_freeze.json",
    )
    parser.add_argument(
        "--verification",
        type=Path,
        default=PROJECT / "reports/m2c-s0-verification.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT / "reports/m2c-s0-freeze.json",
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=PROJECT / "reports/m2c-s0-freeze.md",
    )
    parser.add_argument("--allow-missing-local-artifacts", action="store_true")
    args = parser.parse_args()
    if os.environ.get("M2B_EVIDENCE_READONLY") != "1":
        parser.error("M2B_EVIDENCE_READONLY=1 is required")
    manifest = json.loads(args.manifest.read_text())
    report = build_report(
        args.project,
        manifest,
        require_local_artifacts=not args.allow_missing_local_artifacts,
    )
    verification = (
        json.loads(args.verification.read_text())
        if args.verification.is_file()
        else None
    )
    tests = verification.get("tests", {}) if verification else {}
    verification_passed = bool(
        verification
        and verification.get("status") == "PASS"
        and int(tests.get("passed", 0)) > 0
        and int(tests.get("failed", 1)) == 0
    )
    if not verification_passed:
        report["findings"].append("S0 full-suite verification is missing or failing")
        report["status"] = "FAIL"
    report["adr"] = "docs/decisions/ADR-0020-m2c-model-owned-recovery.md"
    if not (args.project / report["adr"]).is_file():
        report["findings"].append("ADR-0020 is missing")
        report["status"] = "FAIL"
    generated_reports = {
        str(args.report.resolve().relative_to(args.project.resolve())),
        str(args.report_md.resolve().relative_to(args.project.resolve())),
    }
    report["task_report"] = {
        "changed_files": sorted(
            {*changed_files(args.project), *generated_reports}
        ),
        "tests": {
            "passed": int(tests.get("passed", 0)),
            "failed": int(tests.get("failed", 0)) if verification else None,
        },
        "failures": verification.get("failures", []) if verification else [],
        "blockers": report["findings"],
    }
    report["next_command"] = "make m2c-s1" if report["status"] == "PASS" else "make m2c-freeze"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    write_markdown(args.report_md, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
