#!/usr/bin/env python3
"""Summarize post-execution Isaac gate receipts without model attribution."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from m2b.build_dataset_v2 import (
        evidence_from_worker_status,
        remote_sha256,
        sources_from_manifest,
    )
    from m2b.build_failure_evidence_pilot import remote_json
except ModuleNotFoundError:
    from build_dataset_v2 import (
        evidence_from_worker_status,
        remote_sha256,
        sources_from_manifest,
    )
    from build_failure_evidence_pilot import remote_json

from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    extract_physical_runtime_gate_receipt,
)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passing = [row for row in rows if row["receipt"]["complete_and_passing"]]
    counts = Counter(row["receipt"]["failure_type"] for row in rows)
    passing_counts = Counter(
        row["receipt"]["failure_type"] for row in passing
    )
    return {
        "schema_version": "M2BPhysicalRuntimeGateReportV1",
        "status": (
            "PASS_PHYSICAL_POST_EXECUTION_RECEIPTS_NOT_FORMAL_MAPPING"
            if passing
            else "NOT_READY_PHYSICAL_POST_EXECUTION_RECEIPTS"
        ),
        "receipts_valid": len(rows),
        "receipts_complete_and_passing": len(passing),
        "post_execution_gate_rate": len(passing) / len(rows) if rows else None,
        "counts_by_failure": dict(sorted(counts.items())),
        "passing_counts_by_failure": dict(sorted(passing_counts.items())),
        "model_selected_decisions": 0,
        "runtime_mapping_rate": None,
        "prospective_planning_checks_complete": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "limitations": [
            "Receipts are post-execution B0 monitors, not model-selected decisions.",
            "The post-execution rate is not the formal >=95% runtime mapping rate.",
            "Prospective per-decision IK, collision, and safety checks remain required.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--required-probe-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    host, evidence, statuses = sources_from_manifest(args.source_manifest)
    if not host:
        raise SystemExit("source manifest must declare a remote host")
    for status in statuses:
        evidence.extend(evidence_from_worker_status(host, status))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for failure_type, path in evidence:
        digest = remote_sha256(host, path)
        if digest in seen:
            continue
        seen.add(digest)
        payload = remote_json(host, path)
        if payload.get("actuation_probe_source_sha256") != args.required_probe_sha256:
            continue
        receipt = extract_physical_runtime_gate_receipt(
            payload, failure_type=failure_type
        )
        receipt_json = receipt.model_dump(mode="json")
        receipt_json["complete_and_passing"] = receipt.complete_and_passing
        rows.append(
            {
                "evidence": path,
                "evidence_sha256": digest,
                "actuation_probe_source_sha256": args.required_probe_sha256,
                "receipt": receipt_json,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    report = summarize(rows)
    report.update(
        {
            "required_probe_sha256": args.required_probe_sha256,
            "output": str(args.output),
            "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
