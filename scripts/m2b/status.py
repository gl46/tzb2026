#!/usr/bin/env python3
"""Report evidence-backed progress for the active M2B goal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]


def load_optional(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=PROJECT / "reports")
    parser.add_argument(
        "--output", type=Path, default=PROJECT / "reports/m2b-status.json"
    )
    args = parser.parse_args()
    freeze = load_optional(args.report_dir / "m2b-s0-m2a-freeze.json")
    physical = load_optional(
        args.report_dir / "m2b-s1-physical-failure-smoke.json"
    )
    mapping = load_optional(
        args.report_dir / "m2b-s0-runtime-mapping-audit.json"
    )
    dataset = load_optional(args.report_dir / "m2b-s2-dataset-v2.json")
    evidence_pilot = load_optional(
        args.report_dir / "m2b-s2-failure-evidence-pilot.json"
    )
    residual = load_optional(args.report_dir / "m2b-s3-residual-pairs.json")
    residual_pilot = load_optional(
        args.report_dir / "m2b-s3-residual-pairs-pilot.json"
    )
    training = load_optional(args.report_dir / "m2b-s4-training.json")
    closed_loop = load_optional(args.report_dir / "m2b-s5-closed-loop.json")
    blockers = []
    if not physical or physical.get("status") != "PASS_PUBLIC_FAILURES_AND_RECOVERIES":
        blockers.append("three public+physical failure/recovery chains are incomplete")
    if not dataset or int(dataset.get("episodes_valid", 0)) < 150:
        blockers.append("Dataset V2 has not met the limited-scale 50/class minimum")
    if not residual or int(residual.get("valid_pairs", 0)) <= 0:
        blockers.append("nondegenerate successful residual pairs are not packaged")
    if not training:
        blockers.append("two-seed A100 NoFC/FC training has not run")
    if not closed_loop:
        blockers.append("matched B0/QRM Isaac closed-loop evaluation has not run")
    status = {
        "schema_version": "M2BStatusV1",
        "goal_complete": not blockers,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "world_model_mainline_replaced": False,
        "m2a_freeze_status": freeze.get("status") if freeze else "MISSING",
        "physical_failure_recovery_status": (
            physical.get("status") if physical else "MISSING"
        ),
        "physical_failure_classes": (
            physical.get("accepted_failures", []) if physical else []
        ),
        "dataset_v2_episodes_valid": (
            int(dataset.get("episodes_valid", 0)) if dataset else 0
        ),
        "failure_evidence_pilot_records": (
            int(evidence_pilot.get("records_valid", 0))
            if evidence_pilot
            else 0
        ),
        "residual_pairs_valid": (
            int(residual.get("valid_pairs", 0)) if residual else 0
        ),
        "residual_pilot_status": (
            residual_pilot.get("status") if residual_pilot else "NOT_RUN"
        ),
        "residual_pilot_pairs": (
            int(residual_pilot.get("valid_pairs", 0))
            if residual_pilot
            else 0
        ),
        "runtime_mapping_baseline_status": (
            mapping.get("status") if mapping else "MISSING"
        ),
        "training_status": training.get("status") if training else "NOT_RUN",
        "closed_loop_status": (
            closed_loop.get("status") if closed_loop else "NOT_RUN"
        ),
        "blockers": blockers,
        "next_command": "make m2b-generate-failures",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["goal_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
