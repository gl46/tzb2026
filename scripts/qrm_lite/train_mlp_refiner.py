#!/usr/bin/env python3
"""Train MLP residual refiner on alpha dataset (numpy overfit path)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.mlp_refiner import MLPRefinerConfig, MLPResidualRefiner


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
    p = argparse.ArgumentParser(description="Train MLP residual refiner")
    p.add_argument("--dataset", default="data/qrm_lite/manifests/alpha-dataset.jsonl")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--epochs", type=int, default=500)
    p.add_argument("--lr", type=float, default=0.1)
    p.add_argument("--horizon", type=int, default=4)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="artifacts/qrm_lite/mlp_refiner.npz")
    p.add_argument("--report", default="reports/qrm-lite-mlp-refiner.md")
    p.add_argument("--report-json", default="reports/qrm-lite-mlp-refiner.json")
    args = p.parse_args(argv)

    samples = load_samples(Path(args.dataset), limit=args.limit)
    cdim = context_dim(backbone_dim=0)
    model = MLPResidualRefiner(
        MLPRefinerConfig(context_dim=cdim, horizon=args.horizon, action_dim=10, hidden=512)
    )

    Xc = np.stack([build_context_vector(s.observation, backbone_dim=0) for s in samples])
    Nom = np.stack([np.asarray(s.nominal_action_chunk.values, dtype=np.float64) for s in samples])
    Y = np.stack([np.asarray(s.residual_action_chunk.values, dtype=np.float64) for s in samples])

    history = []
    for epoch in range(args.epochs):
        # Train on unclipped linear outputs; clip only for metrics/export.
        B = Xc.shape[0]
        n_flat = Nom.reshape(B, -1)
        x = np.concatenate([Xc, n_flat], axis=-1)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        h_pre = np.clip(x @ model.w1 + model.b1, -20.0, 20.0)
        h = np.tanh(h_pre)
        raw = h @ model.w2 + model.b2
        raw = raw.reshape(B, model.cfg.horizon, model.cfg.action_dim)
        err = raw - Y
        loss = float(np.mean(err**2))
        dpred = (2.0 / err.size) * err
        dpred_flat = dpred.reshape(B, -1)
        dw2 = np.clip(h.T @ dpred_flat, -1.0, 1.0)
        db2 = np.clip(dpred_flat.sum(axis=0), -1.0, 1.0)
        dh = dpred_flat @ model.w2.T * (1 - h**2)
        dw1 = np.clip(x.T @ dh, -1.0, 1.0)
        db1 = np.clip(dh.sum(axis=0), -1.0, 1.0)
        model.w2 -= args.lr * dw2
        model.b2 -= args.lr * db2
        model.w1 -= args.lr * dw1
        model.b1 -= args.lr * db1
        pred = model.forward(Xc, Nom)
        mae_t = float(np.mean(np.abs(pred[..., 0:3] - Y[..., 0:3])))
        history.append({"epoch": epoch, "loss": loss, "trans_mae": mae_t})
        if epoch % 25 == 0 or epoch == args.epochs - 1:
            print(f"epoch={epoch} loss={loss:.6f} trans_mae={mae_t:.6f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, w1=model.w1, b1=model.b1, w2=model.w2, b2=model.b2, cfg=json.dumps(model.cfg.__dict__))

    final = history[-1]
    report = {
        "n_samples": len(samples),
        "final_loss": final["loss"],
        "final_trans_mae": final["trans_mae"],
        "initial_loss": history[0]["loss"],
        "overfit_verified": final["loss"] < history[0]["loss"] * 0.25 and final["trans_mae"] < 0.05,
        "checkpoint": str(out),
        "history_tail": history[-5:],
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.report).write_text(
        "\n".join(
            [
                "# QRM-Lite MLP residual refiner",
                "",
                f"- samples: {len(samples)}",
                f"- final loss: {final['loss']:.6f} (from {history[0]['loss']:.6f})",
                f"- translation MAE: {final['trans_mae']:.6f}",
                f"- overfit_verified: {report['overfit_verified']}",
                f"- checkpoint: `{out}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["overfit_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
