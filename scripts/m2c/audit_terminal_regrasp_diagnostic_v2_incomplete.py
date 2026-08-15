#!/usr/bin/env python3
"""Audit the consumed V2 diagnostic that stopped before terminal actuation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    TerminalDiagnosticError,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    M2CTerminalDiagnosticConsumptionReceiptV2,
    load_committed_diagnostic_prereg_v2,
)


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PROBE_ERROR = "M2B public RGB-D capture requires a failure injection"
IMPLEMENTATION_PATH = "scripts/m2c/audit_terminal_regrasp_diagnostic_v2_incomplete.py"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=lambda pairs: (
                dict(pairs)
                if len(pairs) == len({key for key, _ in pairs})
                else (_ for _ in ()).throw(ValueError("duplicate JSON key"))
            ),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise TerminalDiagnosticError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise TerminalDiagnosticError(f"{label} is not a JSON object")
    return value


def _verify_self_hash(payload: Mapping[str, Any], *, field: str, label: str) -> None:
    claimed = payload.get(field)
    if not isinstance(claimed, str):
        raise TerminalDiagnosticError(f"{label} lacks {field}")
    core = dict(payload)
    del core[field]
    if canonical_sha256(core) != claimed:
        raise TerminalDiagnosticError(f"{label} semantic hash changed")


def _inventory(root: Path, *, prefix: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TerminalDiagnosticError("V2 incomplete evidence has unsafe member")
        raw = v4_auth.read_regular_file_once(path)
        entries.append(
            {
                "path": f"{prefix}/{path.relative_to(root).as_posix()}",
                "size": len(raw),
                "sha256": _sha256(raw),
            }
        )
    return entries


def audit_v2_incomplete_campaign(
    *,
    project_root: Path,
    prereg_path: Path,
    ledger_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    resolved = load_committed_diagnostic_prereg_v2(
        project_root=project_root,
        prereg_path=prereg_path,
    )
    prereg = resolved.prereg
    run = prereg.runs[0]
    suffix = run.run_id.removeprefix("m2c-s4-terminal-diagnostic-")[:16]
    job_root = evidence_root / f"run-00-{suffix}"
    claim_path = ledger_root / "claim-00.json"
    projected_claim_path = job_root / "authorization" / "diagnostic-claim.json"
    job_path = job_root / "job-receipt.json"
    terminal_path = job_root / "terminal-receipt.json"
    console_path = job_root / "probe" / "console.log"
    derived_path = job_root / "derived" / "terminal-regrasp-diagnostic-probe-v2.py"
    raw_path = job_root / "probe" / "terminal-regrasp-diagnostic.json"

    claim_raw = v4_auth.read_regular_file_once(claim_path)
    if claim_raw != v4_auth.read_regular_file_once(projected_claim_path):
        raise TerminalDiagnosticError("V2 projected claim differs from canonical claim")
    claim = M2CTerminalDiagnosticConsumptionReceiptV2.model_validate_json(claim_raw)
    if (
        claim.run != run
        or claim.ordinal != 0
        or claim.prereg_sha256 != prereg.prereg_sha256
        or claim.event != "CONSUMED_BEFORE_STAGE"
    ):
        raise TerminalDiagnosticError("V2 claim differs from frozen ordinal zero")

    job_raw = v4_auth.read_regular_file_once(job_path)
    job = _json_object(job_raw, label="V2 diagnostic job receipt")
    _verify_self_hash(job, field="receipt_sha256", label="V2 diagnostic job receipt")
    if (
        job.get("schema_version") != "M2CTerminalDiagnosticJobReceiptV2"
        or job.get("status") != "CONSUMED_V2_DIAGNOSTIC_ONLY_BEFORE_STAGE"
        or job.get("run") != run.model_dump(mode="json")
        or job.get("claim_sha256") != _sha256(claim_raw)
        or job.get("derived_probe_sha256") != claim.derived_probe_sha256
        or job.get("prereg_sha256") != prereg.prereg_sha256
        or job.get("teacher_used") is not False
        or job.get("privileged_truth_policy_input") is not False
    ):
        raise TerminalDiagnosticError("V2 job receipt cross-binding changed")
    derived_raw = v4_auth.read_regular_file_once(derived_path)
    if _sha256(derived_raw) != claim.derived_probe_sha256:
        raise TerminalDiagnosticError("V2 derived probe digest changed")

    terminal_raw = v4_auth.read_regular_file_once(terminal_path)
    terminal = _json_object(terminal_raw, label="V2 diagnostic terminal receipt")
    _verify_self_hash(
        terminal,
        field="terminal_receipt_sha256",
        label="V2 diagnostic terminal receipt",
    )
    expected_terminal = {
        "schema_version": "M2CTerminalDiagnosticRunTerminalV2",
        "run_id": run.run_id,
        "ordinal": 0,
        "condition": "C1_NO_BLOCKER",
        "claim_sha256": _sha256(claim_raw),
        "stage_completed": True,
        "probe_returncode": 0,
        "raw_evidence_sha256": None,
        "status": "INCOMPLETE",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "error_type": "TerminalDiagnosticError",
    }
    for key, expected in expected_terminal.items():
        if terminal.get(key) != expected:
            raise TerminalDiagnosticError(f"V2 terminal receipt changed field {key}")
    if set(terminal) != set(expected_terminal) | {
        "probe_command_sha256",
        "terminalized_at_ns",
        "terminal_receipt_sha256",
    }:
        raise TerminalDiagnosticError("V2 terminal receipt has unexpected fields")
    if not isinstance(terminal.get("probe_command_sha256"), str):
        raise TerminalDiagnosticError("V2 terminal receipt lacks probe command digest")
    if (
        not isinstance(terminal.get("terminalized_at_ns"), int)
        or terminal["terminalized_at_ns"] <= claim.consumed_at_ns
    ):
        raise TerminalDiagnosticError("V2 terminal time does not follow consumption")

    console_raw = v4_auth.read_regular_file_once(console_path)
    try:
        console = console_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TerminalDiagnosticError("V2 probe console is not UTF-8") from error
    required_console_fragments = (
        f'"message": "{EXPECTED_PROBE_ERROR}"',
        '"error_type": "ValueError"',
        "in _setup_m2b_public_rgbd",
        f'raise ValueError("{EXPECTED_PROBE_ERROR}")',
    )
    if any(fragment not in console for fragment in required_console_fragments):
        raise TerminalDiagnosticError("V2 console does not prove public-capture mismatch")
    source = derived_raw.decode("utf-8")
    setup_call = source.index("m2b_public_rgbd = _setup_m2b_public_rgbd(stage, output)")
    controller_setup = source.index("SimulationManager.setup_simulation(")
    first_direct_execution = source.index("direct_result = _execute_m2b_public_regrasp(")
    if not setup_call < controller_setup < first_direct_execution:
        raise TerminalDiagnosticError("V2 source no longer proves pre-controller failure order")
    if raw_path.exists():
        raise TerminalDiagnosticError("V2 incomplete attempt unexpectedly has raw evidence")
    if sorted(path.name for path in ledger_root.glob("claim-*.json")) != ["claim-00.json"]:
        raise TerminalDiagnosticError("V2 ledger is not exact one-claim prefix")
    if sorted(path.name for path in evidence_root.glob("run-*")) != [job_root.name]:
        raise TerminalDiagnosticError("V2 evidence has unexpected additional runs")

    inventory = [
        *_inventory(ledger_root, prefix="ledger"),
        *_inventory(evidence_root, prefix="evidence"),
    ]
    report: dict[str, Any] = {
        "schema_version": "M2CTerminalRegraspDiagnosticIncompleteAuditV2",
        "status": "BLOCKED_INCOMPLETE_PUBLIC_CAPTURE_SETUP_MISMATCH",
        "campaign_id": prereg.campaign_id,
        "governing_adr": prereg.governing_adr,
        "implementation": {
            "path": IMPLEMENTATION_PATH,
            "sha256": _sha256(v4_auth.read_regular_file_once(project_root / IMPLEMENTATION_PATH)),
        },
        "preregistration": {
            "path": str(resolved.path),
            "file_sha256": resolved.file_sha256,
            "content_sha256": prereg.prereg_sha256,
            "introduced_commit": resolved.introduced_commit,
        },
        "consumed_run_count": 1,
        "unrun_count": len(prereg.runs) - 1,
        "valid_terminal_measurements": 0,
        "decision": None,
        "r1_r2_r3_evaluation_allowed": False,
        "failed_run": {
            "ordinal": 0,
            "run_id": run.run_id,
            "condition": run.condition,
            "claim_sha256": _sha256(claim_raw),
            "claim_semantic_sha256": claim.receipt_sha256,
            "job_receipt_sha256": _sha256(job_raw),
            "terminal_receipt_sha256": _sha256(terminal_raw),
            "terminal_receipt_semantic_sha256": terminal["terminal_receipt_sha256"],
            "probe_console_sha256": _sha256(console_raw),
            "derived_probe_sha256": _sha256(derived_raw),
            "stage_completed": True,
            "kit_started": True,
            "controller_initialized": False,
            "terminal_primitive_called": False,
            "raw_terminal_measurement_present": False,
            "physical_action_outcome": "NOT_AVAILABLE",
            "blocker_class": "PUBLIC_CAPTURE_SETUP_REQUIRES_LEGACY_FAILURE_INJECTION",
            "blocker": EXPECTED_PROBE_ERROR,
        },
        "campaign_can_satisfy_frozen_denominator": False,
        "further_v2_execution_authorized": False,
        "retry_or_replacement_authorized": False,
        "training_collection_authorized": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "evidence_inventory": inventory,
        "evidence_inventory_sha256": canonical_sha256(inventory),
    }
    report["report_content_sha256"] = canonical_sha256(report)
    return report


def _write_create_only(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise TerminalDiagnosticError("short V2 incomplete audit write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _markdown(report: Mapping[str, Any]) -> str:
    failed = report["failed_run"]
    return (
        "# M2C terminal-regrasp diagnostic V2 incomplete audit\n\n"
        f"- Status: `{report['status']}`\n"
        "- Valid terminal measurements: `0/36`\n"
        "- R1/R2/R3 decision: `withheld`\n"
        f"- Consumed/unrun: `{report['consumed_run_count']}/{report['unrun_count']}`\n"
        f"- Failed condition: `{failed['condition']}`\n"
        f"- Blocker: `{failed['blocker']}`\n"
        "- Stage/Kit/controller/terminal/raw: `complete/started/not initialized/not called/absent`\n"
        "- Physical action outcome: `NOT_AVAILABLE`\n"
        "- Retry/replacement/further V2 execution: `false/false/false`\n"
        "- Training collection: `not authorized`\n"
        "- Teacher/privileged truth policy input: `false/false`\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    report = audit_v2_incomplete_campaign(
        project_root=args.project_root.resolve(strict=True),
        prereg_path=args.prereg,
        ledger_root=args.ledger_root.resolve(strict=True),
        evidence_root=args.evidence_root.resolve(strict=True),
    )
    _write_create_only(
        args.output_json,
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n",
    )
    _write_create_only(args.output_md, _markdown(report).encode())
    print(json.dumps({"status": report["status"], "decision": None}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
