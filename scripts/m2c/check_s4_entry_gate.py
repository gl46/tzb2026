#!/usr/bin/env python3
"""Generate the read-only, fail-closed M2C S4 Q-B entry report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.s4_entry_gate import evaluate_s4_entry_gate


PROJECT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(path: Path, payload: dict[str, object]) -> None:
    local = payload["local_contract_tests"]
    physical = payload["physical_integration"]
    assert isinstance(local, dict)
    assert isinstance(physical, dict)
    blockers = [str(item) for item in payload.get("blockers", [])]
    lines = [
        "# M2C S4 Q-B entry gate",
        "",
        f"- Status: **{payload['status']}**",
        f"- Checked Git HEAD: `{payload['checked_head_commit']}`",
        "- Required physical policy: trained Qwen V2 world-model bundle "
        "(LoRA adapter + skill/pointer/destination heads).",
        "- Structured Q0/Q1/Q2 checkpoint accepted as world model: `false`",
        f"- Governance gate passed: `{payload['governance_gate_passed']}`",
        f"- Local contract tests passed: `{payload['local_contract_tests_passed']}`",
        (
            "- Real physical integration receipt passed: "
            f"`{payload['physical_integration_receipt_passed']}`"
        ),
        (f"- Formal Q-B evaluation authorized: `{payload['formal_q_b_evaluation_authorized']}`"),
        f"- ADR-authorized training scope available: `{payload['training_authorized_by_adr']}`",
        "- Training executed by this command: `false`",
        "- Evaluation executed by this command: `false`",
        "- Teacher used: `false`",
        "- Privileged simulator truth used as policy input: `false`",
        "- Synthetic unit journal accepted as physical evidence: `false`",
        "",
        "## Evidence layers",
        "",
        f"- Local layer: `{local.get('status')}`; origin `{local.get('evidence_origin')}`.",
        (
            f"- Physical layer: `{physical.get('status')}`; "
            f"origin `{physical.get('evidence_origin')}`; "
            f"receipts `{physical.get('physical_receipts_observed')}`; "
            f"Qwen bundle verified `{physical.get('world_model_bundle_verified')}`."
        ),
        "",
        "Local pytest evidence proves contracts only. ADR §7(3) passes only with one "
        "real Isaac receipt from a frozen SMOKE key containing eight fresh public "
        "observations, eight unique physical receipts, and trained Qwen V2 "
        "world-model provenance. Entry independently replays the complete formal "
        "runner wire evidence and its hash-bound labserver service/session audits; "
        "it also requires a frozen implementation commit/container/import closure, "
        "an unchanged B0 runtime wrapper, and a separately verifiable authentication "
        "receipt that never persists endpoint HMAC secrets. Arbitrary hash files and "
        "a structured Q012 NPZ cannot satisfy this layer.",
        "",
        "## Blockers",
        "",
        *([f"- {item}" for item in blockers] or ["- None."]),
        "",
        "## Task report",
        "",
        "- Changed files: entry-gate implementation, CLI, Make target, and unit tests.",
        "- Tests: `pytest -q tests/unit/test_m2c_s4_entry_gate.py`.",
        "- Failures: none beyond the blockers above.",
        (
            "- Blocker: none."
            if payload["formal_q_b_evaluation_authorized"]
            else "- Blocker: formal Q-B evaluation remains fail-closed."
        ),
        f"- Next command: `{payload['next_command']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--local-test-receipt", type=Path)
    parser.add_argument("--physical-receipt", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "reports/m2c-s4-entry-gate.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=PROJECT / "reports/m2c-s4-entry-gate.md",
    )
    args = parser.parse_args()
    result = evaluate_s4_entry_gate(
        args.project_root,
        local_receipt_path=args.local_test_receipt,
        physical_receipt_path=args.physical_receipt,
    )
    _write_json(args.output, result)
    _write_markdown(args.output_md, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["formal_q_b_evaluation_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
