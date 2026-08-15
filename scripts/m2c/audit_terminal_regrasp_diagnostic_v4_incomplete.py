#!/usr/bin/env python3
"""Audit the consumed ADR-0026 V4 run that stopped in stage construction."""

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
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v4 import (
    M2CTerminalDiagnosticConsumptionReceiptV4,
    load_committed_diagnostic_prereg_v4,
)


ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_PATH = "scripts/m2c/audit_terminal_regrasp_diagnostic_v4_incomplete.py"
CRASH_FRAGMENTS = (
    "[Fatal] [carb.crashreporter-breakpad.plugin]",
    "libusd_sdf.so!",
    "Sdf_PathNode::GetPathToken",
    "Segmentation fault      (core dumped)",
)


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
            raise TerminalDiagnosticError("V4 incomplete evidence has unsafe member")
        raw = v4_auth.read_regular_file_once(path)
        entries.append(
            {
                "path": f"{prefix}/{path.relative_to(root).as_posix()}",
                "size": len(raw),
                "sha256": _sha256(raw),
            }
        )
    return entries


def audit_v4_incomplete_campaign(
    *,
    project_root: Path,
    prereg_path: Path,
    ledger_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    resolved = load_committed_diagnostic_prereg_v4(
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
    stage_console_path = job_root / "stage" / "console.log"
    stage_usdc_path = job_root / "stage" / "m1b_physics_scene.usdc"
    stage_metrics_path = job_root / "stage" / "metrics.json"
    derived_path = job_root / "derived" / "terminal-regrasp-diagnostic-probe-v4.py"
    probe_console_path = job_root / "probe" / "console.log"
    raw_path = job_root / "probe" / "terminal-regrasp-diagnostic.json"

    claim_raw = v4_auth.read_regular_file_once(claim_path)
    if claim_raw != v4_auth.read_regular_file_once(projected_claim_path):
        raise TerminalDiagnosticError("V4 projected claim differs from canonical claim")
    claim = M2CTerminalDiagnosticConsumptionReceiptV4.model_validate_json(claim_raw)
    if (
        claim.run != run
        or claim.ordinal != 0
        or claim.prereg_sha256 != prereg.prereg_sha256
        or claim.event != "CONSUMED_BEFORE_STAGE"
    ):
        raise TerminalDiagnosticError("V4 claim differs from frozen ordinal zero")

    job_raw = v4_auth.read_regular_file_once(job_path)
    job = _json_object(job_raw, label="V4 diagnostic job receipt")
    _verify_self_hash(job, field="receipt_sha256", label="V4 diagnostic job receipt")
    if (
        job.get("schema_version") != "M2CTerminalDiagnosticJobReceiptV4"
        or job.get("status") != "CONSUMED_V4_DIAGNOSTIC_ONLY_BEFORE_STAGE"
        or job.get("run") != run.model_dump(mode="json")
        or job.get("claim_sha256") != _sha256(claim_raw)
        or job.get("derived_probe_sha256") != claim.derived_probe_sha256
        or job.get("prereg_sha256") != prereg.prereg_sha256
        or job.get("direct_branch_precedes_inherited_v4_chain") is not True
        or job.get("direct_public_rgbd_setup_contract") != prereg.direct_public_rgbd_setup_contract
        or job.get("teacher_used") is not False
        or job.get("privileged_truth_policy_input") is not False
    ):
        raise TerminalDiagnosticError("V4 job receipt cross-binding changed")
    derived_raw = v4_auth.read_regular_file_once(derived_path)
    if _sha256(derived_raw) != claim.derived_probe_sha256:
        raise TerminalDiagnosticError("V4 derived probe digest changed")

    terminal_raw = v4_auth.read_regular_file_once(terminal_path)
    terminal = _json_object(terminal_raw, label="V4 diagnostic terminal receipt")
    _verify_self_hash(
        terminal,
        field="terminal_receipt_sha256",
        label="V4 diagnostic terminal receipt",
    )
    expected_terminal = {
        "schema_version": "M2CTerminalDiagnosticRunTerminalV4",
        "run_id": run.run_id,
        "ordinal": 0,
        "condition": "C1_NO_BLOCKER",
        "claim_sha256": _sha256(claim_raw),
        "stage_completed": False,
        "probe_returncode": None,
        "raw_evidence_sha256": None,
        "status": "INCOMPLETE",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "error_type": "TerminalDiagnosticError",
    }
    for key, expected in expected_terminal.items():
        if terminal.get(key) != expected:
            raise TerminalDiagnosticError(f"V4 terminal receipt changed field {key}")
    if set(terminal) != set(expected_terminal) | {
        "terminalized_at_ns",
        "terminal_receipt_sha256",
    }:
        raise TerminalDiagnosticError("V4 terminal receipt has unexpected fields")
    if (
        not isinstance(terminal.get("terminalized_at_ns"), int)
        or terminal["terminalized_at_ns"] <= claim.consumed_at_ns
    ):
        raise TerminalDiagnosticError("V4 terminal time does not follow consumption")

    console_raw = v4_auth.read_regular_file_once(stage_console_path)
    try:
        console = console_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TerminalDiagnosticError("V4 stage console is not UTF-8") from error
    if any(fragment not in console for fragment in CRASH_FRAGMENTS):
        raise TerminalDiagnosticError("V4 console does not prove the USD-stage SIGSEGV")
    if not stage_usdc_path.is_file() or stage_metrics_path.exists():
        raise TerminalDiagnosticError("V4 stage outputs do not prove an incomplete stage")
    stage_usdc_raw = v4_auth.read_regular_file_once(stage_usdc_path)
    if not stage_usdc_raw:
        raise TerminalDiagnosticError("V4 incomplete USD stage is empty")
    if probe_console_path.exists() or raw_path.exists():
        raise TerminalDiagnosticError("V4 stage failure unexpectedly reached diagnostic probe")
    if any(path.is_file() for path in (job_root / "probe").rglob("*")):
        raise TerminalDiagnosticError("V4 stage failure unexpectedly produced probe evidence")

    source = derived_raw.decode("utf-8")
    main_start = source.index("def main() -> int:")
    direct_call = source.index("direct_result = _execute_m2b_public_regrasp(", main_start)
    inherited_guard = source.index(
        'raise RuntimeError("M2C chain requires public blocker and task-target tracks")',
        main_start,
    )
    if not direct_call < inherited_guard:
        raise TerminalDiagnosticError("V4 source no longer routes direct branch first")
    if sorted(path.name for path in ledger_root.glob("claim-*.json")) != ["claim-00.json"]:
        raise TerminalDiagnosticError("V4 ledger is not exact one-claim prefix")
    if sorted(path.name for path in evidence_root.glob("run-*")) != [job_root.name]:
        raise TerminalDiagnosticError("V4 evidence has unexpected additional runs")

    inventory = [
        *_inventory(ledger_root, prefix="ledger"),
        *_inventory(evidence_root, prefix="evidence"),
    ]
    report: dict[str, Any] = {
        "schema_version": "M2CTerminalRegraspDiagnosticIncompleteAuditV4",
        "status": "BLOCKED_INCOMPLETE_STAGE_SIGSEGV_BEFORE_DIAGNOSTIC_PROBE",
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
        "frozen_decision_tree": prereg.decision_tree.model_dump(mode="json"),
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
            "stage_console_sha256": _sha256(console_raw),
            "incomplete_stage_usdc_sha256": _sha256(stage_usdc_raw),
            "derived_probe_sha256": _sha256(derived_raw),
            "stage_completed": False,
            "stage_kit_started": True,
            "stage_metrics_present": False,
            "diagnostic_probe_started": False,
            "diagnostic_controller_initialized": False,
            "terminal_primitive_called": False,
            "raw_terminal_measurement_present": False,
            "diagnostic_physical_action_outcome": "NOT_AVAILABLE",
            "blocker_class": "ISAAC_USD_STAGE_PROCESS_SIGSEGV",
            "blocker": "stage process terminated with SIGSEGV in libusd_sdf before metrics",
        },
        "campaign_can_satisfy_frozen_denominator": False,
        "further_v4_execution_authorized": False,
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
                raise TerminalDiagnosticError("short V4 incomplete audit write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _markdown(report: Mapping[str, Any]) -> str:
    failed = report["failed_run"]
    return (
        "# M2C terminal-regrasp diagnostic V4 incomplete audit\n\n"
        f"- Status: `{report['status']}`\n"
        "- Valid terminal measurements: `0/36`\n"
        "- R1/R2/R3 decision: `withheld`\n"
        f"- Consumed/unrun: `{report['consumed_run_count']}/{report['unrun_count']}`\n"
        f"- Failed condition: `{failed['condition']}`\n"
        f"- Blocker: `{failed['blocker']}`\n"
        "- Stage Kit/output/metrics: `started/partial USD/absent`\n"
        "- Diagnostic probe/controller/terminal/raw: `not started/not initialized/not called/absent`\n"
        "- Diagnostic physical action outcome: `NOT_AVAILABLE`\n"
        "- Retry/replacement/further V4 execution: `false/false/false`\n"
        "- Training collection: `halted`\n"
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
    report = audit_v4_incomplete_campaign(
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
