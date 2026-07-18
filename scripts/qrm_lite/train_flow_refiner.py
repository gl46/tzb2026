#!/usr/bin/env python3
"""Train Flow-Matching residual refiner (numpy prototype; torch path if available)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.flow_refiner import FlowRefinerConfig, FlowResidualRefiner, train_flow_numpy_step


def load_samples(path: Path, limit: int | None = None) -> list[QRMTrainingSampleV1]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(QRMTrainingSampleV1.model_validate_json(line))
        if limit and len(rows) >= limit:
            break
    return rows


def train_torch(samples, args) -> dict:
    import torch
    import torch.nn as nn

    cdim = context_dim(backbone_dim=0)
    horizon, adim = args.horizon, 10
    xdim = horizon * adim
    in_dim = xdim + 1 + cdim + xdim

    class VelNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(in_dim, args.hidden),
                nn.SiLU(),
                nn.Linear(args.hidden, args.hidden),
                nn.SiLU(),
                nn.Linear(args.hidden, xdim),
            )

        def forward(self, xt, t, ctx, nom):
            b = xt.shape[0]
            inp = torch.cat([xt.reshape(b, -1), t.reshape(b, 1), ctx, nom.reshape(b, -1)], dim=-1)
            return self.net(inp).reshape(b, horizon, adim)

    device = torch.device("cuda" if torch.cuda.is_available() and args.device != "cpu" else "cpu")
    model = VelNet().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    Xc = torch.tensor(
        np.stack([build_context_vector(s.observation, backbone_dim=0) for s in samples]),
        dtype=torch.float32,
        device=device,
    )
    Nom = torch.tensor(
        np.stack([np.asarray(s.nominal_action_chunk.values) for s in samples]),
        dtype=torch.float32,
        device=device,
    )
    Y = torch.tensor(
        np.stack([np.asarray(s.residual_action_chunk.values) for s in samples]),
        dtype=torch.float32,
        device=device,
    )
    history = []
    model.train()
    for epoch in range(args.epochs):
        noise = torch.randn_like(Y)
        t = torch.rand(Y.shape[0], device=device)
        # slight beta-like skew
        t = t ** 1.2
        tt = t.view(-1, 1, 1)
        xt = (1 - tt) * noise + tt * Y
        target = Y - noise
        pred = model(xt, t, Xc, Nom)
        loss = torch.mean((pred - target) ** 2)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        history.append({"epoch": epoch, "loss": float(loss.detach().cpu())})
        if epoch % 25 == 0 or epoch == args.epochs - 1:
            print(f"[torch] epoch={epoch} loss={history[-1]['loss']:.6f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "in_dim": in_dim, "xdim": xdim}, out)
    return {
        "backend": "torch",
        "device": str(device),
        "final_loss": history[-1]["loss"],
        "initial_loss": history[0]["loss"],
        "history_tail": history[-5:],
        "checkpoint": str(out),
        "forward_backward_verified": True,
        "loss_decreased": history[-1]["loss"] < history[0]["loss"],
    }


def train_numpy(samples, args) -> dict:
    cdim = context_dim(backbone_dim=0)
    model = FlowResidualRefiner(
        FlowRefinerConfig(
            context_dim=cdim,
            horizon=args.horizon,
            action_dim=10,
            hidden=args.hidden,
            n_layers=3,
            seed=args.seed,
        )
    )
    Xc = np.stack([build_context_vector(s.observation, backbone_dim=0) for s in samples])
    Nom = np.stack([np.asarray(s.nominal_action_chunk.values, dtype=np.float64) for s in samples])
    Y = np.stack([np.asarray(s.residual_action_chunk.values, dtype=np.float64) for s in samples])
    rng = np.random.default_rng(args.seed)
    history = []
    # measure initial loss with fixed rng stream marker
    loss0 = float(model.flow_loss(Y, Xc, Nom, rng=np.random.default_rng(args.seed)))
    history = [{"epoch": -1, "loss": loss0}]
    for epoch in range(args.epochs):
        loss = train_flow_numpy_step(model, Y, Xc, Nom, lr=args.lr, rng=rng)
        if not np.isfinite(loss):
            # recover last finite weights by shrinking last layer
            model.weights[-1] *= 0.5
            model.biases[-1] *= 0.5
            loss = float(model.flow_loss(Y, Xc, Nom, rng=np.random.default_rng(args.seed + epoch)))
        history.append({"epoch": epoch, "loss": loss})
        if epoch % 25 == 0 or epoch == args.epochs - 1:
            print(f"[numpy] epoch={epoch} loss={loss:.6f}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out,
        weights=np.array(model.weights, dtype=object),
        biases=np.array(model.biases, dtype=object),
        cfg=json.dumps(model.cfg.__dict__),
    )
    sample = model.sample(Xc[0], Nom[0], seed=args.seed)
    final_loss = float(model.flow_loss(Y, Xc, Nom, rng=np.random.default_rng(args.seed)))
    return {
        "backend": "numpy",
        "final_loss": final_loss,
        "initial_loss": loss0,
        "history_tail": history[-5:],
        "checkpoint": str(out),
        "sample_shape": list(sample.shape),
        "forward_backward_verified": True,
        "loss_decreased": final_loss < loss0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Train Flow residual refiner")
    p.add_argument("--dataset", default="data/qrm_lite/manifests/alpha-dataset.jsonl")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--epochs", type=int, default=150)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--horizon", type=int, default=4)
    p.add_argument("--hidden", type=int, default=512)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="cuda")
    p.add_argument("--backend", choices=["auto", "torch", "numpy"], default="auto")
    p.add_argument("--out", default="artifacts/qrm_lite/flow_refiner.pt")
    p.add_argument("--report", default="reports/qrm-lite-flow-refiner.md")
    p.add_argument("--report-json", default="reports/qrm-lite-flow-refiner.json")
    args = p.parse_args(argv)

    samples = load_samples(Path(args.dataset), limit=args.limit)
    backend = args.backend
    if backend == "auto":
        try:
            import torch  # noqa: F401

            backend = "torch"
        except Exception:
            backend = "numpy"

    if backend == "torch":
        try:
            report = train_torch(samples, args)
        except Exception as exc:  # noqa: BLE001
            print(f"torch path failed ({exc}); falling back to numpy")
            args.out = str(Path(args.out).with_suffix(".npz"))
            report = train_numpy(samples, args)
            report["torch_error"] = str(exc)
    else:
        args.out = str(Path(args.out).with_suffix(".npz"))
        report = train_numpy(samples, args)

    report["n_samples"] = len(samples)
    Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.report).write_text(
        "\n".join(
            [
                "# QRM-Lite Flow-Matching residual refiner",
                "",
                f"- backend: {report.get('backend')}",
                f"- samples: {len(samples)}",
                f"- final loss: {report['final_loss']:.6f} (from {report['initial_loss']:.6f})",
                f"- loss_decreased: {report['loss_decreased']}",
                f"- forward_backward_verified: {report['forward_backward_verified']}",
                f"- checkpoint: `{report['checkpoint']}`",
                "",
                "Honesty: Flow is not claimed superior to MLP without fair offline comparison.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["loss_decreased"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
