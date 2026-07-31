#!/usr/bin/env python3
"""Reload a Qwen coarse adapter and validate held-out runtime mappings."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from xh_agent.policy.qrm_lite.coarse_inference import (
    QwenCoarseRecoveryPolicy,
)
from xh_agent.policy.qrm_lite.contracts import QRMCoarseTrainingSampleV2
from xh_agent.policy.qrm_lite.runtime_adapter import (
    build_runtime_skill_request,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    load_registry,
    validate_runtime_mapping,
)


def resolve_image(dataset_root: Path, uri: str) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported RGB URI: {uri}")
    relative = Path(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"RGB URI escapes dataset: {uri}")
    path = dataset_root / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_tree(path: Path) -> str:
    if not path.is_dir():
        raise ValueError(f"model adapter is not a directory: {path}")
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise ValueError(f"model adapter directory is empty: {path}")
    digest = hashlib.sha256()
    for item in files:
        if item.is_symlink():
            raise ValueError(f"model adapter contains a symlink: {item}")
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--split", choices=("val", "test"), default="val")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    samples = [
        sample
        for line in args.dataset.read_text().splitlines()
        if line.strip()
        for sample in [QRMCoarseTrainingSampleV2.model_validate_json(line)]
        if sample.split == args.split
    ]
    if not samples:
        raise SystemExit(f"no {args.split} samples")
    policy = QwenCoarseRecoveryPolicy(
        model_id=args.model_id,
        adapter_path=args.adapter,
        revision=args.revision,
    )
    registry = load_registry(args.registry)
    registry_sha256 = hashlib.sha256(args.registry.read_bytes()).hexdigest()
    checkpoint_sha256 = sha256_tree(args.adapter)
    records = []
    for sample in samples:
        assert sample.observation.rgb_uri is not None
        image_path = resolve_image(
            args.dataset_root, sample.observation.rgb_uri
        )
        image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
        model_input = {
            "observation": sample.observation.model_dump(mode="json"),
            "rgb_sha256": image_sha256,
        }
        prediction = policy.predict(
            sample.observation,
            image_path,
        )
        model_output = {
            "model_id": prediction.model_id,
            "coarse": prediction.coarse.model_dump(mode="json"),
            "recovery_skill": prediction.recovery_skill,
            "confidence": prediction.confidence,
            "probabilities": prediction.probabilities,
            "used_failure_context": prediction.used_failure_context,
        }
        request = build_runtime_skill_request(
            sample.observation,
            prediction,
            registry,
            task_target_track_id=sample.observation.task_target_track_id,
        )
        mapping = validate_runtime_mapping(request, registry)
        request_payload = request.model_dump(mode="json")
        mapping_payload = mapping.model_dump(mode="json")
        records.append(
            {
                "sample_id": sample.sample_id,
                "episode_id": sample.episode_id,
                "split": sample.split,
                "failure_type": (
                    sample.observation.failure_context.failure_type.value
                ),
                "truth_skill": sample.coarse_intent.skill_type,
                "predicted_skill": prediction.coarse.skill_type,
                "confidence": prediction.confidence,
                "used_failure_context": prediction.used_failure_context,
                "model_input": model_input,
                "model_output": model_output,
                "request": request_payload,
                "mapping": mapping_payload,
                "registry_sha256": registry_sha256,
                "model_checkpoint_sha256": checkpoint_sha256,
                "model_input_sha256": canonical_sha256(model_input),
                "model_output_sha256": canonical_sha256(model_output),
                "request_sha256": canonical_sha256(request_payload),
                "mapping_result_sha256": canonical_sha256(
                    mapping_payload
                ),
            }
        )
    valid = [record for record in records if record["mapping"]["status"] == "VALID"]
    correct = [
        record
        for record in records
        if record["truth_skill"] == record["predicted_skill"]
    ]
    rejections = Counter(
        record["mapping"]["rejection_reason"]
        for record in records
        if record["mapping"]["status"] == "REJECTED"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    )
    report = {
        "schema_version": "M2BQwenCoarseAdapterHeldoutV1",
        "status": (
            "PASS_ADAPTER_RELOAD_STRUCTURAL_MAPPING"
            if len(valid) / len(records) >= 0.95
            else "FAIL_STRUCTURAL_MAPPING"
        ),
        "split": args.split,
        "samples": len(records),
        "skill_accuracy": len(correct) / len(records),
        "structurally_valid": len(valid),
        "structural_mapping_rate": len(valid) / len(records),
        "runtime_mapping_rate": None,
        "planning_checks_complete": False,
        "planning_gate_status": {
            "ik": "NOT_RUN",
            "collision": "NOT_RUN",
            "safety": "NOT_RUN",
        },
        "rejection_reason_histogram": dict(sorted(rejections.items())),
        "failure_context": (
            "on" if policy.use_failure_context else "off"
        ),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "registry_sha256": registry_sha256,
        "model_checkpoint_sha256": checkpoint_sha256,
        "adapter": str(args.adapter),
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "limitations": [
            "This reload gate validates held-out model inference and structural mapping only.",
            "IK, collision, safety, and physical execution remain NOT_RUN.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
