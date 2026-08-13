#!/usr/bin/env python3
"""Real Qwen LoRA training entry for replayed M2C V4 physical supervision.

There is deliberately no dry-run mode.  Contract-only checks live in
``qwen_coarse_v4.run_offline_contract_smoke_v4`` and do not update weights.
This entry performs real training only after every V4 package, frozen TRAIN
key, and S6 exclusion has been independently replayed.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import time
from typing import Any
import uuid

import numpy as np
from PIL import Image

from m2c.qwen_coarse_v2 import classification_metrics, sha256_tree
from m2c.qwen_coarse_v4 import (
    CHAIN_SKILLS,
    DESTINATION_LABELS,
    POINTER_LABELS,
    SKILL_LABELS,
    M2CQwenCoarseV4TrainingSample,
    M2CQwenCoarseV4DatasetLoadReportV1,
    NumpyThreeHeadsV4,
    dataset_report_sha256_v4,
    index_executed_histories_v4,
    load_training_packages_v4,
    qwen_coarse_v4_prompt,
    read_dataset_asset_v4,
    write_bundle_manifest_v4,
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


MAX_TRAINING_WALL_SECONDS = 6 * 60 * 60
WALL_BUDGET_ERROR = "M2C Qwen V4 seed exceeded its six-hour whole-run budget"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHA256_PATTERN = r"^[0-9a-f]{64}$"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train M2C Qwen M2C_Q012_V4 heads and LoRA")
    parser.add_argument(
        "--package-root",
        action="append",
        required=True,
        type=Path,
        help="one packaged V4 TRAIN episode root; repeat for additional episodes",
    )
    parser.add_argument("--training-keys", required=True, type=Path)
    parser.add_argument("--evaluation-keys", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--failure-context", choices=("on", "off"), required=True)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-train", type=int, default=288)
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=MAX_TRAINING_WALL_SECONDS,
    )
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if args.model_id != DEFAULT_MODEL_ID:
        raise ValueError("V4 real training requires the canonical Qwen model ID")
    if args.revision != DEFAULT_REVISION:
        raise ValueError("V4 real training requires the canonical Qwen revision")
    if not args.local_files_only:
        raise ValueError("V4 real training requires --local-files-only")
    if not args.cache_dir.is_dir():
        raise ValueError("V4 local-only Qwen cache directory does not exist")
    if args.epochs < 1 or args.learning_rate <= 0.0:
        raise ValueError("V4 epochs and learning rate must be positive")
    if args.max_train < 1 or args.max_train % len(CHAIN_SKILLS) != 0:
        raise ValueError("V4 train limit must preserve complete eight-step episodes")
    if not 0 < args.max_wall_seconds <= MAX_TRAINING_WALL_SECONDS:
        raise ValueError("each V4 seed is limited to at most six hours")
    if args.output_root.exists():
        raise FileExistsError(f"refusing to overwrite V4 output root: {args.output_root}")


def _require_phase2_training_bindings() -> None:
    """Honor ADR-0024: two active bindings, two withdrawn sentinels."""

    from xh_agent.policy.qrm_lite import s4_entry_gate

    missing = [
        name
        for name in (
            "FORMAL_PHYSICAL_RUNNER_BINDING",
            "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
        )
        if getattr(s4_entry_gate, name) is None
    ]
    if missing:
        raise RuntimeError(f"V4 training requires active Phase-2 bindings: {missing}")
    withdrawn = [
        name
        for name in (
            "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
            "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
        )
        if getattr(s4_entry_gate, name) is not None
    ]
    if withdrawn:
        raise RuntimeError(f"ADR-0024 withdrawn bindings must remain unset: {withdrawn}")
    runner_path_text, runner_sha256 = s4_entry_gate.FORMAL_PHYSICAL_RUNNER_BINDING
    implementation_commit, container_image, closure_sha256 = (
        s4_entry_gate.FORMAL_DEPLOYMENT_CLOSURE_BINDING
    )
    runner_relative = Path(runner_path_text)
    if (
        runner_relative.is_absolute()
        or ".." in runner_relative.parts
        or re.fullmatch(SHA256_PATTERN, runner_sha256) is None
        or re.fullmatch(r"^[0-9a-f]{40}$", implementation_commit) is None
        or re.fullmatch(r"^sha256:[0-9a-f]{64}$", container_image) is None
        or re.fullmatch(SHA256_PATTERN, closure_sha256) is None
    ):
        raise RuntimeError("Phase-2 training binding shape is invalid")
    runner = PROJECT_ROOT / runner_relative
    if runner.is_symlink() or not runner.is_file():
        raise RuntimeError("Phase-2 frozen runner path is absent or linked")
    runner_bytes = runner.read_bytes()
    if hashlib.sha256(runner_bytes).hexdigest() != runner_sha256:
        raise RuntimeError("Phase-2 frozen runner current bytes differ")
    committed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "show", f"{implementation_commit}:{runner_path_text}"],
        check=False,
        capture_output=True,
    )
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(PROJECT_ROOT),
            "merge-base",
            "--is-ancestor",
            implementation_commit,
            "HEAD",
        ],
        check=False,
        capture_output=True,
    )
    if (
        committed.returncode != 0
        or hashlib.sha256(committed.stdout).hexdigest() != runner_sha256
        or ancestor.returncode != 0
    ):
        raise RuntimeError("Phase-2 frozen runner is not exact at an ancestor binding commit")


def _resolve_local_revision_snapshot(cache_dir: Path) -> Path:
    # Reuse the formal Qwen service's exact materialized-snapshot verifier.
    # Keeping one verifier prevents the trainer from accepting a mutable
    # Hugging Face symlink view that the deployed service would later reject.
    from m2c.serve_qwen_coarse_v2 import _resolve_materialized_model_snapshot

    return _resolve_materialized_model_snapshot(cache_dir)


def _require_snapshot_unchanged(
    cache_dir: Path,
    snapshot: Path,
    expected_tree_sha256: str,
) -> None:
    if (
        _resolve_local_revision_snapshot(cache_dir) != snapshot
        or sha256_tree(snapshot) != expected_tree_sha256
    ):
        raise ValueError("V4 base-model snapshot changed while model loaded")


def _deadline(started: float, budget: float) -> float:
    return started + budget


def _require_budget(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError(WALL_BUDGET_ERROR)


@contextmanager
def _hard_wall_alarm(deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        raise TimeoutError(WALL_BUDGET_ERROR)
    prior_delay, prior_interval = signal.getitimer(signal.ITIMER_REAL)
    if prior_delay > 0.0 or prior_interval > 0.0:
        raise RuntimeError("refusing to replace an existing process wall timer")
    prior_handler = signal.getsignal(signal.SIGALRM)

    def timeout(_signum: int, _frame: object) -> None:
        raise TimeoutError(WALL_BUDGET_ERROR)

    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, prior_handler)


def _staging_root(output_root: Path) -> Path:
    return output_root.parent / f".{output_root.name}.incomplete-{uuid.uuid4().hex}"


def _publish_staging(staging_root: Path, output_root: Path, deadline: float) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite V4 output root: {output_root}")
    if not staging_root.is_dir():
        raise FileNotFoundError("V4 staging output is absent")
    _require_budget(deadline)
    try:
        staging_root.replace(output_root)
        _require_budget(deadline)
    except TimeoutError:
        if output_root.is_dir() and not staging_root.exists():
            output_root.replace(staging_root)
        raise


def _build_backbone(args: argparse.Namespace, snapshot: Path) -> Qwen35Backbone:
    return Qwen35Backbone(
        model_id=args.model_id,
        revision=args.revision,
        device="cuda",
        dtype="bfloat16",
        cache_dir=str(args.cache_dir.resolve()),
        local_files_only=True,
        resolved_model_path=str(snapshot.resolve()),
    )


def _package_by_key(
    samples: list[M2CQwenCoarseV4TrainingSample],
    dataset_report: M2CQwenCoarseV4DatasetLoadReportV1,
) -> dict[str, Path]:
    mapping = {item.matched_key: Path(item.package_root) for item in dataset_report.packages}
    if any(sample.matched_key not in mapping for sample in samples):
        raise ValueError("V4 sample has no replayed package root")
    return mapping


def _load_rgb_images(
    samples: list[M2CQwenCoarseV4TrainingSample],
    dataset_report: M2CQwenCoarseV4DatasetLoadReportV1,
) -> dict[str, Image.Image]:
    roots = _package_by_key(samples, dataset_report)
    images: dict[str, Image.Image] = {}
    for sample in samples:
        payload = read_dataset_asset_v4(
            roots[sample.matched_key],
            sample.observation.rgb_uri,
            sample.observation.rgb_sha256,
        )
        with Image.open(io.BytesIO(payload)) as image:
            images[sample.sample_id] = image.convert("RGB").copy()
    return images


def _masked_pointer_logits(classifier: Any, features: Any, valid_mask: list[bool]):
    import torch

    logits = classifier(features.float())
    mask = torch.tensor([*valid_mask, True], device=logits.device, dtype=torch.bool).reshape(1, -1)
    return logits.masked_fill(~mask, torch.finfo(logits.dtype).min)


def _numpy_heads(classifiers: dict[str, Any]) -> NumpyThreeHeadsV4:
    def values(name: str) -> tuple[np.ndarray, np.ndarray]:
        classifier = classifiers[name]
        return (
            classifier.weight.detach().cpu().float().numpy().T.copy(),
            classifier.bias.detach().cpu().float().numpy().copy(),
        )

    skill_w, skill_b = values("skill")
    pointer_w, pointer_b = values("pointer")
    destination_w, destination_b = values("destination")
    return NumpyThreeHeadsV4(
        skill_w=skill_w,
        skill_b=skill_b,
        pointer_w=pointer_w,
        pointer_b=pointer_b,
        destination_w=destination_w,
        destination_b=destination_b,
    )


def _evaluate_fit(
    *,
    backbone: Qwen35Backbone,
    classifiers: dict[str, Any],
    samples: list[M2CQwenCoarseV4TrainingSample],
    images: dict[str, Image.Image],
    histories: dict[str, list[Any]],
    use_failure_context: bool,
    deadline: float,
) -> dict[str, Any]:
    import torch

    truth = {"skill": [], "pointer": [], "destination": []}
    predicted = {"skill": [], "pointer": [], "destination": []}
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
                        qwen_coarse_v4_prompt(
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
            targets = {
                "skill": sample.skill_label_index,
                "pointer": sample.pointer_class_index,
                "destination": sample.destination_class_index,
            }
            for name, target in targets.items():
                truth[name].append(target)
                predicted[name].append(int(logits[name].argmax(dim=-1).item()))
    return {
        "skill": classification_metrics(truth["skill"], predicted["skill"], SKILL_LABELS),
        "pointer": classification_metrics(truth["pointer"], predicted["pointer"], POINTER_LABELS),
        "destination": classification_metrics(
            truth["destination"], predicted["destination"], DESTINATION_LABELS
        ),
        "joint_exact_match": sum(
            all(truth[name][index] == predicted[name][index] for name in truth)
            for index in range(len(samples))
        )
        / len(samples),
    }


def _train(
    args: argparse.Namespace,
    samples: list[M2CQwenCoarseV4TrainingSample],
    dataset_report: M2CQwenCoarseV4DatasetLoadReportV1,
    *,
    snapshot: Path,
    expected_snapshot_tree_sha256: str,
    staging_root: Path,
    started: float,
    deadline: float,
) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("real M2C V4 Qwen training requires an available CUDA GPU")
    by_episode: dict[str, list[M2CQwenCoarseV4TrainingSample]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    episodes = sorted(by_episode)
    random.Random(args.seed).shuffle(episodes)
    episodes = episodes[: args.max_train // len(CHAIN_SKILLS)]
    train = [
        sample
        for episode in episodes
        for sample in sorted(by_episode[episode], key=lambda item: item.decision_index)
    ]
    if not train:
        raise ValueError("V4 real training has zero complete eligible episodes")
    images = _load_rgb_images(train, dataset_report)
    histories = index_executed_histories_v4(train)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    if sha256_tree(snapshot) != expected_snapshot_tree_sha256:
        raise ValueError("V4 base-model snapshot changed before model loading")
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
    base_model_snapshot_tree_sha256 = expected_snapshot_tree_sha256
    optimizer_steps = 0
    maximum_gradient_l2 = 0.0
    history: list[dict[str, Any]] = []
    backbone._model.train()
    for head in classifiers.values():
        head.train()
    for epoch in range(args.epochs):
        totals = {"skill": 0.0, "pointer": 0.0, "destination": 0.0}
        for sample in train:
            _require_budget(deadline)
            inputs = backbone._prepare_batch(
                {
                    "texts": [
                        qwen_coarse_v4_prompt(
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
            targets = {
                "skill": sample.skill_label_index,
                "pointer": sample.pointer_class_index,
                "destination": sample.destination_class_index,
            }
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
        history.append(
            {
                "epoch": epoch,
                "mean_loss": {name: value / len(train) for name, value in totals.items()},
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
    heads = _numpy_heads(classifiers)
    selected_report_payload = dataset_report.model_dump(mode="json")
    selected_report_payload.update(
        {
            "combined_dataset_sha256": hashlib.sha256(
                "".join(item.model_dump_json(exclude_none=False) + "\n" for item in train).encode()
            ).hexdigest(),
            "rows_total": len(train),
            "eligible_episodes": len(episodes),
            "packages": [
                item for item in dataset_report.packages if item.episode_id in set(episodes)
            ],
        }
    )
    selected_report = M2CQwenCoarseV4DatasetLoadReportV1.model_validate(selected_report_payload)
    bundle = write_bundle_manifest_v4(
        staging_root,
        heads=heads,
        model_id=args.model_id,
        model_revision=args.revision,
        base_model_snapshot_tree_sha256=base_model_snapshot_tree_sha256,
        failure_context=args.failure_context,
        dataset_report=selected_report,
        seed=args.seed,
        optimizer_steps=optimizer_steps,
    )
    return {
        "schema_version": "M2CQwenCoarseV4TrainReportV1",
        "status": "PASS_TRAINED_QWEN_LORA_M2C_Q012_V4_NOT_PHYSICAL_EVALUATION",
        "model_id": args.model_id,
        "model_revision": args.revision,
        "base_model_snapshot_tree_sha256": base_model_snapshot_tree_sha256,
        "failure_context": args.failure_context,
        "seed": args.seed,
        "epochs": args.epochs,
        "n_train": len(train),
        "n_episodes": len(episodes),
        "optimizer_steps": optimizer_steps,
        "max_gradient_l2": maximum_gradient_l2,
        "history": history,
        "training_fit_metrics": fit_metrics,
        "wall_seconds": time.monotonic() - started,
        "wall_budget_seconds": args.max_wall_seconds,
        "peak_vram_mb": torch.cuda.max_memory_allocated() / (1024**2),
        "dataset_report": selected_report.model_dump(mode="json"),
        "dataset_report_sha256": dataset_report_sha256_v4(selected_report),
        "bundle_sha256": bundle.bundle_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "physical_evaluation_executed": False,
        "limitations": [
            "Training-fit metrics are not held-out or physical evaluation evidence.",
            "No fixed B0 continuation is part of this model bundle.",
            "Runtime mapping, A1-A4 preflight/execution, and physical Q-B remain NOT_RUN.",
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
        # Replay data before model-cache resolution, CUDA checks, model loading,
        # or output creation. Zero eligible V4 evidence cannot start training.
        samples, dataset_report = load_training_packages_v4(
            args.package_root,
            training_manifest_path=args.training_keys,
            evaluation_manifest_path=args.evaluation_keys,
        )
        snapshot = _resolve_local_revision_snapshot(args.cache_dir)
        snapshot_tree_sha256 = sha256_tree(snapshot)
        staging = _staging_root(args.output_root)
        try:
            report = _train(
                args,
                samples,
                dataset_report,
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
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise OSError("short write while publishing V4 train report")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            _publish_staging(staging, args.output_root, deadline)
        except BaseException:
            # Never publish a partial result as a trained bundle.
            raise
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
