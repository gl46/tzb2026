#!/usr/bin/env python3
"""Fair offline comparison between MLP and Flow residual refiners."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.flow_refiner import FlowRefinerConfig, FlowResidualRefiner
from xh_agent.policy.qrm_lite.mlp_refiner import MLPRefinerConfig, MLPResidualRefiner


def load_samples(path: Path) -> list[QRMTrainingSampleV1]:
    return [
        QRMTrainingSampleV1.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def metrics(pred: np.ndarray, target: np.ndarray) -> dict:
    return {
        "translation_mae": float(np.mean(np.abs(pred[..., 0:3] - target[..., 0:3]))),
        "rotation_r6d_mae": float(np.mean(np.abs(pred[..., 3:9] - target[..., 3:9]))),
        "gripper_mae": float(np.mean(np.abs(pred[..., 9] - target[..., 9]))),
        "chunk_endpoint_trans_mae": float(np.mean(np.abs(pred[:, -1, 0:3] - target[:, -1, 0:3]))),
        "mse": float(np.mean((pred - target) ** 2)),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline MLP vs Flow evaluation")
    p.add_argument("--dataset", default="data/qrm_lite/manifests/alpha-dataset.jsonl")
    p.add_argument("--split", default="val")
    p.add_argument("--mlp-ckpt", default="artifacts/qrm_lite/mlp_refiner.npz")
    p.add_argument("--flow-ckpt", default="artifacts/qrm_lite/flow_refiner.npz")
    p.add_argument("--report", default="reports/qrm-lite-mlp-vs-flow.md")
    p.add_argument("--report-json", default="reports/qrm-lite-mlp-vs-flow.json")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    samples = [s for s in load_samples(Path(args.dataset)) if s.split == args.split]
    if not samples:
        samples = load_samples(Path(args.dataset))[:20]

    cdim = context_dim(backbone_dim=0)
    Xc = np.stack([build_context_vector(s.observation, backbone_dim=0) for s in samples])
    Nom = np.stack([np.asarray(s.nominal_action_chunk.values) for s in samples])
    Y = np.stack([np.asarray(s.residual_action_chunk.values) for s in samples])

    mlp = MLPResidualRefiner(MLPRefinerConfig(context_dim=cdim, horizon=Y.shape[1], action_dim=10))
    if Path(args.mlp_ckpt).exists():
        data = np.load(args.mlp_ckpt, allow_pickle=True)
        mlp.w1, mlp.b1, mlp.w2, mlp.b2 = data["w1"], data["b1"], data["w2"], data["b2"]
    pred_mlp = mlp.forward(Xc, Nom)

    flow = FlowResidualRefiner(FlowRefinerConfig(context_dim=cdim, horizon=Y.shape[1], action_dim=10, seed=args.seed))
    if Path(args.flow_ckpt).exists() and args.flow_ckpt.endswith(".npz"):
        data = np.load(args.flow_ckpt, allow_pickle=True)
        # best-effort load
        try:
            flow.weights = list(data["weights"])
            flow.biases = list(data["biases"])
        except Exception:
            pass
    pred_flow = np.stack([flow.sample(Xc[i], Nom[i], seed=args.seed + i) for i in range(len(samples))])

    m_mlp = metrics(pred_mlp, Y)
    m_flow = metrics(pred_flow, Y)
    flow_better = m_flow["mse"] < m_mlp["mse"] * 0.95 and m_flow["translation_mae"] <= m_mlp["translation_mae"]

    report = {
        "n_eval": len(samples),
        "split": args.split,
        "mlp": m_mlp,
        "flow": m_flow,
        "flow_outperforms_mlp_preliminary": flow_better,
        "same_split": True,
        "note": "If Flow is not better, do not market diffusion as the core innovation.",
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.report).write_text(
        "\n".join(
            [
                "# QRM-Lite MLP vs Flow (offline)",
                "",
                f"- n_eval: {len(samples)}",
                f"- MLP: `{json.dumps(m_mlp)}`",
                f"- Flow: `{json.dumps(m_flow)}`",
                f"- flow_outperforms_mlp_preliminary: **{flow_better}**",
                "",
                "> 如果 Flow head 没有稳定优于 MLP residual baseline，就不把扩散式动作生成包装成项目核心创新。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
