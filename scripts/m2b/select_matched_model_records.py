#!/usr/bin/env python3
"""Select matched NoFC/FC model records without metric-based cherry-picking."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from m2b.build_prospective_runtime_decisions import validate_model_record
from xh_agent.policy.qrm_lite.skill_registry import load_registry


FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")


def load_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def indexed(records: list[dict[str, Any]], *, label: str) -> dict[str, dict[str, Any]]:
    result = {str(record["sample_id"]): record for record in records}
    if len(result) != len(records):
        raise ValueError(f"{label} contains duplicate sample_id")
    return result


def select_matched(
    no_fc: list[dict[str, Any]],
    fc: list[dict[str, Any]],
    *,
    quotas: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if set(quotas) != set(FAILURES) or any(value <= 0 for value in quotas.values()):
        raise ValueError("selection requires a positive quota for every failure type")
    if sum(quotas.values()) < 20:
        raise ValueError("formal matched selection requires at least 20 samples")
    no_fc_by_id = indexed(no_fc, label="NoFC records")
    fc_by_id = indexed(fc, label="FC records")
    if set(no_fc_by_id) != set(fc_by_id):
        raise ValueError("NoFC and FC sample sets differ")
    candidates: dict[str, list[str]] = {failure: [] for failure in FAILURES}
    for sample_id in sorted(no_fc_by_id):
        left = no_fc_by_id[sample_id]
        right = fc_by_id[sample_id]
        for field in ("episode_id", "failure_type", "split", "registry_sha256"):
            if left.get(field) != right.get(field):
                raise ValueError(f"{sample_id}: matched {field} differs")
        failure = str(left["failure_type"])
        if failure not in candidates:
            raise ValueError(f"{sample_id}: unsupported failure type {failure}")
        candidates[failure].append(sample_id)
    selected_ids = []
    for failure in FAILURES:
        available = candidates[failure]
        if len(available) < quotas[failure]:
            raise ValueError(
                f"{failure}: only {len(available)} matched samples; need {quotas[failure]}"
            )
        selected_ids.extend(available[: quotas[failure]])
    selected_ids.sort()
    return (
        [no_fc_by_id[sample_id] for sample_id in selected_ids],
        [fc_by_id[sample_id] for sample_id in selected_ids],
    )


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_quota(items: list[str]) -> dict[str, int]:
    quotas = {}
    for item in items:
        failure, raw = item.split("=", 1)
        if failure in quotas:
            raise ValueError(f"duplicate quota for {failure}")
        quotas[failure] = int(raw)
    return quotas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fc", required=True, type=Path)
    parser.add_argument("--fc", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--quota", action="append", required=True)
    parser.add_argument("--no-fc-output", required=True, type=Path)
    parser.add_argument("--fc-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    no_fc = load_records(args.no_fc)
    fc = load_records(args.fc)
    registry = load_registry(args.registry)
    registry_sha256 = hashlib.sha256(args.registry.read_bytes()).hexdigest()
    for records in (no_fc, fc):
        for record in records:
            validate_model_record(
                record,
                registry=registry,
                registry_sha256=registry_sha256,
            )
    no_fc_checkpoints = {str(record["model_checkpoint_sha256"]) for record in no_fc}
    fc_checkpoints = {str(record["model_checkpoint_sha256"]) for record in fc}
    if len(no_fc_checkpoints) != 1 or len(fc_checkpoints) != 1:
        raise ValueError("each model-record input must contain one checkpoint")
    if no_fc_checkpoints == fc_checkpoints:
        raise ValueError("NoFC and FC records use the same checkpoint")
    if any(record.get("used_failure_context") is not False for record in no_fc):
        raise ValueError("NoFC input contains a FailureContext-enabled record")
    if any(record.get("used_failure_context") is not True for record in fc):
        raise ValueError("FC input contains a FailureContext-disabled record")
    quotas = parse_quota(args.quota)
    selected_no_fc, selected_fc = select_matched(no_fc, fc, quotas=quotas)
    no_fc_sha256 = write_jsonl(args.no_fc_output, selected_no_fc)
    fc_sha256 = write_jsonl(args.fc_output, selected_fc)
    counts = Counter(str(record["failure_type"]) for record in selected_fc)
    report = {
        "schema_version": "M2BMatchedModelRecordSelectionV1",
        "status": "PASS_MATCHED_MODEL_RECORDS_SELECTED",
        "selection_policy": "LEXICOGRAPHIC_SAMPLE_ID_WITHIN_FAILURE_TYPE_NO_METRIC_SELECTION",
        "selected_samples": len(selected_fc),
        "counts_by_failure": dict(sorted(counts.items())),
        "quotas": dict(sorted(quotas.items())),
        "sample_ids": [str(record["sample_id"]) for record in selected_fc],
        "registry_sha256": registry_sha256,
        "no_fc_checkpoint_sha256": next(iter(no_fc_checkpoints)),
        "fc_checkpoint_sha256": next(iter(fc_checkpoints)),
        "no_fc_output": str(args.no_fc_output),
        "no_fc_output_sha256": no_fc_sha256,
        "fc_output": str(args.fc_output),
        "fc_output_sha256": fc_sha256,
        "metric_based_selection": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
