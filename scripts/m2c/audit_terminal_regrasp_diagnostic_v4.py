#!/usr/bin/env python3
"""Replay ADR-0026 V4 measurements and apply the frozen decision tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from m2c.audit_terminal_regrasp_diagnostic import (
    _job_path,
    _json_object,
    _write_create_only,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    DIAGNOSTIC_CONDITIONS,
    M2CTerminalDiagnosticAttemptV1,
    TerminalDiagnosticError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v4 import (
    DIRECT_PUBLIC_RGBD_CONTRACT,
    M2CTerminalDiagnosticConsumptionReceiptV4,
    evaluate_preregistered_decision_tree_v4,
    load_committed_diagnostic_prereg_v4,
    parse_diagnostic_raw_bytes_v4,
)


ROOT = Path(__file__).resolve().parents[2]


def _verify_terminal_hash(terminal: Mapping[str, Any]) -> None:
    claimed = terminal.get("terminal_receipt_sha256")
    if not isinstance(claimed, str):
        raise TerminalDiagnosticError("V4 terminal receipt lacks semantic hash")
    core = dict(terminal)
    del core["terminal_receipt_sha256"]
    if canonical_sha256(core) != claimed:
        raise TerminalDiagnosticError("V4 terminal receipt semantic hash changed")


def audit_campaign_v4(
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
    attempts: list[M2CTerminalDiagnosticAttemptV1] = []
    run_audits: list[dict[str, Any]] = []
    blockers: list[str] = []
    for run in resolved.prereg.runs:
        claim_path = ledger_root / f"claim-{run.ordinal:02d}.json"
        job = _job_path(evidence_root, run.ordinal, run.run_id)
        raw_path = job / "probe" / "terminal-regrasp-diagnostic.json"
        terminal_path = job / "terminal-receipt.json"
        try:
            claim_raw = v4_auth.read_regular_file_once(claim_path)
            claim = M2CTerminalDiagnosticConsumptionReceiptV4.model_validate_json(claim_raw)
            if claim.run != run or claim.prereg_sha256 != resolved.prereg.prereg_sha256:
                raise TerminalDiagnosticError("V4 claim differs from frozen run")
            terminal_raw = v4_auth.read_regular_file_once(terminal_path)
            terminal = _json_object(terminal_raw, label="V4 terminal receipt")
            _verify_terminal_hash(terminal)
            raw_bytes = v4_auth.read_regular_file_once(raw_path)
            raw = parse_diagnostic_raw_bytes_v4(raw_bytes)
            if (
                terminal.get("schema_version") != "M2CTerminalDiagnosticRunTerminalV4"
                or terminal.get("run_id") != run.run_id
                or terminal.get("ordinal") != run.ordinal
                or terminal.get("condition") != run.condition
                or terminal.get("claim_sha256") != sha256_bytes(claim_raw)
                or terminal.get("raw_evidence_sha256") != sha256_bytes(raw_bytes)
                or terminal.get("status") != "COMPLETE_VALID_TERMINAL_MEASUREMENT"
                or raw.authorization.consumption_receipt_sha256 != claim.receipt_sha256
                or raw.authorization.prereg_sha256 != resolved.prereg.prereg_sha256
                or raw.public_rgbd_setup_contract != DIRECT_PUBLIC_RGBD_CONTRACT
            ):
                raise TerminalDiagnosticError("V4 terminal/raw/claim binding changed")
            attempt = M2CTerminalDiagnosticAttemptV1(
                schema_version="M2CTerminalDiagnosticAttemptV1",
                run_id=raw.run_id,
                ordinal=run.ordinal,
                condition=raw.condition,
                terminal_measurement_valid=True,
                terminal_execution_status=raw.terminal_execution_status,
                pregrasp_ik_passed=raw.pregrasp_ik_passed,
                contact_gate_passed=raw.contact_gate_passed,
                selected_free_gap_yaw_rad=raw.selected_free_gap_yaw_rad,
                terminal_target_blocker_surface_gap_m=(raw.terminal_target_blocker_surface_gap_m),
                public_predicates=raw.public_predicates,
                terminal_success=raw.terminal_success,
                physical_action_executed=raw.physical_action_executed,
                collision_or_safety_violations=raw.collision_or_safety_violations,
                teacher_used=False,
                privileged_truth_policy_input=False,
                raw_evidence_sha256=sha256_bytes(raw_bytes),
            )
            attempts.append(attempt)
            run_audits.append(
                {
                    "ordinal": run.ordinal,
                    "run_id": run.run_id,
                    "condition": run.condition,
                    "status": "VALID_TERMINAL_MEASUREMENT",
                    "claim_path": str(claim_path),
                    "claim_sha256": sha256_bytes(claim_raw),
                    "terminal_receipt_path": str(terminal_path),
                    "terminal_receipt_sha256": sha256_bytes(terminal_raw),
                    "raw_evidence_path": str(raw_path),
                    "raw_evidence_sha256": sha256_bytes(raw_bytes),
                    "measurement": attempt.model_dump(mode="json"),
                }
            )
        except (
            OSError,
            ValueError,
            TerminalDiagnosticError,
            v4_auth.CollectionAuthorizationError,
        ) as error:
            blocker = f"run {run.ordinal:02d} {run.run_id}: {type(error).__name__}: {error}"
            blockers.append(blocker)
            run_audits.append(
                {
                    "ordinal": run.ordinal,
                    "run_id": run.run_id,
                    "condition": run.condition,
                    "status": "INCOMPLETE_OR_INVALID",
                    "blocker": blocker,
                }
            )
    decision = None
    if not blockers:
        decision = evaluate_preregistered_decision_tree_v4(
            prereg=resolved.prereg,
            attempts=attempts,
        ).model_dump(mode="json")
    counts = {
        condition: sum(attempt.condition == condition for attempt in attempts)
        for condition in DIAGNOSTIC_CONDITIONS
    }
    successes = {
        condition: sum(
            attempt.condition == condition and attempt.terminal_success for attempt in attempts
        )
        for condition in DIAGNOSTIC_CONDITIONS
    }
    report: dict[str, Any] = {
        "schema_version": "M2CTerminalRegraspDiagnosticAuditV4",
        "status": ("PASS_COMPLETE_DECISION" if decision is not None else "BLOCKED_INCOMPLETE"),
        "campaign_id": resolved.prereg.campaign_id,
        "governing_adr": resolved.prereg.governing_adr,
        "prior_v3_invalidation": resolved.prereg.prior_v3_invalidation.model_dump(mode="json"),
        "prereg_path": str(resolved.path),
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": resolved.prereg.prereg_sha256,
        "prereg_introduced_commit": resolved.introduced_commit,
        "valid_measurements": len(attempts),
        "valid_measurements_by_condition": counts,
        "successes_by_condition": successes,
        "decision": decision,
        "blockers": blockers,
        "runs": run_audits,
        "six_canonical_objects_retained": True,
        "direct_branch_precedes_inherited_v4_chain": True,
        "direct_public_rgbd_setup_contract": DIRECT_PUBLIC_RGBD_CONTRACT,
        "public_rgbd_pixels_tracker_predicates_unchanged": True,
        "no_retry_or_replacement_within_v4": True,
        "v1_v2_or_v3_claim_or_identity_reused": False,
        "training_collection_authorized": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    report["report_content_sha256"] = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
    return report


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M2C terminal-regrasp diagnostic V4 audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Valid measurements: `{report['valid_measurements']}/36`",
        f"- Counts: `{json.dumps(report['valid_measurements_by_condition'], sort_keys=True)}`",
        f"- Successes: `{json.dumps(report['successes_by_condition'], sort_keys=True)}`",
        f"- Selected branch: `{(report.get('decision') or {}).get('selected_branch')}`",
        "- Direct branch precedes inherited V4-chain gate: `true`",
        "- Public RGB-D pixels/tracker/predicates changed: `false`",
        "- V1/V2/V3 claim or identity reused: `false`",
        "- Retry/replacement within V4: `false`",
        "- Teacher/privileged truth policy input: `false/false`",
        "",
    ]
    if report["blockers"]:
        lines.extend(["## Blockers", ""])
        lines.extend(f"- {item}" for item in report["blockers"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    report = audit_campaign_v4(
        project_root=args.project_root.resolve(strict=True),
        prereg_path=args.prereg,
        ledger_root=args.ledger_root.resolve(strict=True),
        evidence_root=args.evidence_root.resolve(strict=True),
    )
    _write_create_only(
        args.output_json,
        (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )
    _write_create_only(args.output_md, _markdown(report).encode())
    print(json.dumps({"status": report["status"], "decision": report["decision"]}))
    return 0 if report["status"] == "PASS_COMPLETE_DECISION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
