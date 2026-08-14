#!/usr/bin/env python3
"""Record the ADR-0026 cancellation boundary for partially started Batch 24."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth


ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = "docs/decisions/ADR-0026-m2c-terminal-step-diagnosis.md"
ADR_SHA256 = "ba24b65435b19b3a7700bb7caba83a01d98897a8999aee54af5c2370d410c180"
PREREG_PATH = "docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-24-PREREG.json"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Batch24 cancellation evidence contains unsafe path")
        raw = v4_auth.read_regular_file_once(path)
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(raw),
                "sha256": _sha(raw),
            }
        )
    return entries


def audit(*, project_root: Path, evidence_root: Path) -> dict[str, Any]:
    adr = v4_auth.read_regular_file_once(project_root / ADR_PATH)
    prereg_raw = v4_auth.read_regular_file_once(project_root / PREREG_PATH)
    prereg = json.loads(prereg_raw)
    if _sha(adr) != ADR_SHA256 or prereg.get("batch_id") != "m2c-s4-v4-train-batch-24":
        raise RuntimeError("Batch24 cancellation governance binding changed")
    selected = prereg.get("selected_keys")
    if not isinstance(selected, list) or len(selected) != 3:
        raise RuntimeError("Batch24 preregistration no longer has exactly three keys")
    inventory = _inventory(evidence_root)
    names = {item["path"] for item in inventory}
    claims = [item for item in inventory if item["path"].startswith("ledger/claim-")]
    if len(claims) != 1:
        raise RuntimeError("Batch24 cancellation must preserve exactly one consumed claim")
    claim_path = evidence_root / claims[0]["path"]
    claim = v4_auth.M2CS4V4CollectionConsumptionReceiptV1.model_validate_json(
        v4_auth.read_regular_file_once(claim_path)
    )
    first_key = selected[0]
    if (
        claim.selected_key.matched_key != first_key["matched_key"]
        or claim.selected_key.scene_seed != first_key["scene_seed"]
        or claim.selected_key.failure_seed != first_key["failure_seed"]
    ):
        raise RuntimeError("Batch24 cancellation claim is not the first selected key")
    forbidden = {
        path
        for path in names
        if path.endswith("actuation-probe.json")
        or "packaged" in path
        or path.endswith("terminal-receipt.json")
    }
    if forbidden:
        raise RuntimeError("Batch24 cancellation evidence unexpectedly contains an outcome")
    for other in selected[1:]:
        if any(other["matched_key"] in path for path in names):
            raise RuntimeError("an unrun Batch24 key appears in cancellation evidence")
    core: dict[str, Any] = {
        "schema_version": "M2CS4V4Batch24CancellationAuditV1",
        "status": "CANCELLED_BY_ADR0026_NO_OUTCOME",
        "governing_adr": {"path": ADR_PATH, "sha256": ADR_SHA256},
        "batch24_prereg": {"path": PREREG_PATH, "sha256": _sha(prereg_raw)},
        "consumed_keys": [first_key["matched_key"]],
        "unrun_keys": [item["matched_key"] for item in selected[1:]],
        "consumed_claim": {
            "path": claims[0]["path"],
            "sha256": claims[0]["sha256"],
            "consumption_id": claim.consumption_id,
            "consumed_at_ns": claim.consumed_at_ns,
        },
        "actuation_probe_present": False,
        "terminal_outcome_recorded": False,
        "training_sample_count": 0,
        "failure_count_increment": 0,
        "physical_execution_state": "UNKNOWN_NO_TERMINAL_RAW_RECEIPT",
        "selection_or_replacement_authorized": False,
        "evidence_inventory": inventory,
        "evidence_inventory_sha256": v4_auth.canonical_sha256(inventory),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    core["report_content_sha256"] = v4_auth.canonical_sha256(core)
    return core


def _write(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise RuntimeError("short Batch24 cancellation audit write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    report = audit(
        project_root=args.project_root.resolve(strict=True),
        evidence_root=args.evidence_root.resolve(strict=True),
    )
    _write(
        args.output_json,
        (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )
    markdown = (
        "# M2C S4 V4 Batch 24 cancellation\n\n"
        f"- Status: `{report['status']}`\n"
        f"- Consumed key: `{report['consumed_keys'][0]}`\n"
        f"- Unrun keys: `{', '.join(report['unrun_keys'])}`\n"
        "- Raw terminal outcome: `absent`\n"
        "- Training/failure increment: `0/0`\n"
        "- Physical execution state: `UNKNOWN_NO_TERMINAL_RAW_RECEIPT`\n"
        "- Teacher/privileged truth policy input: `false/false`\n"
    )
    _write(args.output_md, markdown.encode())
    print(json.dumps({"status": report["status"], "files": len(report["evidence_inventory"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
