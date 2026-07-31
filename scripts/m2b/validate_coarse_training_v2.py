#!/usr/bin/env python3
"""Gate M2B coarse-only data before formal paired A100 training."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from xh_agent.data_engine.isaac.contract import audit_policy_projection
from xh_agent.policy.qrm_lite.contracts import QRMCoarseTrainingSampleV2


EXPECTED_SKILLS = {
    "EMPTY_GRASP": "REOBSERVE",
    "WRONG_OBJECT": "SAFE_PLACE_NON_TARGET",
    "RELEASE_FAILURE": "RETRY_RELEASE",
}


def validate(path: Path) -> dict:
    samples = [
        QRMCoarseTrainingSampleV2.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    split_groups: dict[str, set[str]] = defaultdict(set)
    findings = []
    for sample in samples:
        failure = sample.observation.failure_context.failure_type.value
        counts[sample.split][failure] += 1
        group = sample.provenance.get("split_group", "")
        if not group:
            findings.append(f"{sample.sample_id}: split_group missing")
        split_groups[group].add(sample.split)
        expected = EXPECTED_SKILLS.get(failure)
        if sample.coarse_intent.skill_type != expected:
            findings.append(
                f"{sample.sample_id}: {failure} label is not {expected}"
            )
        if sample.continuous_action_target_available is not False:
            findings.append(
                f"{sample.sample_id}: continuous action target was fabricated"
            )
        findings.extend(
            f"{sample.sample_id}: {finding}"
            for finding in audit_policy_projection(
                sample.observation.model_dump(mode="json")
            )
        )
    leakage = sorted(
        group for group, splits in split_groups.items() if len(splits) > 1
    )
    if leakage:
        findings.append(f"split group leakage: {leakage}")
    total_counts = Counter(
        failure
        for sample in samples
        for failure in [
            sample.observation.failure_context.failure_type.value
        ]
    )
    limited_coverage = all(
        total_counts[failure] >= 50 for failure in EXPECTED_SKILLS
    )
    train_coverage = all(
        counts["train"][failure] >= 30 for failure in EXPECTED_SKILLS
    )
    eval_coverage = any(
        all(counts[split][failure] >= 3 for failure in EXPECTED_SKILLS)
        for split in ("val", "test")
    )
    formal_ready = bool(
        samples
        and not findings
        and limited_coverage
        and train_coverage
        and eval_coverage
    )
    return {
        "schema_version": "M2BCoarseTrainingDataGateV1",
        "status": "PASS_FORMAL_TRAINING_READY" if formal_ready else "NOT_READY",
        "samples": len(samples),
        "counts_by_split": {
            split: dict(sorted(split_counts.items()))
            for split, split_counts in sorted(counts.items())
        },
        "total_failure_counts": {
            failure: total_counts[failure] for failure in EXPECTED_SKILLS
        },
        "limited_failure_coverage": limited_coverage,
        "train_coverage": train_coverage,
        "eval_coverage": eval_coverage,
        "split_group_leakage": leakage,
        "findings": sorted(set(findings)),
        "continuous_action_targets": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "formal_training_ready": formal_ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = validate(args.dataset)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["formal_training_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
