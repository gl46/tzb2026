#!/usr/bin/env python3
"""Real Qwen V4 LoRA training on ADR-0026 decision-level supervision.

There is no dry-run path.  The offline loader/smoke lives in
``qwen_decision_level_v4.py``.  This entry requires the same active Phase-2
bindings as the formal V4 trainer, replays all 273 V4 prefix rows before
loading the model, and masks only the 14 pointer losses whose public target
is outside the frozen K=8 candidate set.
"""

from __future__ import annotations

import argparse
from collections import Counter
import io
import json
import os
from pathlib import Path
import random
import time
from typing import Any

import numpy as np
from PIL import Image

from m2c.qwen_coarse_v2 import classification_metrics, sha256_tree
from m2c.qwen_coarse_v4 import (
    DESTINATION_LABELS,
    POINTER_LABELS,
    SKILL_LABELS,
)
from m2c.qwen_decision_level_v4 import (
    LoadedADR0026DecisionDatasetV4,
    decision_dataset_report_sha256_v4,
    decision_head_targets_v4,
    index_decision_histories_v4,
    load_adr0026_decision_dataset_v4,
    qwen_decision_prompt_v4,
    read_decision_rgb_v4,
    write_adr0026_decision_bundle_v4,
)
from m2c.train_qwen_coarse_v4 import (
    MAX_TRAINING_WALL_SECONDS,
    _build_backbone,
    _deadline,
    _hard_wall_alarm,
    _masked_pointer_logits,
    _numpy_heads,
    _publish_staging,
    _require_budget,
    _require_phase2_training_bindings,
    _require_snapshot_unchanged,
    _resolve_local_revision_snapshot,
    _staging_root,
)
from xh_agent.policy.qrm_lite.backbone import DEFAULT_MODEL_ID, DEFAULT_REVISION, Qwen35Backbone
from xh_agent.policy.qrm_lite.decision_level_supervision_v1 import (
    M2CS4DecisionLevelTrainingSampleV1,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)


ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-dataset-manifest", type=Path, required=True)
    parser.add_argument("--decision-packaging-report", type=Path, required=True)
    parser.add_argument("--evidence-base", type=Path, required=True)
    parser.add_argument("--training-keys", type=Path, action="append", required=True)
    parser.add_argument("--evaluation-keys", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--failure-context", choices=("on", "off"), required=True)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-wall-seconds", type=float, default=MAX_TRAINING_WALL_SECONDS)
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if args.model_id != DEFAULT_MODEL_ID or args.revision != DEFAULT_REVISION:
        raise ValueError("ADR-0026 training requires the canonical Qwen model revision")
    if not args.local_files_only:
        raise ValueError("ADR-0026 training requires --local-files-only")
    if not args.cache_dir.is_dir():
        raise ValueError("ADR-0026 local-only Qwen cache directory does not exist")
    if len(args.training_keys) != 2:
        raise ValueError("ADR-0026 training requires the two frozen V4 TRAIN manifests")
    if args.epochs < 1 or args.learning_rate <= 0.0:
        raise ValueError("ADR-0026 epochs and learning rate must be positive")
    if not 0 < args.max_wall_seconds <= MAX_TRAINING_WALL_SECONDS:
        raise ValueError("ADR-0026 training is limited to at most six hours")
    if args.output_root.exists():
        raise FileExistsError(f"refusing to overwrite ADR-0026 output root: {args.output_root}")


def _load_images(
    loaded: LoadedADR0026DecisionDatasetV4,
) -> dict[str, Image.Image]:
    rows = {row.training_sample.sample_id: row for row in loaded.rows}
    if len(rows) != len(loaded.rows):
        raise ValueError("ADR-0026 decision dataset repeats a sample identity")
    images: dict[str, Image.Image] = {}
    for sample in loaded.samples:
        payload = read_decision_rgb_v4(loaded, rows[sample.sample_id])
        with Image.open(io.BytesIO(payload)) as image:
            images[sample.sample_id] = image.convert("RGB").copy()
    return images


def _supervised_targets(
    sample: M2CS4DecisionLevelTrainingSampleV1,
) -> dict[str, int]:
    targets = {
        name: target
        for name, target in decision_head_targets_v4(sample).items()
        if target is not None
    }
    expected = (
        {"skill", "pointer", "destination"}
        if sample.pointer_head_supervision_eligible
        else {"skill", "destination"}
    )
    if set(targets) != expected:
        raise ValueError("ADR-0026 loss mask changed outside the pointer head")
    return targets


def _evaluate_fit(
    *,
    backbone: Qwen35Backbone,
    classifiers: dict[str, Any],
    samples: list[M2CS4DecisionLevelTrainingSampleV1],
    images: dict[str, Image.Image],
    histories: dict[str, list[Any]],
    use_failure_context: bool,
    deadline: float,
) -> dict[str, Any]:
    import torch

    truth: dict[str, list[int]] = {"skill": [], "pointer": [], "destination": []}
    predicted: dict[str, list[int]] = {"skill": [], "pointer": [], "destination": []}
    joint: list[bool] = []
    assert backbone._model is not None
    backbone._model.eval()
    for classifier in classifiers.values():
        classifier.eval()
    with torch.no_grad():
        for sample in samples:
            _require_budget(deadline)
            pooled = backbone.encode_multimodal(
                {
                    "texts": [
                        qwen_decision_prompt_v4(
                            sample,
                            executed_intent_history=histories[sample.sample_id],
                            use_failure_context=use_failure_context,
                        )
                    ],
                    "images": [images[sample.sample_id]],
                }
            ).pooled.float()
            logits = {
                "skill": classifiers["skill"](pooled),
                "pointer": _masked_pointer_logits(
                    classifiers["pointer"],
                    pooled,
                    sample.observation.candidate_payload.valid_mask,
                ),
                "destination": classifiers["destination"](pooled),
            }
            targets = decision_head_targets_v4(sample)
            sample_exact = True
            for name, target in targets.items():
                if target is None:
                    continue
                prediction = int(logits[name].argmax(dim=-1).item())
                truth[name].append(target)
                predicted[name].append(prediction)
                sample_exact &= prediction == target
            joint.append(sample_exact)
    return {
        "skill": classification_metrics(truth["skill"], predicted["skill"], SKILL_LABELS),
        "pointer": classification_metrics(truth["pointer"], predicted["pointer"], POINTER_LABELS),
        "destination": classification_metrics(
            truth["destination"], predicted["destination"], DESTINATION_LABELS
        ),
        "joint_exact_match_over_supervised_heads": sum(joint) / len(joint),
        "pointer_masked_rows": sum(
            not sample.pointer_head_supervision_eligible for sample in samples
        ),
    }


def _train(
    args: argparse.Namespace,
    loaded: LoadedADR0026DecisionDatasetV4,
    *,
    snapshot: Path,
    expected_snapshot_tree_sha256: str,
    staging_root: Path,
    started: float,
    deadline: float,
) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("real ADR-0026 Qwen training requires an available CUDA GPU")
    samples = loaded.samples
    by_episode: dict[str, list[M2CS4DecisionLevelTrainingSampleV1]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    if len(by_episode) != loaded.report.eligible_episodes or any(
        sorted(item.decision_index for item in episode) != list(range(7))
        for episode in by_episode.values()
    ):
        raise ValueError("ADR-0026 training input is not the exact complete prefix inventory")
    train = [
        sample
        for episode_id in sorted(by_episode)
        for sample in sorted(by_episode[episode_id], key=lambda item: item.decision_index)
    ]
    if len(train) != loaded.report.rows_total:
        raise ValueError("ADR-0026 training may not subsample the frozen first bundle")
    images = _load_images(loaded)
    histories = index_decision_histories_v4(train)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    if sha256_tree(snapshot) != expected_snapshot_tree_sha256:
        raise ValueError("ADR-0026 base-model snapshot changed before model loading")
    backbone = _build_backbone(args, snapshot)
    _require_snapshot_unchanged(args.cache_dir, snapshot, expected_snapshot_tree_sha256)
    backbone.attach_lora(r=8, alpha=16, dropout=0.05)
    assert backbone._model is not None and backbone._device is not None
    model_config = backbone._model.config
    hidden_size = int(getattr(model_config, "text_config", model_config).hidden_size)
    classifiers = {
        "skill": torch.nn.Linear(
            hidden_size, len(SKILL_LABELS), device=backbone._device, dtype=torch.float32
        ),
        "pointer": torch.nn.Linear(
            hidden_size, len(POINTER_LABELS), device=backbone._device, dtype=torch.float32
        ),
        "destination": torch.nn.Linear(
            hidden_size, len(DESTINATION_LABELS), device=backbone._device, dtype=torch.float32
        ),
    }
    parameters = [
        *(parameter for parameter in backbone._model.parameters() if parameter.requires_grad),
        *(parameter for head in classifiers.values() for parameter in head.parameters()),
    ]
    optimizer = torch.optim.AdamW(parameters, lr=args.learning_rate)
    loss_function = torch.nn.CrossEntropyLoss()
    use_failure_context = args.failure_context == "on"
    optimizer_steps = 0
    maximum_gradient_l2 = 0.0
    history: list[dict[str, Any]] = []
    backbone._model.train()
    for head in classifiers.values():
        head.train()
    for epoch in range(args.epochs):
        totals = {"skill": 0.0, "pointer": 0.0, "destination": 0.0}
        counts: Counter[str] = Counter()
        for sample in train:
            _require_budget(deadline)
            inputs = backbone._prepare_batch(
                {
                    "texts": [
                        qwen_decision_prompt_v4(
                            sample,
                            executed_intent_history=histories[sample.sample_id],
                            use_failure_context=use_failure_context,
                        )
                    ],
                    "images": [images[sample.sample_id]],
                }
            )
            optimizer.zero_grad(set_to_none=True)
            output = backbone._model(
                **inputs,
                output_hidden_states=True,
                return_dict=True,
                use_cache=False,
            )
            pooled = backbone._pool_hidden(
                output.hidden_states[-1], inputs.get("attention_mask")
            ).float()
            logits = {
                "skill": classifiers["skill"](pooled),
                "pointer": _masked_pointer_logits(
                    classifiers["pointer"],
                    pooled,
                    sample.observation.candidate_payload.valid_mask,
                ),
                "destination": classifiers["destination"](pooled),
            }
            targets = _supervised_targets(sample)
            losses = {
                name: loss_function(
                    logits[name],
                    torch.tensor([target], device=logits[name].device, dtype=torch.long),
                )
                for name, target in targets.items()
            }
            sum(losses.values()).backward()
            gradient_l2 = (
                sum(
                    float(parameter.grad.detach().float().pow(2).sum().cpu())
                    for parameter in parameters
                    if parameter.grad is not None
                )
                ** 0.5
            )
            maximum_gradient_l2 = max(maximum_gradient_l2, gradient_l2)
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            optimizer_steps += 1
            for name, value in losses.items():
                totals[name] += float(value.detach().cpu())
                counts[name] += 1
        history.append(
            {
                "epoch": epoch,
                "mean_loss": {name: totals[name] / counts[name] for name in totals},
                "supervised_rows": dict(sorted(counts.items())),
            }
        )
    fit_metrics = _evaluate_fit(
        backbone=backbone,
        classifiers=classifiers,
        samples=train,
        images=images,
        histories=histories,
        use_failure_context=use_failure_context,
        deadline=deadline,
    )
    staging_root.mkdir(parents=True)
    backbone.save_adapter(staging_root / "adapter")
    bundle = write_adr0026_decision_bundle_v4(
        staging_root,
        heads=_numpy_heads(classifiers),
        model_id=args.model_id,
        model_revision=args.revision,
        base_model_snapshot_tree_sha256=expected_snapshot_tree_sha256,
        failure_context=args.failure_context,
        dataset_report=loaded.report,
        seed=args.seed,
        optimizer_steps=optimizer_steps,
    )
    return {
        "schema_version": "M2CQwenCoarseV4ADR0026TrainReportV1",
        "status": "PASS_TRAINED_QWEN_LORA_M2C_Q012_V4_ADR0026_NOT_PHYSICAL_EVALUATION",
        "model_id": args.model_id,
        "model_revision": args.revision,
        "base_model_snapshot_tree_sha256": expected_snapshot_tree_sha256,
        "failure_context": args.failure_context,
        "seed": args.seed,
        "epochs": args.epochs,
        "n_train": len(train),
        "n_episodes": len(by_episode),
        "optimizer_steps": optimizer_steps,
        "pointer_head_supervised_rows": loaded.report.pointer_head_supervised_rows,
        "pointer_head_masked_rows": loaded.report.pointer_head_masked_rows,
        "max_gradient_l2": maximum_gradient_l2,
        "history": history,
        "training_fit_metrics": fit_metrics,
        "wall_seconds": time.monotonic() - started,
        "wall_budget_seconds": args.max_wall_seconds,
        "peak_vram_mb": torch.cuda.max_memory_allocated() / (1024**2),
        "dataset_report": loaded.report.model_dump(mode="json"),
        "dataset_report_sha256": decision_dataset_report_sha256_v4(loaded.report),
        "bundle_sha256": bundle.bundle_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "physical_evaluation_executed": False,
        "limitations": [
            "Training-fit metrics are not held-out or physical Q-B evidence.",
            "V3 rows remain isolated and were not silently upgraded into V4.",
            "Fourteen pointer losses are masked; skill and destination remain supervised.",
            "Runtime mapping, A1-A4 execution, and physical Q-B remain NOT_RUN.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_pre_freeze(M2CExperimentAction.TRAINING)
    _validate_args(args)
    _require_phase2_training_bindings()
    started = time.monotonic()
    deadline = _deadline(started, args.max_wall_seconds)
    with _hard_wall_alarm(deadline):
        loaded = load_adr0026_decision_dataset_v4(
            project_root=ROOT,
            evidence_base=args.evidence_base,
            dataset_manifest_path=args.decision_dataset_manifest,
            packaging_report_path=args.decision_packaging_report,
            training_manifest_paths=args.training_keys,
            evaluation_manifest_path=args.evaluation_keys,
        )
        snapshot = _resolve_local_revision_snapshot(args.cache_dir)
        snapshot_tree_sha256 = sha256_tree(snapshot)
        staging = _staging_root(args.output_root)
        report = _train(
            args,
            loaded,
            snapshot=snapshot,
            expected_snapshot_tree_sha256=snapshot_tree_sha256,
            staging_root=staging,
            started=started,
            deadline=deadline,
        )
        report_path = staging / "train_report.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(report_path, flags, 0o600)
        try:
            payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write while publishing ADR-0026 train report")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _publish_staging(staging, args.output_root, deadline)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
