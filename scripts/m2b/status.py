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
    parser.add_argument("--output", type=Path, default=PROJECT / "reports/m2b-status.json")
    args = parser.parse_args()
    freeze = load_optional(args.report_dir / "m2b-s0-m2a-freeze.json")
    physical = load_optional(args.report_dir / "m2b-s1-physical-failure-smoke.json")
    mapping = load_optional(args.report_dir / "m2b-s0-runtime-mapping-audit.json")
    mapping_offline = load_optional(args.report_dir / "m2b-s5-runtime-mapping-offline.json")
    physical_runtime_gates = load_optional(args.report_dir / "m2b-s5-physical-runtime-gates.json")
    dataset = load_optional(args.report_dir / "m2b-s2-dataset-v2.json")
    evidence_pilot = load_optional(args.report_dir / "m2b-s2-failure-evidence-pilot.json")
    residual = load_optional(args.report_dir / "m2b-s3-residual-pairs.json")
    residual_pilot = load_optional(args.report_dir / "m2b-s3-residual-pairs-pilot.json")
    training = load_optional(args.report_dir / "m2b-s4-training.json")
    residual_training = load_optional(args.report_dir / "m2b-s4-residual-mlp.json")
    closed_loop = load_optional(args.report_dir / "m2b-s5-closed-loop.json")
    blockers = []
    physical_ready = bool(
        physical and physical.get("status") == "PASS_PUBLIC_FAILURES_AND_RECOVERIES"
    )
    if not physical_ready:
        blockers.append("three public+physical failure/recovery chains are incomplete")
    failure_counts = dataset.get("failure_counts", {}) if dataset else {}
    recovery_counts = dataset.get("successful_recovery_counts", {}) if dataset else {}
    dataset_ready = bool(
        dataset
        and dataset.get("limited_coverage_gate_passed") is True
        and int(dataset.get("episodes_quarantined", 0)) == 0
        and all(
            int(failure_counts.get(failure, 0)) >= 50 and int(recovery_counts.get(failure, 0)) >= 25
            for failure in (
                "EMPTY_GRASP",
                "WRONG_OBJECT",
                "RELEASE_FAILURE",
            )
        )
    )
    if not dataset_ready:
        blockers.append("Dataset V2 has not met the limited-scale 50/class minimum")
    residual_ready = bool(
        residual
        and int(residual.get("valid_pairs", 0)) >= 50
        and residual.get("status") == "PASS_INFORMATIVE_RESIDUAL_TARGETS"
    )
    if not residual_ready:
        blockers.append("at least 50 informative physical residual pairs are not packaged")
    mapping_ready = bool(
        mapping_offline
        and mapping_offline.get("runtime_mapping_rate") is not None
        and float(mapping_offline["runtime_mapping_rate"]) >= 0.95
        and mapping_offline.get("planning_checks_complete") is True
        and mapping_offline.get("formal_mapping_ready") is True
    )
    if not mapping_ready:
        blockers.append("runtime mapping still requires Isaac IK/collision/safety dry-runs")
    training_ready = bool(
        training
        and training.get("status") == "PASS_ABLATION_COMPLETE"
        and training.get("formal_ablation") is True
    )
    if not training_ready:
        blockers.append("two-seed A100 NoFC/FC training has not run")
    residual_training_ready = bool(
        residual_training and residual_training.get("formal_two_seed_evaluation") is True
    )
    if not residual_training_ready:
        blockers.append("two-seed A100 residual MLP-vs-zero evaluation has not run")
    closed_loop_ready = bool(
        closed_loop
        and closed_loop.get("status") == "PASS_FORMAL_MATCHED_EVALUATION_COMPLETE"
        and closed_loop.get("formal_evaluation_ready") is True
        and int(closed_loop.get("qrm_model_decisions_executed", 0)) >= 20
    )
    if not closed_loop_ready:
        blockers.append("matched B0/QRM Isaac closed-loop evaluation has not run")
    if not physical_ready or not dataset_ready:
        next_command = "make m2b-generate-failures"
    elif not residual_ready:
        next_command = "make m2b-generate-residuals"
    elif not training_ready or not residual_training_ready:
        next_command = "make m2b-train"
    elif not mapping_ready:
        next_command = "make m2b-map-validate"
    elif not closed_loop_ready:
        next_command = "make m2b-run-matched-closed-loop"
    else:
        next_command = "make m2b-status"
    status = {
        "schema_version": "M2BStatusV1",
        "goal_complete": not blockers,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "world_model_mainline_replaced": False,
        "m2a_freeze_status": freeze.get("status") if freeze else "MISSING",
        "physical_failure_recovery_status": (physical.get("status") if physical else "MISSING"),
        "physical_failure_classes": (physical.get("accepted_failures", []) if physical else []),
        "dataset_v2_episodes_valid": (int(dataset.get("episodes_valid", 0)) if dataset else 0),
        "dataset_v2_failure_counts": failure_counts,
        "dataset_v2_successful_recovery_counts": recovery_counts,
        "failure_evidence_pilot_records": (
            int(evidence_pilot.get("records_valid", 0)) if evidence_pilot else 0
        ),
        "residual_pairs_valid": (int(residual.get("valid_pairs", 0)) if residual else 0),
        "residual_pilot_status": (residual_pilot.get("status") if residual_pilot else "NOT_RUN"),
        "residual_pilot_pairs": (
            int(residual_pilot.get("valid_pairs", 0)) if residual_pilot else 0
        ),
        "runtime_mapping_baseline_status": (mapping.get("status") if mapping else "MISSING"),
        "runtime_mapping_offline_status": (
            mapping_offline.get("status") if mapping_offline else "NOT_RUN"
        ),
        "runtime_structural_mapping_rate": (
            mapping_offline.get("structural_mapping_rate") if mapping_offline else None
        ),
        "runtime_mapping_rate": (
            mapping_offline.get("runtime_mapping_rate") if mapping_offline else None
        ),
        "physical_runtime_gate_status": (
            physical_runtime_gates.get("status") if physical_runtime_gates else "NOT_RUN"
        ),
        "physical_runtime_receipts_complete_and_passing": (
            int(physical_runtime_gates.get("receipts_complete_and_passing", 0))
            if physical_runtime_gates
            else 0
        ),
        "physical_runtime_post_execution_gate_rate": (
            physical_runtime_gates.get("post_execution_gate_rate")
            if physical_runtime_gates
            else None
        ),
        "prospective_runtime_planning_checks_complete": bool(
            physical_runtime_gates
            and physical_runtime_gates.get("prospective_planning_checks_complete")
        ),
        "training_status": training.get("status") if training else "NOT_RUN",
        "residual_mlp_status": (
            residual_training.get("status") if residual_training else "NOT_RUN"
        ),
        "residual_mlp_supported_offline": (
            residual_training.get("mlp_residual_supported_offline") if residual_training else None
        ),
        "closed_loop_status": (closed_loop.get("status") if closed_loop else "NOT_RUN"),
        "blockers": blockers,
        "next_command": next_command,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["goal_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
