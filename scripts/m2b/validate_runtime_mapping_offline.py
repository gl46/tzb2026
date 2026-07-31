#!/usr/bin/env python3
"""Validate held-out QRM outputs against the M2B runtime registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.contracts import QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.models_q012 import load_formal_checkpoint
from xh_agent.policy.qrm_lite.runtime_adapter import (
    build_runtime_skill_request,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    load_registry,
    validate_runtime_mapping,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_samples(path: Path, split: str) -> list[QRMTrainingSampleV1]:
    return [
        sample
        for line in path.read_text().splitlines()
        if line.strip()
        for sample in [QRMTrainingSampleV1.model_validate_json(line)]
        if sample.split == split
    ]


def evaluate(
    samples: list[QRMTrainingSampleV1],
    *,
    checkpoint: Path,
    registry_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    model = load_formal_checkpoint(str(checkpoint))
    registry = load_registry(registry_path)
    records = []
    for sample in samples:
        nominal = np.asarray(sample.nominal_action_chunk.values)
        output = model.predict(
            sample.observation,
            nominal=nominal if model.uses_residual else None,
            moveit_accept_fn=lambda _chunk: (
                False,
                "OFFLINE_RESIDUAL_EXECUTION_NOT_AUTHORIZED",
            ),
        )
        # QRM-Real-V1 predates TaskSpec.track_id in QRMObservationV1.  Its
        # public FailureContext retains the last public target track; this is
        # used as the legacy TaskSpec surrogate.  No held-out intent label or
        # simulator entity identity participates in mapping.
        task_target_track_id = (
            sample.observation.failure_context.last_target_track_id
        )
        request = build_runtime_skill_request(
            sample.observation,
            output,
            registry,
            task_target_track_id=task_target_track_id,
        )
        result = validate_runtime_mapping(request, registry)
        records.append(
            {
                "sample_id": sample.sample_id,
                "episode_id": sample.episode_id,
                "split": sample.split,
                "model_id": output.model_id.value,
                "checkpoint_revision": model.meta_checkpoint_revision,
                "predicted_coarse_skill": output.coarse.skill_type,
                "predicted_recovery_skill": output.recovery_skill,
                "failure_type": (
                    sample.observation.failure_context.failure_type.value
                ),
                "task_target_track_source": (
                    "PUBLIC_FAILURE_CONTEXT_LAST_TARGET"
                ),
                "request": request.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            }
        )
    valid = [row for row in records if row["result"]["status"] == "VALID"]
    rejection_histogram = Counter(
        row["result"]["rejection_reason"]
        for row in records
        if row["result"]["status"] == "REJECTED"
    )
    predicted_skills = Counter(
        row["request"]["skill"] for row in records
    )
    report = {
        "schema_version": "M2BRuntimeMappingOfflineV1",
        "status": (
            "PASS_STRUCTURAL_MAPPING_PLANNING_DRY_RUN_PENDING"
            if records and len(valid) / len(records) >= 0.95
            else "FAIL_STRUCTURAL_MAPPING"
        ),
        "heldout_model_outputs": len(records),
        "structurally_valid": len(valid),
        "structural_mapping_rate": (
            len(valid) / len(records) if records else None
        ),
        "runtime_mapping_rate": None,
        "planning_checks_complete": False,
        "planning_gate_status": {
            "ik": "NOT_RUN",
            "collision": "NOT_RUN",
            "safety": "NOT_RUN",
        },
        "rejection_reason_histogram": dict(sorted(rejection_histogram.items())),
        "predicted_runtime_skill_histogram": dict(sorted(predicted_skills.items())),
        "checkpoint_revision": getattr(
            model, "meta_checkpoint_revision", "UNKNOWN"
        ),
        "target_track_source": "PUBLIC_FAILURE_CONTEXT_LAST_TARGET",
        "privileged_truth_policy_input": False,
        "teacher_used": False,
        "limitations": [
            "This is a structural mapping gate over held-out model outputs.",
            "IK, collision, controller, and safety dry-runs require Isaac scene execution before runtime_mapping_rate may be populated.",
            "The frozen M2A model is evaluated for integration only; it is not an M2B performance claim.",
        ],
    }
    return records, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    samples = load_samples(args.dataset, args.split)
    if not samples:
        raise SystemExit(f"no samples found for split {args.split!r}")
    records, report = evaluate(
        samples,
        checkpoint=args.checkpoint,
        registry_path=args.registry,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records)
    )
    report.update(
        {
            "dataset": str(args.dataset),
            "dataset_sha256": sha256_file(args.dataset),
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": sha256_file(args.checkpoint),
            "registry": str(args.registry),
            "registry_sha256": sha256_file(args.registry),
            "model_outputs": str(args.output),
            "model_outputs_sha256": sha256_file(args.output),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
