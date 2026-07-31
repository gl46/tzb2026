#!/usr/bin/env python3
"""LoRA-train Qwen3.5-4B pooled features for real Isaac coarse skills."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from PIL import Image

from xh_agent.policy.qrm_lite.coarse_prompt import coarse_prompt
from xh_agent.policy.qrm_lite.contracts import (
    QRMCoarseTrainingSampleV2,
    QRMTrainingSampleV1,
)


CoarseSample = QRMTrainingSampleV1 | QRMCoarseTrainingSampleV2


def load_samples(path: Path) -> list[CoarseSample]:
    samples: list[CoarseSample] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        contract = (
            QRMCoarseTrainingSampleV2
            if payload.get("schema_version") == "QRMCoarseTrainingSampleV2"
            else QRMTrainingSampleV1
        )
        samples.append(contract.model_validate(payload))
    return samples


def resolve_image(dataset_root: Path, uri: str) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported RGB URI: {uri}")
    relative = Path(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"RGB URI escapes dataset: {uri}")
    direct = dataset_root / relative
    if direct.is_file():
        return direct
    # M2A URI begins with shard-XXXXX.READY, under dataset/shards.
    legacy = dataset_root / "shards" / relative
    if legacy.is_file():
        return legacy
    raise FileNotFoundError(f"neither {direct} nor {legacy} exists")


def prompt(
    sample: CoarseSample,
    *,
    use_failure_context: bool,
    allowed_skills: list[str] | None = None,
) -> str:
    return coarse_prompt(
        sample.observation,
        use_failure_context=use_failure_context,
        allowed_skills=allowed_skills or ["APPROACH", "REOBSERVE"],
    )


def classification_metrics(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str],
) -> dict:
    per_class = {}
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(y_true, y_pred))
        fp = sum(t != label and p == label for t, p in zip(y_true, y_pred))
        fn = sum(t == label and p != label for t, p in zip(y_true, y_pred))
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        per_class[label] = {
            "support": sum(t == label for t in y_true),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "accuracy": sum(t == p for t, p in zip(y_true, y_pred))
        / max(len(y_true), 1),
        "macro_f1": sum(item["f1"] for item in per_class.values())
        / len(labels),
        "per_class": per_class,
    }


def expected_calibration_error(
    confidences: list[float],
    correct: list[bool],
) -> float:
    import numpy as np

    values = np.asarray(confidences)
    outcomes = np.asarray(correct, dtype=float)
    error = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        selected = (values >= lower) & (values < lower + 0.1)
        if selected.any():
            error += float(selected.mean()) * abs(
                float(values[selected].mean())
                - float(outcomes[selected].mean())
            )
    return error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--failure-context", choices=("on", "off"), required=True)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--max-train", type=int, default=120)
    parser.add_argument("--max-eval", type=int, default=50)
    parser.add_argument("--eval-split", choices=("val", "test"), default="test")
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--adapter-out", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    args = parser.parse_args()

    import numpy as np
    import torch
    from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    samples = load_samples(args.dataset)
    train = [sample for sample in samples if sample.split == "train"]
    evaluation = [sample for sample in samples if sample.split == args.eval_split]
    random.Random(args.seed).shuffle(train)
    random.Random(args.seed).shuffle(evaluation)
    train = train[: args.max_train]
    evaluation = evaluation[: args.max_eval]
    observed_labels = sorted({sample.coarse_intent.skill_type for sample in samples})
    labels = observed_labels
    if not labels:
        raise SystemExit("coarse dataset has no observed labels")
    label_to_id = {label: index for index, label in enumerate(labels)}
    if not train or not evaluation:
        raise SystemExit("train/eval split is empty")

    backbone = Qwen35Backbone(
        model_id=args.model_id,
        revision=args.revision,
        device="cuda",
        dtype="bfloat16",
        local_files_only=Path(args.model_id).exists(),
    )
    backbone.attach_lora(r=8, alpha=16, dropout=0.05)
    assert backbone._model is not None
    model_config = backbone._model.config
    text_config = getattr(model_config, "text_config", model_config)
    hidden_size = int(text_config.hidden_size)
    classifier = torch.nn.Linear(hidden_size, len(labels), device="cuda", dtype=torch.float32)
    parameters = [
        parameter
        for parameter in backbone._model.parameters()
        if parameter.requires_grad
    ] + list(classifier.parameters())
    backbone_parameters = [
        parameter
        for parameter in backbone._model.parameters()
        if parameter.requires_grad
    ]
    initial_backbone = [parameter.detach().cpu().clone() for parameter in backbone_parameters]
    initial_classifier = [
        parameter.detach().cpu().clone() for parameter in classifier.parameters()
    ]
    optimizer = torch.optim.AdamW(parameters, lr=args.lr)
    loss_function = torch.nn.CrossEntropyLoss()
    use_fc = args.failure_context == "on"
    started = time.time()
    history: list[dict] = []
    max_gradient_l2 = 0.0
    optimizer_steps = 0
    backbone._model.train()
    classifier.train()
    for epoch in range(args.epochs):
        correct = 0
        loss_total = 0.0
        for index, sample in enumerate(train):
            image = Image.open(resolve_image(args.dataset_root, sample.observation.rgb_uri)).convert("RGB")
            inputs = backbone._prepare_batch(
                {
                    "texts": [
                        prompt(
                            sample,
                            use_failure_context=use_fc,
                            allowed_skills=labels,
                        )
                    ],
                    "images": [image],
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
            logits = classifier(pooled)
            target = torch.tensor(
                [label_to_id[sample.coarse_intent.skill_type]],
                device=logits.device,
            )
            loss = loss_function(logits, target)
            loss.backward()
            gradient_l2 = sum(
                float(parameter.grad.detach().float().pow(2).sum().cpu())
                for parameter in parameters
                if parameter.grad is not None
            ) ** 0.5
            max_gradient_l2 = max(max_gradient_l2, gradient_l2)
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            optimizer_steps += 1
            loss_total += float(loss.detach().cpu())
            correct += int(int(logits.argmax(dim=-1)) == int(target[0]))
            if index % 10 == 0:
                print(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "sample": index,
                            "loss": float(loss.detach().cpu()),
                            "failure_context": args.failure_context,
                        }
                    ),
                    flush=True,
                )
        history.append(
            {
                "epoch": epoch,
                "mean_loss": loss_total / len(train),
                "train_accuracy": correct / len(train),
            }
        )

    backbone._model.eval()
    classifier.eval()
    y_true: list[str] = []
    y_pred: list[str] = []
    confidences: list[float] = []
    with torch.no_grad():
        for sample in evaluation:
            image = Image.open(resolve_image(args.dataset_root, sample.observation.rgb_uri)).convert("RGB")
            features = backbone.encode_multimodal(
                {
                    "texts": [
                        prompt(
                            sample,
                            use_failure_context=use_fc,
                            allowed_skills=labels,
                        )
                    ],
                    "images": [image],
                }
            )
            logits = classifier(features.pooled.float())
            y_true.append(sample.coarse_intent.skill_type)
            y_pred.append(labels[int(logits.argmax(dim=-1))])
            confidences.append(
                float(torch.softmax(logits, dim=-1).max().detach().cpu())
            )
    args.adapter_out.mkdir(parents=True, exist_ok=True)
    backbone.save_adapter(args.adapter_out)
    torch.save(
        {
            "labels": labels,
            "classifier_state_dict": classifier.state_dict(),
            "hidden_size": hidden_size,
            "failure_context": args.failure_context,
            "seed": args.seed,
        },
        args.adapter_out / "coarse_head.pt",
    )
    evaluation_metrics = classification_metrics(y_true, y_pred, labels)
    evaluation_metrics["ece_10bin"] = expected_calibration_error(
        confidences,
        [truth == predicted for truth, predicted in zip(y_true, y_pred)],
    )
    failure_indices = [
        index
        for index, sample in enumerate(evaluation)
        if sample.observation.failure_context.failure_type.value != "NONE"
    ]
    evaluation_metrics["failure_recovery_skill_accuracy"] = (
        sum(y_true[index] == y_pred[index] for index in failure_indices)
        / max(len(failure_indices), 1)
    )
    evaluation_metrics["wrong_object_recovery_accuracy"] = None
    backbone_update_l2 = sum(
        float(
            (
                parameter.detach().cpu().float() - initial.float()
            ).pow(2).sum()
        )
        for parameter, initial in zip(backbone_parameters, initial_backbone)
    ) ** 0.5
    classifier_update_l2 = sum(
        float(
            (
                parameter.detach().cpu().float() - initial.float()
            ).pow(2).sum()
        )
        for parameter, initial in zip(classifier.parameters(), initial_classifier)
    ) ** 0.5
    limitations = []
    status = "PASS"
    if len(observed_labels) < 2:
        status = "PASS_WITH_LIMITATIONS_SINGLE_CLASS"
        limitations.append(
            "real Pilot coarse labels contain one class; accuracy is degenerate "
            "and cannot establish FailureContext value"
        )
    if max_gradient_l2 == 0.0:
        limitations.append("training objective produced zero gradient")
    report = {
        "schema_version": "Qwen35LoRACoarseBetaTrainV1",
        "status": status,
        "model_id": args.model_id,
        "revision": args.revision,
        "failure_context": args.failure_context,
        "seed": args.seed,
        "epochs": args.epochs,
        "n_train": len(train),
        "n_eval": len(evaluation),
        "eval_split": args.eval_split,
        "labels": labels,
        "head_label_count": len(labels),
        "observed_labels": observed_labels,
        "observed_label_count": len(observed_labels),
        "history": history,
        "eval_accuracy": evaluation_metrics["accuracy"],
        "eval_metrics": evaluation_metrics,
        "eval_predictions": [
            {
                "truth": truth,
                "predicted": predicted,
                "confidence": confidence,
            }
            for truth, predicted, confidence in zip(
                y_true,
                y_pred,
                confidences,
            )
        ],
        "adapter_out": str(args.adapter_out),
        "wall_seconds": time.time() - started,
        "peak_vram_mb": (
            torch.cuda.max_memory_allocated() / (1024**2)
            if torch.cuda.is_available()
            else None
        ),
        "optimizer_steps": optimizer_steps,
        "max_gradient_l2": max_gradient_l2,
        "backbone_trainable_parameters": sum(
            parameter.numel() for parameter in backbone_parameters
        ),
        "classifier_trainable_parameters": sum(
            parameter.numel() for parameter in classifier.parameters()
        ),
        "backbone_update_l2": backbone_update_l2,
        "classifier_update_l2": classifier_update_l2,
        "limitations": limitations,
        "oracle_policy_inputs": False,
        "flow_status": "DISABLED",
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
