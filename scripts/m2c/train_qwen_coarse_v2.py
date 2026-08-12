#!/usr/bin/env python3
"""Train the ADR-0020 Qwen LoRA skill/pointer/destination heads.

The default invocation performs real GPU training.  ``--dry-run`` is an
explicit five-sample, NumPy-only contract/checkpoint smoke and makes no model,
training, or Q-B evaluation claim.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import random
import signal
import time
from typing import Any
import uuid

import numpy as np
from PIL import Image

try:
    from m2c.qwen_coarse_v2 import (
        CHAIN_SKILLS,
        DESTINATION_LABELS,
        HEAD_CHECKPOINT_NAME,
        MAX_TRAINING_WALL_SECONDS,
        POINTER_LABELS,
        SKILL_LABELS,
        M2CQwenCoarseV2TrainingSample,
        NumpyThreeHeadsV2,
        build_head_metadata,
        canonical_slots_for_sample,
        classification_metrics,
        index_executed_histories,
        load_training_dataset,
        qwen_coarse_v2_prompt,
        resolve_dataset_asset,
        run_offline_smoke,
        save_head_checkpoint,
        write_bundle_manifest,
    )
except ModuleNotFoundError as error:
    if error.name != "m2c":
        raise
    from qwen_coarse_v2 import (  # type: ignore[no-redef]
        CHAIN_SKILLS,
        DESTINATION_LABELS,
        HEAD_CHECKPOINT_NAME,
        MAX_TRAINING_WALL_SECONDS,
        POINTER_LABELS,
        SKILL_LABELS,
        M2CQwenCoarseV2TrainingSample,
        NumpyThreeHeadsV2,
        build_head_metadata,
        canonical_slots_for_sample,
        classification_metrics,
        index_executed_histories,
        load_training_dataset,
        qwen_coarse_v2_prompt,
        resolve_dataset_asset,
        run_offline_smoke,
        save_head_checkpoint,
        write_bundle_manifest,
    )
from xh_agent.policy.qrm_lite.backbone import (
    DEFAULT_MODEL_ID,
    DEFAULT_REVISION,
    Qwen35Backbone,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)


WALL_BUDGET_ERROR = "M2C Qwen seed exceeded its six-hour whole-run budget"


def _wall_budget_deadline(started_monotonic: float, budget_seconds: float) -> float:
    return started_monotonic + budget_seconds


def _require_wall_budget(deadline_monotonic: float) -> None:
    if time.monotonic() >= deadline_monotonic:
        raise TimeoutError(WALL_BUDGET_ERROR)


def _run_with_wall_budget(
    deadline_monotonic: float,
    operation,
    /,
    *args,
    **kwargs,
):
    """Run one blocking stage and reject a result completed at/after deadline."""

    _require_wall_budget(deadline_monotonic)
    result = operation(*args, **kwargs)
    _require_wall_budget(deadline_monotonic)
    return result


def _elapsed_within_wall_budget(
    started_monotonic: float,
    deadline_monotonic: float,
) -> float:
    finished_monotonic = time.monotonic()
    if finished_monotonic >= deadline_monotonic:
        raise TimeoutError(WALL_BUDGET_ERROR)
    return finished_monotonic - started_monotonic


@contextmanager
def _hard_wall_alarm(deadline_monotonic: float):
    """Raise at the real-process deadline, including inside blocking stages."""

    remaining_seconds = deadline_monotonic - time.monotonic()
    if remaining_seconds <= 0.0:
        raise TimeoutError(WALL_BUDGET_ERROR)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    if previous_delay > 0.0 or previous_interval > 0.0:
        raise RuntimeError("refusing to replace an existing process wall timer")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def handle_timeout(_signum, _frame) -> None:
        raise TimeoutError(WALL_BUDGET_ERROR)

    signal.signal(signal.SIGALRM, handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, remaining_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _staging_output_root(output_root: Path) -> Path:
    return output_root.parent / (f".{output_root.name}.incomplete-{uuid.uuid4().hex}")


def _publish_staged_output(
    staging_root: Path,
    output_root: Path,
    deadline_monotonic: float,
) -> None:
    """Atomically publish, rolling back if the commit crosses the deadline."""

    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite M2C output root: {output_root}")
    if not staging_root.is_dir():
        raise FileNotFoundError(f"M2C staging root is missing: {staging_root}")
    _require_wall_budget(deadline_monotonic)
    try:
        staging_root.replace(output_root)
        _require_wall_budget(deadline_monotonic)
    except TimeoutError:
        if output_root.is_dir() and not staging_root.exists():
            output_root.replace(staging_root)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train M2C Qwen CoarseIntentV2 three heads",
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--dataset-manifest", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--training-keys", required=True, type=Path)
    parser.add_argument("--evaluation-keys", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Hugging Face cache root; never used as the model identity",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="resolve the pinned revision from --cache-dir without hub access",
    )
    parser.add_argument(
        "--failure-context",
        choices=("on", "off"),
        required=True,
    )
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-train", type=int, default=288)
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=MAX_TRAINING_WALL_SECONDS,
    )
    parser.add_argument(
        "--m2b-init-adapter",
        type=Path,
        help=(
            "unsupported on the formal S4 path; any value fails closed before "
            "dataset or model loading because M2B adapter provenance is not frozen"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="five-sample NumPy smoke; never loads Qwen or CUDA",
    )
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if args.m2b_init_adapter is not None:
        raise ValueError(
            "formal S4 training forbids --m2b-init-adapter; initialization_source must be NONE"
        )
    if args.epochs < 1:
        raise ValueError("epochs must be positive")
    if args.learning_rate <= 0.0:
        raise ValueError("learning rate must be positive")
    if args.max_train < 1:
        raise ValueError("train limit must be positive")
    if args.max_train % len(CHAIN_SKILLS) != 0:
        raise ValueError("train limit must preserve complete 8-step episodes")
    if not 0 < args.max_wall_seconds <= MAX_TRAINING_WALL_SECONDS:
        raise ValueError("each seed is limited to at most six hours")
    if not args.dry_run and args.model_id != DEFAULT_MODEL_ID:
        raise ValueError(
            "real training requires the canonical Qwen model ID; local paths "
            "may only be supplied as --cache-dir"
        )
    if not args.dry_run and args.revision != DEFAULT_REVISION:
        raise ValueError("real training requires the canonical Qwen revision")
    if not args.dry_run and args.local_files_only:
        if args.cache_dir is None:
            raise ValueError("--local-files-only requires an explicit --cache-dir")
        if not args.cache_dir.is_dir():
            raise ValueError("local-only Qwen cache directory does not exist")
    if args.output_root.exists():
        raise FileExistsError(f"refusing to overwrite M2C output root: {args.output_root}")


def _canonical_cache_snapshot(cache_dir: Path) -> Path:
    repository_cache = "models--" + DEFAULT_MODEL_ID.replace("/", "--")
    return cache_dir / repository_cache / "snapshots" / DEFAULT_REVISION


def _reject_lfs_pointer(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"local-only Qwen cache file is absent or empty: {path.name}")
    with path.open("rb") as stream:
        prefix = stream.read(128)
    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise ValueError(f"local-only Qwen cache still has an LFS pointer: {path.name}")


def _resolve_local_revision_snapshot(cache_dir: Path) -> Path:
    """Resolve and minimally validate the exact canonical offline snapshot."""

    snapshot = _canonical_cache_snapshot(cache_dir)
    if not snapshot.is_dir():
        raise ValueError("local-only Qwen cache cannot resolve the canonical fixed revision")
    config = snapshot / "config.json"
    _reject_lfs_pointer(config)
    weight_files: set[Path] = set()
    for index_name in (
        "model.safetensors.index.json",
        "pytorch_model.bin.index.json",
    ):
        index_path = snapshot / index_name
        if not index_path.is_file():
            continue
        _reject_lfs_pointer(index_path)
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("local-only Qwen weight index is invalid") from error
        weight_map = payload.get("weight_map")
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError("local-only Qwen weight index has no weight map")
        for raw_name in weight_map.values():
            if not isinstance(raw_name, str):
                raise ValueError("local-only Qwen weight index has a non-string shard")
            relative = Path(raw_name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("local-only Qwen weight shard escapes the snapshot")
            weight_files.add(snapshot / relative)
    if not weight_files:
        for single_name in ("model.safetensors", "pytorch_model.bin"):
            candidate = snapshot / single_name
            if candidate.is_file():
                weight_files.add(candidate)
    if not weight_files:
        raise ValueError("local-only canonical Qwen snapshot has no complete weight files")
    for weight_file in weight_files:
        _reject_lfs_pointer(weight_file)
    return snapshot


def _model_cache_report(
    args: argparse.Namespace,
    *,
    fixed_revision_resolved: bool,
    dry_run: bool,
) -> dict[str, bool | str]:
    if dry_run:
        mode = "NOT_ACCESSED_DRY_RUN"
    elif args.local_files_only:
        mode = "LOCAL_FILES_ONLY"
    else:
        mode = "HUB_ACCESS_ALLOWED"
    return {
        "mode": mode,
        "cache_dir_explicit": args.cache_dir is not None,
        "local_files_only": bool(args.local_files_only),
        "fixed_revision_resolved": fixed_revision_resolved,
        "cache_path_recorded_as_model_identity": False,
    }


def _build_backbone(args: argparse.Namespace) -> Qwen35Backbone:
    return Qwen35Backbone(
        model_id=args.model_id,
        revision=args.revision,
        device="cuda",
        dtype="bfloat16",
        cache_dir=(str(args.cache_dir.resolve()) if args.cache_dir else None),
        local_files_only=bool(args.local_files_only),
    )


def _verified_assets(
    samples: list[M2CQwenCoarseV2TrainingSample],
    dataset_root: Path,
) -> dict[str, tuple[Path, Path]]:
    assets: dict[str, tuple[Path, Path]] = {}
    for sample in samples:
        rgb = resolve_dataset_asset(
            dataset_root,
            sample.observation.rgb_uri,
            sample.observation.rgb_sha256,
        )
        depth = resolve_dataset_asset(
            dataset_root,
            sample.observation.depth_uri,
            sample.observation.depth_sha256,
        )
        assets[sample.sample_id] = (rgb, depth)
    return assets


def _torch_masked_logits(
    classifier,
    features,
    valid_mask: list[bool],
):
    import torch

    logits = classifier(features.float())
    mask = torch.tensor(
        [*valid_mask, True],
        device=logits.device,
        dtype=torch.bool,
    ).reshape(1, -1)
    return logits.masked_fill(~mask, torch.finfo(logits.dtype).min)


def _tensor_target(value: int, device):
    import torch

    return torch.tensor([value], device=device, dtype=torch.long)


def _evaluate(
    *,
    backbone: Qwen35Backbone,
    classifiers: dict[str, Any],
    samples: list[M2CQwenCoarseV2TrainingSample],
    assets: dict[str, tuple[Path, Path]],
    use_failure_context: bool,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    import torch

    truth = {"skill": [], "pointer": [], "destination": []}
    predicted = {"skill": [], "pointer": [], "destination": []}
    histories = index_executed_histories(samples)
    for classifier in classifiers.values():
        classifier.eval()
    assert backbone._model is not None
    backbone._model.eval()
    with torch.no_grad():
        for sample in samples:
            if deadline_monotonic is not None:
                _require_wall_budget(deadline_monotonic)
            rgb_path, _ = assets[sample.sample_id]
            features = backbone.encode_multimodal(
                {
                    "texts": [
                        qwen_coarse_v2_prompt(
                            sample,
                            executed_intent_history=histories[sample.sample_id],
                            use_failure_context=use_failure_context,
                        )
                    ],
                    "images": [Image.open(rgb_path).convert("RGB")],
                }
            ).pooled.float()
            logits = {
                "skill": classifiers["skill"](features),
                "pointer": _torch_masked_logits(
                    classifiers["pointer"],
                    features,
                    canonical_slots_for_sample(sample).valid_mask.tolist(),
                ),
                "destination": classifiers["destination"](features),
            }
            targets = {
                "skill": sample.skill_label_index,
                "pointer": sample.pointer_class_index,
                "destination": sample.destination_class_index,
            }
            for name in targets:
                truth[name].append(targets[name])
                predicted[name].append(int(logits[name].argmax(dim=-1).item()))
    return {
        "skill": classification_metrics(
            truth["skill"],
            predicted["skill"],
            SKILL_LABELS,
        ),
        "pointer": classification_metrics(
            truth["pointer"],
            predicted["pointer"],
            POINTER_LABELS,
        ),
        "destination": classification_metrics(
            truth["destination"],
            predicted["destination"],
            DESTINATION_LABELS,
        ),
        "joint_exact_match": sum(
            skill_truth == skill_prediction
            and pointer_truth == pointer_prediction
            and destination_truth == destination_prediction
            for (
                skill_truth,
                skill_prediction,
                pointer_truth,
                pointer_prediction,
                destination_truth,
                destination_prediction,
            ) in zip(
                truth["skill"],
                predicted["skill"],
                truth["pointer"],
                predicted["pointer"],
                truth["destination"],
                predicted["destination"],
            )
        )
        / len(samples),
    }


def _numpy_heads(classifiers: dict[str, Any]) -> NumpyThreeHeadsV2:
    def values(name: str) -> tuple[np.ndarray, np.ndarray]:
        classifier = classifiers[name]
        weight = classifier.weight.detach().cpu().float().numpy().T.copy()
        bias = classifier.bias.detach().cpu().float().numpy().copy()
        return weight, bias

    skill_w, skill_b = values("skill")
    pointer_w, pointer_b = values("pointer")
    destination_w, destination_b = values("destination")
    return NumpyThreeHeadsV2(
        skill_w=skill_w,
        skill_b=skill_b,
        pointer_w=pointer_w,
        pointer_b=pointer_b,
        destination_w=destination_w,
        destination_b=destination_b,
    )


def _attach_trainable_adapter(
    backbone: Qwen35Backbone,
    initialization_adapter: Path | None,
) -> tuple[str, str | None]:
    if initialization_adapter is not None:
        # Defense in depth for direct callers that bypass CLI validation.  An
        # arbitrary PEFT directory cannot be promoted to M2B_Q012_V1 solely by
        # supplying a path and hashing its bytes.
        raise ValueError(
            "formal S4 training forbids M2B adapter initialization; "
            "initialization_source must be NONE"
        )
    backbone.attach_lora(r=8, alpha=16, dropout=0.05)
    return "NONE", None


def _real_train(
    args: argparse.Namespace,
    samples: list[M2CQwenCoarseV2TrainingSample],
    dataset_report,
    *,
    whole_run_started_monotonic: float | None = None,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    if args.m2b_init_adapter is not None:
        raise ValueError(
            "formal S4 training forbids M2B adapter initialization; "
            "initialization_source must be NONE"
        )
    started = (
        time.monotonic() if whole_run_started_monotonic is None else whole_run_started_monotonic
    )
    deadline = (
        _wall_budget_deadline(started, args.max_wall_seconds)
        if deadline_monotonic is None
        else deadline_monotonic
    )
    _require_wall_budget(deadline)

    import torch

    _require_wall_budget(deadline)

    if not torch.cuda.is_available():
        raise RuntimeError("real M2C Qwen training requires an available CUDA GPU")
    train = [sample for sample in samples if sample.split == "train"]
    if not train:
        raise ValueError("real training requires eligible frozen TRAIN samples")
    if any(sample.split != "train" for sample in samples):
        raise ValueError("real training received an eligible non-TRAIN sample")
    by_episode: dict[str, list[M2CQwenCoarseV2TrainingSample]] = {}
    for sample in train:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    episodes = sorted(by_episode)
    random.Random(args.seed).shuffle(episodes)
    selected_episodes = episodes[: args.max_train // len(CHAIN_SKILLS)]
    train = [
        sample
        for episode_id in selected_episodes
        for sample in sorted(
            by_episode[episode_id],
            key=lambda item: item.decision_index,
        )
    ]
    assets = _run_with_wall_budget(
        deadline,
        _verified_assets,
        train,
        args.dataset_root,
    )

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    backbone = _build_backbone(args)
    initialization_source, initialization_sha256 = _run_with_wall_budget(
        deadline,
        _attach_trainable_adapter,
        backbone,
        args.m2b_init_adapter,
    )
    assert backbone._model is not None
    assert backbone._device is not None
    model_config = backbone._model.config
    text_config = getattr(model_config, "text_config", model_config)
    hidden_size = int(text_config.hidden_size)
    classifiers = {
        "skill": torch.nn.Linear(
            hidden_size,
            len(SKILL_LABELS),
            device=backbone._device,
            dtype=torch.float32,
        ),
        "pointer": torch.nn.Linear(
            hidden_size,
            len(POINTER_LABELS),
            device=backbone._device,
            dtype=torch.float32,
        ),
        "destination": torch.nn.Linear(
            hidden_size,
            len(DESTINATION_LABELS),
            device=backbone._device,
            dtype=torch.float32,
        ),
    }
    trainable_backbone = [
        parameter for parameter in backbone._model.parameters() if parameter.requires_grad
    ]
    parameters = [
        *trainable_backbone,
        *(parameter for head in classifiers.values() for parameter in head.parameters()),
    ]
    optimizer = torch.optim.AdamW(parameters, lr=args.learning_rate)
    loss_function = torch.nn.CrossEntropyLoss()
    _require_wall_budget(deadline)
    use_fc = args.failure_context == "on"
    history: list[dict[str, Any]] = []
    executed_histories = index_executed_histories(train)
    optimizer_steps = 0
    maximum_gradient_l2 = 0.0
    backbone._model.train()
    for head in classifiers.values():
        head.train()

    for epoch in range(args.epochs):
        epoch_loss = {"skill": 0.0, "pointer": 0.0, "destination": 0.0}
        for index, sample in enumerate(train):
            elapsed = time.monotonic() - started
            _require_wall_budget(deadline)
            rgb_path, _ = assets[sample.sample_id]
            inputs = backbone._prepare_batch(
                {
                    "texts": [
                        qwen_coarse_v2_prompt(
                            sample,
                            executed_intent_history=(executed_histories[sample.sample_id]),
                            use_failure_context=use_fc,
                        )
                    ],
                    "images": [Image.open(rgb_path).convert("RGB")],
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
                output.hidden_states[-1],
                inputs.get("attention_mask"),
            ).float()
            logits = {
                "skill": classifiers["skill"](pooled),
                "pointer": _torch_masked_logits(
                    classifiers["pointer"],
                    pooled,
                    canonical_slots_for_sample(sample).valid_mask.tolist(),
                ),
                "destination": classifiers["destination"](pooled),
            }
            targets = {
                "skill": sample.skill_label_index,
                "pointer": sample.pointer_class_index,
                "destination": sample.destination_class_index,
            }
            losses = {
                name: loss_function(
                    logits[name],
                    _tensor_target(target, logits[name].device),
                )
                for name, target in targets.items()
            }
            loss = losses["skill"] + losses["pointer"] + losses["destination"]
            loss.backward()
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
            _require_wall_budget(deadline)
            optimizer_steps += 1
            for name, item in losses.items():
                epoch_loss[name] += float(item.detach().cpu())
            if index % 10 == 0:
                print(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "sample": index,
                            "loss": float(loss.detach().cpu()),
                            "failure_context": args.failure_context,
                            "wall_seconds": elapsed,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        history.append(
            {
                "epoch": epoch,
                "mean_loss": {name: value / len(train) for name, value in epoch_loss.items()},
            }
        )

    train_fit_metrics = _run_with_wall_budget(
        deadline,
        _evaluate,
        backbone=backbone,
        classifiers=classifiers,
        samples=train,
        assets=assets,
        use_failure_context=use_fc,
        deadline_monotonic=deadline,
    )
    _run_with_wall_budget(deadline, args.output_root.mkdir, parents=True)
    adapter_output = args.output_root / "adapter"
    _run_with_wall_budget(deadline, backbone.save_adapter, adapter_output)
    metadata = build_head_metadata(
        model_id=args.model_id,
        model_revision=args.revision,
        hidden_size=hidden_size,
        failure_context=args.failure_context,
        dataset_sha256=dataset_report.dataset_sha256,
        dataset_manifest_sha256=dataset_report.dataset_manifest_sha256,
        training_manifest_sha256=(dataset_report.key_manifest_audit.training_manifest_sha256),
        evaluation_manifest_sha256=(dataset_report.key_manifest_audit.evaluation_manifest_sha256),
        seed=args.seed,
        initialization_source=initialization_source,
        initialization_adapter_sha256=initialization_sha256,
        adapter_source_architecture_revision=(
            "M2B_Q012_V1" if initialization_source == "M2B_ADAPTER_INITIALIZATION_ONLY" else None
        ),
    )
    numpy_heads = _run_with_wall_budget(deadline, _numpy_heads, classifiers)
    _run_with_wall_budget(
        deadline,
        save_head_checkpoint,
        args.output_root / HEAD_CHECKPOINT_NAME,
        numpy_heads,
        metadata,
    )
    bundle = _run_with_wall_budget(
        deadline,
        write_bundle_manifest,
        args.output_root,
        status="TRAINED_QWEN_LORA_THREE_HEADS",
    )
    wall_seconds = _elapsed_within_wall_budget(started, deadline)
    return {
        "schema_version": "M2CQwenCoarseV2TrainReportV1",
        "status": "PASS_TRAINED_QWEN_LORA_THREE_HEADS_NOT_PHYSICAL_EVALUATION",
        "model_id": args.model_id,
        "model_revision": args.revision,
        "model_cache": _model_cache_report(
            args,
            fixed_revision_resolved=True,
            dry_run=False,
        ),
        "failure_context": args.failure_context,
        "seed": args.seed,
        "executed_intent_history": {
            "schema": "PublicExecutedIntentHistoryItemV2",
            "prompt_attribution": "EXECUTED_PHYSICAL_SKILL",
            "training_source_attribution": ("SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"),
            "exact_prior_prefix_required": True,
            "current_decision_index_exposed": False,
            "expected_next_skill_exposed": False,
        },
        "epochs": args.epochs,
        "n_train": len(train),
        "n_val": 0,
        "history": history,
        "training_fit_metrics": train_fit_metrics,
        "optimizer_steps": optimizer_steps,
        "max_gradient_l2": maximum_gradient_l2,
        "wall_seconds": wall_seconds,
        "wall_budget_seconds": args.max_wall_seconds,
        "peak_vram_mb": torch.cuda.max_memory_allocated() / (1024**2),
        "initialization_source": initialization_source,
        "initialization_adapter_sha256": initialization_sha256,
        "adapter_source_architecture_revision": (
            "M2B_Q012_V1" if initialization_source == "M2B_ADAPTER_INITIALIZATION_ONLY" else None
        ),
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "dataset_report": dataset_report.model_dump(mode="json"),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "flow_status": "DISABLED",
        "physical_evaluation_executed": False,
        "limitations": [
            "This is training plus in-sample fit accounting only.",
            "No held-out TRAIN-role validation keys are frozen; training_fit_metrics are not evaluation evidence.",
            "Raw depth is hash-verified; Qwen consumes RGB plus public RGB-D tracks.",
            "Runtime mapping, planning gates, and physical Q-B execution are NOT_RUN.",
        ],
    }


def _run_real_pipeline(
    args: argparse.Namespace,
    staging_root: Path,
    whole_run_started: float,
    whole_run_deadline: float,
) -> dict[str, Any]:
    staged_args = argparse.Namespace(
        **{
            **vars(args),
            "output_root": staging_root,
        }
    )
    with _hard_wall_alarm(whole_run_deadline):
        if args.local_files_only:
            _run_with_wall_budget(
                whole_run_deadline,
                _resolve_local_revision_snapshot,
                args.cache_dir,
            )
        samples, dataset_report = _run_with_wall_budget(
            whole_run_deadline,
            load_training_dataset,
            args.dataset,
            dataset_manifest_path=args.dataset_manifest,
            training_manifest_path=args.training_keys,
            evaluation_manifest_path=args.evaluation_keys,
        )
        report = _real_train(
            staged_args,
            samples,
            dataset_report,
            whole_run_started_monotonic=whole_run_started,
            deadline_monotonic=whole_run_deadline,
        )
        report["wall_seconds"] = _elapsed_within_wall_budget(
            whole_run_started,
            whole_run_deadline,
        )
        report["wall_budget_seconds"] = args.max_wall_seconds
        report_path = staging_root / "train_report.json"
        _run_with_wall_budget(
            whole_run_deadline,
            report_path.write_text,
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _publish_staged_output(
            staging_root,
            args.output_root,
            whole_run_deadline,
        )
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # The historical ``--dry-run`` performs a real five-sample gradient
    # update and publishes a checkpoint bundle.  It is small, but it is still
    # training and therefore cannot bypass the 9/1 experiment freeze.
    require_pre_freeze(M2CExperimentAction.TRAINING)
    _validate_args(args)
    whole_run_started = time.monotonic()
    whole_run_deadline = _wall_budget_deadline(
        whole_run_started,
        args.max_wall_seconds,
    )
    if args.dry_run:
        samples, dataset_report = load_training_dataset(
            args.dataset,
            dataset_manifest_path=args.dataset_manifest,
            training_manifest_path=args.training_keys,
            evaluation_manifest_path=args.evaluation_keys,
        )
        report = run_offline_smoke(
            samples,
            output_root=args.output_root,
            dataset_report=dataset_report,
            seed=args.seed,
            failure_context=args.failure_context,
        )
        report["dataset_report"] = dataset_report.model_dump(mode="json")
        report["model_cache"] = _model_cache_report(
            args,
            fixed_revision_resolved=False,
            dry_run=True,
        )
        report_path = args.output_root / "train_report.json"
        if report_path.exists():
            raise FileExistsError(f"refusing to overwrite report: {report_path}")
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    staging_root = _staging_output_root(args.output_root)
    try:
        report = _run_real_pipeline(
            args,
            staging_root,
            whole_run_started,
            whole_run_deadline,
        )
    except TimeoutError:
        if args.output_root.is_dir() and not staging_root.exists():
            args.output_root.replace(staging_root)
        raise
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
