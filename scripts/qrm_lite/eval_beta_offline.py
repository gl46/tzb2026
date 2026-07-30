#!/usr/bin/env python3
"""Held-out QRM Beta evaluation for coarse, FailureContext, and MLP residual."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.context import build_context_vector
from xh_agent.policy.qrm_lite.contracts import FailureContextV1, QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.models_q012 import FormalModelId, build_formal_model


def load_samples(path: Path, split: str) -> list[QRMTrainingSampleV1]:
    return [
        sample
        for line in path.read_text().splitlines()
        if line.strip()
        for sample in [QRMTrainingSampleV1.model_validate_json(line)]
        if sample.split == split
    ]


def load_model(checkpoint: Path):
    payload = np.load(checkpoint)
    model = build_formal_model(str(payload["model_id"]))
    for name in ("w1", "b1", "w2", "b2"):
        setattr(model.coarse, name, np.asarray(payload[f"coarse_{name}"]))
        setattr(model.mlp, name, np.asarray(payload[f"mlp_{name}"]))
    return model


def classification_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))
    by_class: dict[str, dict[str, float | int]] = {}
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(y_true, y_pred))
        fp = sum(t != label and p == label for t, p in zip(y_true, y_pred))
        fn = sum(t == label and p != label for t, p in zip(y_true, y_pred))
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        by_class[label] = {
            "support": sum(t == label for t in y_true),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "accuracy": sum(t == p for t, p in zip(y_true, y_pred)) / max(len(y_true), 1),
        "macro_f1": sum(float(item["f1"]) for item in by_class.values())
        / max(len(by_class), 1),
        "per_class": by_class,
    }


def expected_calibration_error(confidences: list[float], correct: list[bool]) -> float:
    if not confidences:
        return 0.0
    error = 0.0
    values = np.asarray(confidences)
    outcomes = np.asarray(correct, dtype=float)
    for lower in np.linspace(0.0, 0.9, 10):
        selected = (values >= lower) & (values < lower + 0.1)
        if selected.any():
            error += float(selected.mean()) * abs(
                float(values[selected].mean()) - float(outcomes[selected].mean())
            )
    return error


def evaluate_model(model, samples: list[QRMTrainingSampleV1]) -> dict[str, Any]:
    y_true: list[str] = []
    y_pred: list[str] = []
    confidence: list[float] = []
    residual_pred: list[np.ndarray] = []
    residual_true: list[np.ndarray] = []
    saturation = 0
    for sample in samples:
        nominal = np.asarray(sample.nominal_action_chunk.values)
        output = model.predict(
            sample.observation,
            nominal=nominal if model.uses_residual else None,
        )
        predicted = output.coarse.skill_type
        y_true.append(sample.coarse_intent.skill_type)
        y_pred.append(predicted)
        observation = sample.observation
        if not model.uses_failure_context:
            observation = observation.model_copy(deep=True)
            observation.failure_context = FailureContextV1()
        context = build_context_vector(
            observation,
            backbone_dim=model.cfg.backbone_dim,
            joint_dim=model.cfg.joint_dim,
            history_len=model.cfg.history_len,
            action_dim=model.cfg.action_dim,
        )
        logits = model.coarse.forward(context)[: len(model.label_space.skills)]
        probabilities = np.exp(logits - logits.max())
        probabilities /= probabilities.sum()
        confidence.append(float(probabilities.max()))
        if model.uses_residual:
            prediction = np.asarray(output.residual)
            target = np.asarray(sample.residual_action_chunk.values)
            residual_pred.append(prediction)
            residual_true.append(target)
            saturation += int(np.any(np.abs(prediction[..., :3]) >= 0.03 - 1e-9))
    metrics = classification_metrics(y_true, y_pred)
    metrics["ece_10bin"] = expected_calibration_error(
        confidence, [truth == predicted for truth, predicted in zip(y_true, y_pred)]
    )
    failure_indices = [
        index
        for index, sample in enumerate(samples)
        if sample.observation.failure_context.failure_type.value != "NONE"
    ]
    metrics["failure_recovery_skill_accuracy"] = (
        sum(y_true[index] == y_pred[index] for index in failure_indices)
        / max(len(failure_indices), 1)
    )
    metrics["wrong_object_recovery_accuracy"] = None
    metrics["n"] = len(samples)
    metrics["prediction_histogram"] = dict(Counter(y_pred))
    if residual_pred:
        prediction = np.stack(residual_pred)
        target = np.stack(residual_true)
        difference = prediction - target
        metrics["residual"] = {
            "mae": float(np.mean(np.abs(difference))),
            "rmse": float(np.sqrt(np.mean(difference**2))),
            "camera_translation_mae_m": float(
                np.mean(np.abs(difference[..., :3]))
            ),
            "rotation_r6d_mae": float(np.mean(np.abs(difference[..., 3:9]))),
            "gripper_mae": float(np.mean(np.abs(difference[..., 9]))),
            "saturation_rate": saturation / max(len(samples), 1),
            "ik_acceptance_rate": None,
            "collision_rejection_rate": None,
        }
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--train-report", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--report-json", type=Path, default=Path("reports/m2a-s4-qrm-beta-offline.json"))
    parser.add_argument("--report-md", type=Path, default=Path("reports/m2a-s4-qrm-beta-offline.md"))
    args = parser.parse_args()
    samples = load_samples(args.dataset, args.split)
    if not samples:
        raise SystemExit(f"no {args.split} samples")
    training = json.loads(args.train_report.read_text())
    metrics: dict[str, Any] = {}
    for model_id, details in training["models"].items():
        metrics[model_id] = evaluate_model(
            load_model(Path(details["checkpoint"])),
            samples,
        )
    q0 = metrics.get(FormalModelId.Q0.value, {})
    q2 = metrics.get(FormalModelId.Q2.value, {})
    report = {
        "schema_version": "QRMLiteBetaOfflineEvalV1",
        "status": "PASS",
        "dataset": str(args.dataset),
        "dataset_split": args.split,
        "models": metrics,
        "failure_context_delta": {
            "accuracy": q2.get("accuracy", 0.0) - q0.get("accuracy", 0.0),
            "macro_f1": q2.get("macro_f1", 0.0) - q0.get("macro_f1", 0.0),
            "failure_recovery_skill_accuracy": q2.get(
                "failure_recovery_skill_accuracy", 0.0
            )
            - q0.get("failure_recovery_skill_accuracy", 0.0),
        },
        "flow_status": "DISABLED",
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = ["# M2A S4 QRM Beta offline", "", f"- split: `{args.split}`"]
    for model_id, item in metrics.items():
        lines.extend(
            [
                f"- {model_id}: accuracy={item['accuracy']:.4f}, "
                f"macro-F1={item['macro_f1']:.4f}, ECE={item['ece_10bin']:.4f}",
            ]
        )
    lines.extend(
        [
            f"- FailureContext deltas: `{report['failure_context_delta']}`",
            "- Flow: `DISABLED`",
            "",
        ]
    )
    args.report_md.write_text("\n".join(lines))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

