#!/usr/bin/env python3
"""Train and evaluate the masked M2B residual MLP on scene-held-out data."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

import numpy as np

from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import (
    FailureContextV1,
    QRMObservationV1,
    QRMTrainingSampleV1,
)
from xh_agent.policy.qrm_lite.mlp_refiner import (
    MLPRefinerConfig,
    MLPResidualRefiner,
)


Split = Literal["val", "test"]
DIMENSIONS = [
    "dx",
    "dy",
    "dz",
    "r6d_0",
    "r6d_1",
    "r6d_2",
    "r6d_3",
    "r6d_4",
    "r6d_5",
    "gripper",
]


def load_samples(path: Path) -> list[QRMTrainingSampleV1]:
    return [
        QRMTrainingSampleV1.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _masked_observation(
    observation: QRMObservationV1, *, use_failure_context: bool
) -> QRMObservationV1:
    if use_failure_context:
        return observation
    return observation.model_copy(update={"failure_context": FailureContextV1()})


def sample_tensors(
    samples: list[QRMTrainingSampleV1],
    *,
    use_failure_context: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if not samples:
        raise ValueError("sample partition is empty")
    context = np.stack(
        [
            build_context_vector(
                _masked_observation(
                    sample.observation,
                    use_failure_context=use_failure_context,
                ),
                backbone_dim=0,
            )
            for sample in samples
        ]
    )
    nominal = np.stack(
        [np.asarray(sample.nominal_action_chunk.values, dtype=np.float64) for sample in samples]
    )
    target = np.stack(
        [np.asarray(sample.residual_action_chunk.values, dtype=np.float64) for sample in samples]
    )
    mask = np.stack(
        [
            np.asarray(
                sample.residual_action_chunk.action_mask,
                dtype=np.float64,
            )
            for sample in samples
        ]
    )
    return context, nominal, target, mask


def validate_samples(samples: list[QRMTrainingSampleV1], *, eval_split: Split) -> dict[str, Any]:
    findings: list[str] = []
    split_counts = Counter(sample.split for sample in samples)
    episode_splits: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        episode_splits[sample.episode_id].add(sample.split)
        chunks = (
            sample.nominal_action_chunk,
            sample.residual_action_chunk,
            sample.target_action_chunk,
        )
        expected_mask = [[1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
        for chunk in chunks:
            if len(chunk.values) != 1:
                findings.append(f"{sample.sample_id}: horizon is not 1")
            if chunk.fps != 1.0:
                findings.append(f"{sample.sample_id}: fps is not 1 Hz")
            if chunk.dimension_names != DIMENSIONS:
                findings.append(f"{sample.sample_id}: action dimensions are not explicit M2B 10D")
            if chunk.coordinate_frame != "camera_optical":
                findings.append(f"{sample.sample_id}: action frame is not camera optical")
            if chunk.action_mask != expected_mask:
                findings.append(
                    f"{sample.sample_id}: mask supervises dimensions without physical evidence"
                )
        if sample.synthetic:
            findings.append(f"{sample.sample_id}: synthetic residual label")
        if sample.provenance.get("label_source") != (
            "INDEPENDENT_PHYSICAL_PERTURBATION_CORRECTION"
        ):
            findings.append(f"{sample.sample_id}: physical label provenance missing")
        if not sample.simulator_supervision or not sample.simulator_supervision.get(
            "training_and_evaluation_only"
        ):
            findings.append(f"{sample.sample_id}: supervision boundary missing")
        elif sample.simulator_supervision.get("teacher_used") is not False:
            findings.append(f"{sample.sample_id}: no-Teacher boundary missing")
    leakage = sorted(episode for episode, splits in episode_splits.items() if len(splits) > 1)
    if leakage:
        findings.append(f"episode split leakage: {leakage}")
    n_train = split_counts["train"]
    n_eval = split_counts[eval_split]
    formal_ready = bool(len(samples) >= 50 and n_train >= 30 and n_eval >= 5 and not findings)
    return {
        "findings": sorted(set(findings)),
        "split_counts": dict(sorted(split_counts.items())),
        "episode_split_leakage": leakage,
        "n_train": n_train,
        "n_eval": n_eval,
        "formal_evaluation_ready": formal_ready,
    }


def masked_metrics(
    prediction: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
    *,
    near_zero_threshold: float = 1e-6,
) -> dict[str, Any]:
    prediction = np.asarray(prediction, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    mask = np.asarray(mask, dtype=np.float64)
    if prediction.shape != target.shape or mask.shape != target.shape:
        raise ValueError("prediction, target, and action mask shapes differ")
    active = mask > 0.0
    if not np.any(active):
        raise ValueError("action mask has no supervised dimensions")
    error = prediction - target
    absolute = np.abs(error)
    count = int(np.count_nonzero(active))
    per_axis: dict[str, dict[str, float | int]] = {}
    for index, name in enumerate(DIMENSIONS):
        axis_active = active[..., index]
        axis_count = int(np.count_nonzero(axis_active))
        if axis_count:
            axis_error = error[..., index][axis_active]
            per_axis[name] = {
                "count": axis_count,
                "mae": float(np.mean(np.abs(axis_error))),
                "rmse": float(np.sqrt(np.mean(axis_error**2))),
                "bias": float(np.mean(axis_error)),
            }
    per_sample_l1 = np.sum(absolute * active, axis=(1, 2))
    target_active = np.where(active, target, 0.0)
    prediction_active = np.where(active, prediction, 0.0)
    supervised_per_sample = np.sum(active, axis=(1, 2))
    return {
        "supervised_value_count": count,
        "mae": float(np.sum(absolute * active) / count),
        "rmse": float(np.sqrt(np.sum((error**2) * active) / count)),
        "mean_l1_per_chunk": float(np.mean(per_sample_l1)),
        "per_axis": per_axis,
        "target_exact_zero_value_fraction": float(
            np.count_nonzero(active & (np.abs(target) <= 1e-12)) / count
        ),
        "prediction_exact_zero_value_fraction": float(
            np.count_nonzero(active & (np.abs(prediction) <= 1e-12)) / count
        ),
        "target_near_zero_value_fraction": float(
            np.count_nonzero(active & (np.abs(target) <= near_zero_threshold)) / count
        ),
        "prediction_near_zero_value_fraction": float(
            np.count_nonzero(active & (np.abs(prediction) <= near_zero_threshold)) / count
        ),
        "target_exact_zero_chunk_fraction": float(
            np.mean(np.sum(np.abs(target_active), axis=(1, 2)) <= 1e-12)
        ),
        "prediction_near_zero_chunk_fraction": float(
            np.mean(
                np.sum(
                    active & (np.abs(prediction_active) <= near_zero_threshold),
                    axis=(1, 2),
                )
                == supervised_per_sample
            )
        ),
    }


def train_masked_mlp(
    train_samples: list[QRMTrainingSampleV1],
    *,
    use_failure_context: bool,
    seed: int,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    hidden: int,
) -> tuple[MLPResidualRefiner, list[dict[str, float | int]]]:
    context, nominal, target, mask = sample_tensors(
        train_samples, use_failure_context=use_failure_context
    )
    model = MLPResidualRefiner(
        MLPRefinerConfig(
            context_dim=context_dim(backbone_dim=0),
            horizon=1,
            action_dim=10,
            hidden=hidden,
            seed=seed,
        )
    )
    # Only camera translation has independent physical correction labels.
    # Make unsupported runtime outputs exactly zero, not random-but-untrained.
    model.w2[:, 3:] = 0.0
    model.b2[3:] = 0.0
    rng = np.random.default_rng(seed)
    history: list[dict[str, float | int]] = []
    for epoch in range(epochs):
        indices = rng.permutation(len(train_samples))
        epoch_squared_error = 0.0
        epoch_active = 0.0
        for start in range(0, len(indices), batch_size):
            batch = indices[start : start + batch_size]
            c = context[batch]
            n = nominal[batch]
            y = target[batch]
            m = mask[batch]
            x = np.concatenate([c, n.reshape(len(batch), -1)], axis=-1)
            x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            h = np.tanh(np.clip(x @ model.w1 + model.b1, -20.0, 20.0))
            raw = (h @ model.w2 + model.b2).reshape(len(batch), 1, 10)
            error = raw - y
            active = float(np.sum(m))
            if active <= 0.0:
                raise ValueError("training batch has no supervised values")
            epoch_squared_error += float(np.sum((error**2) * m))
            epoch_active += active
            output_gradient = (2.0 / active) * error * m
            output_gradient = output_gradient.reshape(len(batch), -1)
            dw2 = np.clip(h.T @ output_gradient, -1.0, 1.0)
            db2 = np.clip(output_gradient.sum(axis=0), -1.0, 1.0)
            dh = output_gradient @ model.w2.T * (1.0 - h**2)
            dw1 = np.clip(x.T @ dh, -1.0, 1.0)
            db1 = np.clip(dh.sum(axis=0), -1.0, 1.0)
            model.w2 -= learning_rate * dw2
            model.b2 -= learning_rate * db2
            model.w1 -= learning_rate * dw1
            model.b1 -= learning_rate * db1
        history.append(
            {
                "epoch": epoch,
                "masked_mse": epoch_squared_error / epoch_active,
            }
        )
    return model, history


def train_masked_mlp_torch(
    train_samples: list[QRMTrainingSampleV1],
    *,
    use_failure_context: bool,
    seed: int,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    hidden: int,
    device: str,
) -> tuple[
    MLPResidualRefiner,
    list[dict[str, float | int]],
    dict[str, Any],
]:
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("PyTorch is required for the CUDA backend") from error
    if device != "cuda":
        raise ValueError("torch backend currently supports only device='cuda'")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    context, nominal, target, mask = sample_tensors(
        train_samples, use_failure_context=use_failure_context
    )
    model = MLPResidualRefiner(
        MLPRefinerConfig(
            context_dim=context_dim(backbone_dim=0),
            horizon=1,
            action_dim=10,
            hidden=hidden,
            seed=seed,
        )
    )
    model.w2[:, 3:] = 0.0
    model.b2[3:] = 0.0
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.cuda.reset_peak_memory_stats()
    tensor_device = torch.device("cuda")
    c = torch.as_tensor(context, dtype=torch.float32, device=tensor_device)
    n = torch.as_tensor(nominal, dtype=torch.float32, device=tensor_device)
    y = torch.as_tensor(target, dtype=torch.float32, device=tensor_device)
    m = torch.as_tensor(mask, dtype=torch.float32, device=tensor_device)
    x = torch.cat([c, n.reshape(len(train_samples), -1)], dim=-1)
    parameters = [
        torch.nn.Parameter(torch.as_tensor(value, dtype=torch.float32, device=tensor_device))
        for value in (model.w1, model.b1, model.w2, model.b2)
    ]
    w1, b1, w2, b2 = parameters
    optimizer = torch.optim.Adam(parameters, lr=learning_rate)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    history: list[dict[str, float | int]] = []
    for epoch in range(epochs):
        indices = torch.randperm(len(train_samples), generator=generator)
        squared_error = 0.0
        active_total = 0.0
        for start in range(0, len(train_samples), batch_size):
            batch = indices[start : start + batch_size].to(tensor_device)
            hidden_state = torch.tanh(torch.clamp(x[batch] @ w1 + b1, -20.0, 20.0))
            raw = (hidden_state @ w2 + b2).reshape(len(batch), 1, 10)
            active = torch.sum(m[batch])
            if float(active.item()) <= 0.0:
                raise ValueError("training batch has no supervised values")
            batch_squared_error = torch.sum(((raw - y[batch]) ** 2) * m[batch])
            loss = batch_squared_error / active
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, max_norm=1.0)
            optimizer.step()
            squared_error += float(batch_squared_error.detach().item())
            active_total += float(active.detach().item())
        history.append({"epoch": epoch, "masked_mse": squared_error / active_total})
    model.w1 = w1.detach().cpu().numpy().astype(np.float64)
    model.b1 = b1.detach().cpu().numpy().astype(np.float64)
    model.w2 = w2.detach().cpu().numpy().astype(np.float64)
    model.b2 = b2.detach().cpu().numpy().astype(np.float64)
    model.w2[:, 3:] = 0.0
    model.b2[3:] = 0.0
    device_metadata = {
        "backend": "PYTORCH_CUDA",
        "torch_version": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_device_name": torch.cuda.get_device_name(),
        "peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "optimizer": "Adam",
    }
    return model, history, device_metadata


def evaluate(
    model: MLPResidualRefiner,
    samples: list[QRMTrainingSampleV1],
    *,
    use_failure_context: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context, nominal, target, mask = sample_tensors(
        samples, use_failure_context=use_failure_context
    )
    prediction = model.forward(context, nominal)
    return (
        masked_metrics(prediction, target, mask),
        masked_metrics(np.zeros_like(target), target, mask),
    )


def save_checkpoint(model: MLPResidualRefiner, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        w1=model.w1,
        b1=model.b1,
        w2=model.w2,
        b2=model.b2,
        cfg=json.dumps(model.cfg.__dict__, sort_keys=True),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--eval-split", choices=("val", "test"), default="val")
    parser.add_argument("--failure-context", choices=("off", "on"), default="on")
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    samples = load_samples(args.dataset)
    validation = validate_samples(samples, eval_split=args.eval_split)
    if validation["findings"]:
        raise SystemExit("invalid residual dataset: " + "; ".join(validation["findings"]))
    train_samples = [sample for sample in samples if sample.split == "train"]
    eval_samples = [sample for sample in samples if sample.split == args.eval_split]
    if not train_samples or not eval_samples:
        raise SystemExit("train and requested held-out split must both be non-empty")
    use_failure_context = args.failure_context == "on"
    if args.device == "cuda":
        model, history, device_metadata = train_masked_mlp_torch(
            train_samples,
            use_failure_context=use_failure_context,
            seed=args.seed,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            hidden=args.hidden,
            device=args.device,
        )
    else:
        model, history = train_masked_mlp(
            train_samples,
            use_failure_context=use_failure_context,
            seed=args.seed,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            hidden=args.hidden,
        )
        device_metadata = {
            "backend": "NUMPY_CPU",
            "numpy_version": np.__version__,
            "optimizer": "MASKED_MINIBATCH_SGD",
        }
    model_metrics, zero_metrics = evaluate(
        model, eval_samples, use_failure_context=use_failure_context
    )
    save_checkpoint(model, args.checkpoint)
    beats_zero = bool(
        model_metrics["mae"] < zero_metrics["mae"]
        and model_metrics["rmse"] < zero_metrics["rmse"]
        and model_metrics["mean_l1_per_chunk"] < zero_metrics["mean_l1_per_chunk"]
    )
    formal = validation["formal_evaluation_ready"]
    if formal:
        status = (
            "PASS_FORMAL_MLP_BEATS_ZERO" if beats_zero else "FAIL_FORMAL_MLP_NOT_BETTER_THAN_ZERO"
        )
    else:
        status = "PIPELINE_SMOKE_NOT_FORMAL"
    report = {
        "schema_version": "M2BMaskedResidualMLPReportV1",
        "status": status,
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
        "seed": args.seed,
        "failure_context": args.failure_context,
        "backbone_features": "NONE_STRUCTURED_CONTEXT_AND_NOMINAL_ONLY",
        "horizon": 1,
        "fps": 1.0,
        "action_frame": "camera_optical",
        "action_units": "m_rad_norm",
        "action_dimensions": DIMENSIONS,
        "supervised_dimensions": ["dx", "dy", "dz"],
        "normalization": "none",
        "near_zero_threshold": 1e-6,
        "unsupported_output_policy": "EXACT_ZERO_FROZEN_BY_ZERO_WEIGHTS",
        "eval_split": args.eval_split,
        "validation": validation,
        "model_metrics": model_metrics,
        "zero_residual_baseline": zero_metrics,
        "beats_zero_residual": beats_zero,
        "metric_delta_model_minus_zero": {
            key: model_metrics[key] - zero_metrics[key]
            for key in ("mae", "rmse", "mean_l1_per_chunk")
        },
        "training": {
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "batch_size": args.batch_size,
            "hidden": args.hidden,
            "initial_masked_mse": history[0]["masked_mse"],
            "final_masked_mse": history[-1]["masked_mse"],
            "history_tail": history[-5:],
            "device": device_metadata,
        },
        "teacher_used": False,
        "simulator_hard_truth_training_label": True,
        "privileged_truth_policy_input": False,
        "world_model_replaced": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
