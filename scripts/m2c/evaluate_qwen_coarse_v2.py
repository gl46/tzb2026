#!/usr/bin/env python3
"""Reload and offline-evaluate M2C Qwen skill/pointer/destination heads.

This entry point is not the Q-B physical evaluation.  It performs public-only
inference and structural V2 runtime mapping; all physical gates remain NOT_RUN.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from PIL import Image

from m2c.train_qwen_coarse_v2 import (
    _model_cache_report,
    _resolve_local_revision_snapshot,
)

try:
    from m2c.qwen_coarse_v2 import (
        DESTINATION_LABELS,
        POINTER_LABELS,
        SKILL_LABELS,
        classification_metrics,
        canonical_slots_for_sample,
        index_executed_histories,
        load_bundle,
        load_training_dataset,
        qwen_coarse_v2_prompt,
        resolve_dataset_asset,
        runtime_observation_for_sample,
        sha256_file,
    )
except ModuleNotFoundError as error:
    if error.name != "m2c":
        raise
    from qwen_coarse_v2 import (  # type: ignore[no-redef]
        DESTINATION_LABELS,
        POINTER_LABELS,
        SKILL_LABELS,
        classification_metrics,
        canonical_slots_for_sample,
        index_executed_histories,
        load_bundle,
        load_training_dataset,
        qwen_coarse_v2_prompt,
        resolve_dataset_asset,
        runtime_observation_for_sample,
        sha256_file,
    )
from xh_agent.policy.qrm_lite.backbone import (
    DEFAULT_MODEL_ID,
    DEFAULT_REVISION,
    Qwen35Backbone,
)
from xh_agent.policy.qrm_lite.contracts import CoarseIntentV2
from xh_agent.policy.qrm_lite.runtime_adapter_v2 import (
    build_runtime_skill_request_v2,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    load_registry_v2,
    validate_runtime_mapping_v2,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline reload/eval for M2C Qwen CoarseIntentV2",
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--dataset-manifest", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--training-keys", required=True, type=Path)
    parser.add_argument("--evaluation-keys", required=True, type=Path)
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--split", choices=("train",), default="train")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--device", default="cuda")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if args.model_id != DEFAULT_MODEL_ID:
        raise ValueError(
            "offline evaluation requires the canonical Qwen model ID; local "
            "paths may only be supplied as --cache-dir"
        )
    if args.revision != DEFAULT_REVISION:
        raise ValueError("offline evaluation requires the canonical Qwen revision")
    if not args.local_files_only:
        raise ValueError("offline evaluation must be local-files-only")
    if not args.cache_dir.is_dir():
        raise ValueError("offline Qwen cache directory does not exist")


def _build_backbone(args: argparse.Namespace) -> Qwen35Backbone:
    return Qwen35Backbone(
        model_id=args.model_id,
        revision=args.revision,
        device=args.device,
        dtype="bfloat16",
        cache_dir=str(args.cache_dir.resolve()),
        local_files_only=True,
    )


def _softmax(values: np.ndarray) -> list[float]:
    finite = np.isfinite(values)
    maximum = np.max(values[finite])
    exponent = np.zeros_like(values)
    exponent[finite] = np.exp(values[finite] - maximum)
    return (exponent / exponent.sum()).tolist()


def coarse_intent_from_prediction(
    *,
    skill_index: int,
    target_track_id: str | None,
    destination_cell: str | None,
) -> CoarseIntentV2:
    """Decode the three heads without leaving required grasp semantics implicit."""

    skill = SKILL_LABELS[skill_index]
    return CoarseIntentV2(
        skill_type=skill,
        target_track_id=target_track_id,
        destination_cell=destination_cell,
        grasp_family=("top_down" if skill in {"GRASP", "REGRASP"} else "unknown"),
        reobserve_flag=skill == "REOBSERVE",
        failure_type_aux="PATH_BLOCKED",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_args(args)
    for path in (args.output, args.report):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite offline eval output: {path}")
    _resolve_local_revision_snapshot(args.cache_dir)
    samples, dataset_report = load_training_dataset(
        args.dataset,
        dataset_manifest_path=args.dataset_manifest,
        training_manifest_path=args.training_keys,
        evaluation_manifest_path=args.evaluation_keys,
    )
    samples = [sample for sample in samples if sample.split == args.split]
    if not samples:
        raise ValueError(f"no eligible {args.split} samples")
    heads, metadata, bundle = load_bundle(
        args.bundle_root,
        require_adapter=True,
        expected_model_id=args.model_id,
        expected_model_revision=args.revision,
    )
    if metadata.dataset_sha256 != dataset_report.dataset_sha256:
        raise ValueError("bundle and evaluation dataset SHA-256 differ")
    if metadata.dataset_manifest_sha256 != dataset_report.dataset_manifest_sha256:
        raise ValueError("bundle and supervised dataset manifest SHA-256 differ")
    if metadata.training_manifest_sha256 != (
        dataset_report.key_manifest_audit.training_manifest_sha256
    ):
        raise ValueError("bundle and training-key manifest SHA-256 differ")
    if metadata.evaluation_manifest_sha256 != (
        dataset_report.key_manifest_audit.evaluation_manifest_sha256
    ):
        raise ValueError("bundle and S6-key manifest SHA-256 differ")
    registry = load_registry_v2(args.registry)
    backbone = _build_backbone(args)
    backbone.load_adapter(args.bundle_root / "adapter")
    records: list[dict[str, Any]] = []
    truth = {"skill": [], "pointer": [], "destination": []}
    predicted = {"skill": [], "pointer": [], "destination": []}
    use_fc = metadata.failure_context == "on"
    histories = index_executed_histories(samples)
    for sample in samples:
        rgb_path = resolve_dataset_asset(
            args.dataset_root,
            sample.observation.rgb_uri,
            sample.observation.rgb_sha256,
        )
        resolve_dataset_asset(
            args.dataset_root,
            sample.observation.depth_uri,
            sample.observation.depth_sha256,
        )
        features = (
            backbone.encode_multimodal(
                {
                    "texts": [
                        qwen_coarse_v2_prompt(
                            sample,
                            executed_intent_history=histories[sample.sample_id],
                            use_failure_context=use_fc,
                        )
                    ],
                    "images": [Image.open(rgb_path).convert("RGB")],
                }
            )
            .pooled.detach()
            .cpu()
            .float()
            .numpy()[0]
        )
        slots = canonical_slots_for_sample(sample)
        skill_logits, pointer_logits, destination_logits = heads.logits(
            features,
            slots.valid_mask,
        )
        indices = {
            "skill": int(np.argmax(skill_logits)),
            "pointer": int(np.argmax(pointer_logits)),
            "destination": int(np.argmax(destination_logits)),
        }
        target_track_id = (
            None
            if indices["pointer"] == len(POINTER_LABELS) - 1
            else slots.track_ids[indices["pointer"]]
        )
        destination_cell = (
            None
            if indices["destination"] == len(DESTINATION_LABELS) - 1
            else DESTINATION_LABELS[indices["destination"]]
        )
        intent = coarse_intent_from_prediction(
            skill_index=indices["skill"],
            target_track_id=target_track_id,
            destination_cell=destination_cell,
        )
        head_confidence = min(
            max(_softmax(skill_logits)),
            max(_softmax(pointer_logits)),
            max(_softmax(destination_logits)),
        )
        decision = SimpleNamespace(
            coarse=intent,
            recovery_skill=None,
            confidence=float(head_confidence),
        )
        runtime_observation = runtime_observation_for_sample(sample)
        request = build_runtime_skill_request_v2(
            runtime_observation,
            decision,
            registry,
        )
        mapping = validate_runtime_mapping_v2(request, registry)
        targets = {
            "skill": sample.skill_label_index,
            "pointer": sample.pointer_class_index,
            "destination": sample.destination_class_index,
        }
        for name in targets:
            truth[name].append(targets[name])
            predicted[name].append(indices[name])
        records.append(
            {
                "schema_version": "M2CQwenCoarseV2OfflineDecisionV1",
                "sample_id": sample.sample_id,
                "episode_id": sample.episode_id,
                "decision_index": sample.decision_index,
                "matched_key": sample.matched_key,
                "split": sample.split,
                "truth": targets,
                "prediction": indices,
                "predicted_intent": intent.model_dump(mode="json"),
                "probabilities": {
                    "skill": _softmax(skill_logits),
                    "pointer": _softmax(pointer_logits),
                    "destination": _softmax(destination_logits),
                },
                "runtime_request": request.model_dump(mode="json"),
                "structural_mapping": mapping.model_dump(mode="json"),
                "physical_gates": {
                    "ik": "NOT_RUN",
                    "collision": "NOT_RUN",
                    "safety": "NOT_RUN",
                },
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "physical_evaluation_executed": False,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    structurally_valid = sum(
        record["structural_mapping"]["status"] == "VALID" for record in records
    )
    joint_exact = sum(
        all(record["truth"][name] == record["prediction"][name] for name in truth)
        for record in records
    )
    report = {
        "schema_version": "M2CQwenCoarseV2OfflineEvalReportV1",
        "status": "PASS_IN_SAMPLE_RELOAD_NOT_QB_PHYSICAL_EVALUATION",
        "split": args.split,
        "samples": len(records),
        "metrics": {
            "skill": classification_metrics(truth["skill"], predicted["skill"], SKILL_LABELS),
            "pointer": classification_metrics(
                truth["pointer"], predicted["pointer"], POINTER_LABELS
            ),
            "destination": classification_metrics(
                truth["destination"],
                predicted["destination"],
                DESTINATION_LABELS,
            ),
            "joint_exact_match": joint_exact / len(records),
            "structural_mapping_rate": structurally_valid / len(records),
        },
        "dataset_sha256": dataset_report.dataset_sha256,
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "model_id": args.model_id,
        "model_revision": args.revision,
        "model_cache": _model_cache_report(
            args,
            fixed_revision_resolved=True,
            dry_run=False,
        ),
        "registry_sha256": sha256_file(args.registry),
        "decisions_sha256": sha256_file(args.output),
        "planning_checks_complete": False,
        "physical_gates": {
            "ik": "NOT_RUN",
            "collision": "NOT_RUN",
            "safety": "NOT_RUN",
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "physical_evaluation_executed": False,
        "limitations": [
            "In-sample reload classification and structural mapping only; no held-out TRAIN-role key is frozen.",
            "No IK, collision, safety, controller, Isaac, or Q-B physical execution ran.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
