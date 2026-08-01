#!/usr/bin/env python3
"""Require consistent formal held-out MLP-vs-zero results across seeds."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any


METRICS = ("mae", "rmse", "mean_l1_per_chunk")


def summarize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[str] = []
    if len(reports) < 2:
        findings.append("at least two seed reports are required")
    schemas = {report.get("schema_version") for report in reports}
    if schemas != {"M2BMaskedResidualMLPReportV1"}:
        findings.append(f"unexpected report schemas: {sorted(map(str, schemas))}")
    seeds = [report.get("seed") for report in reports]
    if len(set(seeds)) != len(seeds):
        findings.append("training seeds are not distinct")
    dataset_hashes = {report.get("dataset_sha256") for report in reports}
    if len(dataset_hashes) != 1:
        findings.append("seed reports use different datasets")
    checkpoint_hashes = [report.get("checkpoint_sha256") for report in reports]
    if any(not isinstance(digest, str) or len(digest) != 64 for digest in checkpoint_hashes):
        findings.append("every seed report must bind a SHA-256 checkpoint hash")
    elif len(set(checkpoint_hashes)) != len(checkpoint_hashes):
        findings.append("training seeds produced duplicate checkpoint hashes")
    eval_splits = {report.get("eval_split") for report in reports}
    if len(eval_splits) != 1:
        findings.append("seed reports use different held-out splits")
    if any(report.get("failure_context") != "on" for report in reports):
        findings.append("formal residual reports must use FailureContext on")
    if any(report.get("teacher_used") is not False for report in reports):
        findings.append("no-Teacher boundary is missing")
    if any(report.get("privileged_truth_policy_input") is not False for report in reports):
        findings.append("privileged truth entered policy input")
    if any(
        not report.get("validation", {}).get("formal_evaluation_ready", False) for report in reports
    ):
        findings.append("at least one seed report is not a formal held-out evaluation")
    for report in reports:
        for group in ("model_metrics", "zero_residual_baseline"):
            for metric in METRICS:
                value = report.get(group, {}).get(metric)
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    findings.append(f"seed {report.get('seed')}: {group}.{metric} is not finite")
    formal = not findings
    all_beat_zero = bool(
        reports and all(report.get("beats_zero_residual") is True for report in reports)
    )
    supported = formal and all_beat_zero
    aggregate = {
        metric: {
            "model_mean": mean(float(report["model_metrics"][metric]) for report in reports)
            if reports
            else None,
            "zero_mean": mean(float(report["zero_residual_baseline"][metric]) for report in reports)
            if reports
            else None,
            "model_minus_zero_mean": mean(
                float(report["model_metrics"][metric])
                - float(report["zero_residual_baseline"][metric])
                for report in reports
            )
            if reports
            else None,
        }
        for metric in METRICS
    }
    return {
        "schema_version": "M2BResidualMLPTwoSeedSummaryV1",
        "status": (
            "PASS_FORMAL_TWO_SEED_MLP_BEATS_ZERO"
            if supported
            else "FAIL_FORMAL_MLP_NOT_CONSISTENTLY_BETTER"
            if formal
            else "NOT_FORMAL"
        ),
        "seeds": seeds,
        "reports": len(reports),
        "dataset_sha256": next(iter(dataset_hashes), None),
        "eval_split": next(iter(eval_splits), None),
        "per_seed_beats_zero": {
            str(report.get("seed")): report.get("beats_zero_residual") for report in reports
        },
        "checkpoint_sha256_by_seed": {
            str(report.get("seed")): report.get("checkpoint_sha256") for report in reports
        },
        "aggregate_metrics": aggregate,
        "formal_two_seed_evaluation": formal,
        "mlp_residual_supported_offline": supported,
        "findings": sorted(set(findings)),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "world_model_replaced": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-report", action="append", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    reports = [json.loads(path.read_text()) for path in args.seed_report]
    report = summarize(reports)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["formal_two_seed_evaluation"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
