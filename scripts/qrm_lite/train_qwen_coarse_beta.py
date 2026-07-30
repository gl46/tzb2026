#!/usr/bin/env python3
"""LoRA-train Qwen3.5-4B pooled features for real Isaac coarse skills."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from PIL import Image

from xh_agent.policy.qrm_lite.contracts import FailureContextV1, QRMTrainingSampleV1


def load_samples(path: Path) -> list[QRMTrainingSampleV1]:
    return [
        QRMTrainingSampleV1.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def resolve_image(dataset_root: Path, uri: str) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported RGB URI: {uri}")
    relative = Path(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"RGB URI escapes dataset: {uri}")
    # URI begins with shard-XXXXX.READY, which lives under dataset/shards.
    path = dataset_root / "shards" / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def prompt(sample: QRMTrainingSampleV1, *, use_failure_context: bool) -> str:
    observation = sample.observation
    tracks = [
        {
            "track_id": track.track_id,
            "category": track.category,
            "confidence": round(track.confidence, 4),
            "pose_xyzquat": track.pose_xyzquat,
        }
        for track in observation.perception_tracks
    ]
    context = (
        observation.failure_context.model_dump(mode="json")
        if use_failure_context
        else FailureContextV1().model_dump(mode="json")
    )
    payload = {
        "instruction": observation.instruction,
        "public_tracks": tracks,
        "joint_position": observation.joint_position,
        "gripper_state": observation.gripper_state,
        "current_skill_stage": observation.current_skill_stage,
        "failure_context": context,
        "allowed_skills": ["APPROACH", "REOBSERVE"],
    }
    return (
        "Choose exactly one safe coarse industrial skill from allowed_skills. "
        "Simulator truth is unavailable. Context:\n"
        + json.dumps(payload, sort_keys=True)
    )


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
    labels = ["APPROACH", "REOBSERVE"]
    observed_labels = sorted({sample.coarse_intent.skill_type for sample in samples})
    unsupported_labels = sorted(set(observed_labels) - set(labels))
    if unsupported_labels:
        raise SystemExit(f"unsupported real Pilot coarse labels: {unsupported_labels}")
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
                {"texts": [prompt(sample, use_failure_context=use_fc)], "images": [image]}
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
    with torch.no_grad():
        for sample in evaluation:
            image = Image.open(resolve_image(args.dataset_root, sample.observation.rgb_uri)).convert("RGB")
            features = backbone.encode_multimodal(
                {
                    "texts": [prompt(sample, use_failure_context=use_fc)],
                    "images": [image],
                }
            )
            logits = classifier(features.pooled.float())
            y_true.append(sample.coarse_intent.skill_type)
            y_pred.append(labels[int(logits.argmax(dim=-1))])
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
    accuracy = sum(truth == predicted for truth, predicted in zip(y_true, y_pred)) / len(y_true)
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
        "eval_accuracy": accuracy,
        "eval_predictions": [
            {"truth": truth, "predicted": predicted}
            for truth, predicted in zip(y_true, y_pred)
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
