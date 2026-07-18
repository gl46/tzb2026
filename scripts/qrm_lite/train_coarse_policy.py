#!/usr/bin/env python3
"""Train / overfit the coarse skill head (numpy path by default)."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import CoarsePolicyHead, encode_coarse_intent, default_label_space
from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import QRMTrainingSampleV1


def load_samples(path: Path, limit: int | None = None) -> list[QRMTrainingSampleV1]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(QRMTrainingSampleV1.model_validate_json(line))
        if limit and len(rows) >= limit:
            break
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Train QRM-Lite coarse policy head")
    p.add_argument("--dataset", default="data/qrm_lite/manifests/alpha-dataset.jsonl")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--epochs", type=int, default=400)
    p.add_argument("--lr", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="artifacts/qrm_lite/coarse_overfit.npz")
    p.add_argument("--report", default="reports/qrm-lite-coarse-policy.md")
    p.add_argument("--report-json", default="reports/qrm-lite-coarse-policy.json")
    args = p.parse_args(argv)

    rng = np.random.default_rng(args.seed)
    random.seed(args.seed)
    samples = load_samples(Path(args.dataset), limit=args.limit)
    if not samples:
        raise SystemExit(f"no samples in {args.dataset}")

    space = default_label_space()
    cdim = context_dim(backbone_dim=0)
    head = CoarsePolicyHead(cdim, space, hidden=256)

    X = np.stack([build_context_vector(s.observation, backbone_dim=0) for s in samples])
    Y = np.stack([encode_coarse_intent(s.coarse_intent, space) for s in samples])

    history = []
    for epoch in range(args.epochs):
        logits = head.forward(X)
        # MSE on multi-hot / soft targets (one-hot blocks)
        err = logits - Y
        loss = float(np.mean(err**2))
        # grads
        dlogits = (2.0 / err.size) * err
        h = np.tanh(X @ head.w1 + head.b1)
        dw2 = h.T @ dlogits
        db2 = dlogits.sum(axis=0)
        dh = dlogits @ head.w2.T * (1 - h**2)
        dw1 = X.T @ dh
        db1 = dh.sum(axis=0)
        head.w2 -= args.lr * dw2
        head.b2 -= args.lr * db2
        head.w1 -= args.lr * dw1
        head.b1 -= args.lr * db1
        # skill accuracy
        skill_n = len(space.skills)
        pred_skill = np.argmax(logits[:, :skill_n], axis=1)
        true_skill = np.argmax(Y[:, :skill_n], axis=1)
        acc = float(np.mean(pred_skill == true_skill))
        history.append({"epoch": epoch, "loss": loss, "skill_acc": acc})
        if epoch % 20 == 0 or epoch == args.epochs - 1:
            print(f"epoch={epoch} loss={loss:.6f} skill_acc={acc:.3f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, **{k: v for k, v in head.state_dict().items() if k != "space"}, space_json=json.dumps(head.state_dict()["space"]))

    final = history[-1]
    # qualitative examples
    examples = []
    for s, x in list(zip(samples, X))[:5]:
        pred = head.predict_intent(x)
        examples.append(
            {
                "sample_id": s.sample_id,
                "target_skill": s.coarse_intent.skill_type,
                "pred_skill": pred.skill_type,
                "target_fail": (s.coarse_intent.failure_type_aux or s.observation.failure_context.failure_type).value,
                "pred_fail": (pred.failure_type_aux.value if pred.failure_type_aux else None),
                "failure_context_used": s.observation.failure_context.failure_type.value,
            }
        )

    report_json = {
        "n_samples": len(samples),
        "epochs": args.epochs,
        "final_loss": final["loss"],
        "final_skill_acc": final["skill_acc"],
        "overfit_verified": final["skill_acc"] >= 0.95 and final["loss"] < history[0]["loss"],
        "checkpoint": str(out),
        "examples": examples,
        "history_tail": history[-5:],
    }
    Path(args.report_json).write_text(json.dumps(report_json, indent=2), encoding="utf-8")
    Path(args.report).write_text(
        "\n".join(
            [
                "# QRM-Lite coarse policy",
                "",
                f"- samples: {len(samples)}",
                f"- final skill accuracy: {final['skill_acc']:.3f}",
                f"- final loss: {final['loss']:.6f}",
                f"- overfit_verified: {report_json['overfit_verified']}",
                f"- checkpoint: `{out}`",
                "",
                "## Examples",
                "",
                "```json",
                json.dumps(examples, indent=2),
                "```",
                "",
                "FailureContext fields are part of the context vector (one-hot + residual counts).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report_json, indent=2))
    return 0 if report_json["overfit_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
