#!/usr/bin/env python3
"""Train formal Q0/Q1/Q2 models on QRM-Real-V1 (numpy path for bring-up; chxy torch later)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import encode_coarse_intent
from xh_agent.policy.qrm_lite.context import build_context_vector
from xh_agent.policy.qrm_lite.contracts import FailureContextV1, QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.metrics_beta1 import macro_f1, residual_errors, skill_accuracy, zero_residual_baseline
from xh_agent.policy.qrm_lite.models_q012 import FormalModelId, FormalPolicy, build_formal_model


def load_samples(path: Path, split: str | None = None, limit: int | None = None) -> list[QRMTrainingSampleV1]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = QRMTrainingSampleV1.model_validate_json(line)
        if split and s.split != split:
            continue
        rows.append(s)
        if limit and len(rows) >= limit:
            break
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ctx_matrix(model: FormalPolicy, samples: list[QRMTrainingSampleV1]) -> np.ndarray:
    rows = []
    for s in samples:
        obs = s.observation
        if model.model_id != FormalModelId.Q2:
            obs = obs.model_copy(deep=True)
            obs.failure_context = FailureContextV1()
        rows.append(
            build_context_vector(
                obs,
                backbone_dim=model.cfg.backbone_dim,
                joint_dim=model.cfg.joint_dim,
                history_len=model.cfg.history_len,
                action_dim=model.cfg.action_dim,
            )
        )
    return np.stack(rows)


def train_coarse(model: FormalPolicy, samples: list[QRMTrainingSampleV1], epochs: int, lr: float) -> dict:
    X = _ctx_matrix(model, samples)
    Y = np.stack([encode_coarse_intent(s.coarse_intent, model.label_space) for s in samples])
    hist = []
    for epoch in range(epochs):
        logits = model.coarse.forward(X)
        err = logits - Y
        loss = float(np.mean(err**2))
        dlogits = (2.0 / err.size) * err
        h = np.tanh(np.clip(X @ model.coarse.w1 + model.coarse.b1, -20, 20))
        dw2 = np.clip(h.T @ dlogits, -1, 1)
        db2 = np.clip(dlogits.sum(0), -1, 1)
        dh = dlogits @ model.coarse.w2.T * (1 - h**2)
        dw1 = np.clip(X.T @ dh, -1, 1)
        db1 = np.clip(dh.sum(0), -1, 1)
        model.coarse.w2 -= lr * dw2
        model.coarse.b2 -= lr * db2
        model.coarse.w1 -= lr * dw1
        model.coarse.b1 -= lr * db1
        skill_n = len(model.label_space.skills)
        pred = np.argmax(logits[:, :skill_n], 1)
        true = np.argmax(Y[:, :skill_n], 1)
        acc = float(np.mean(pred == true))
        hist.append({"epoch": epoch, "loss": loss, "skill_acc": acc})
        if epoch % 50 == 0 or epoch == epochs - 1:
            print(f"[{model.model_id.value}] coarse epoch={epoch} loss={loss:.5f} acc={acc:.3f}")
    return {"history_tail": hist[-5:], "final": hist[-1], "initial": hist[0]}


def train_mlp(model: FormalPolicy, samples: list[QRMTrainingSampleV1], epochs: int, lr: float) -> dict:
    X = _ctx_matrix(model, samples)
    Nom = np.stack([np.asarray(s.nominal_action_chunk.values) for s in samples])
    Y = np.stack([np.asarray(s.residual_action_chunk.values) for s in samples])
    hist = []
    for epoch in range(epochs):
        B = X.shape[0]
        n_flat = Nom.reshape(B, -1)
        x = np.concatenate([X, n_flat], axis=-1)
        h = np.tanh(np.clip(x @ model.mlp.w1 + model.mlp.b1, -20, 20))
        raw = (h @ model.mlp.w2 + model.mlp.b2).reshape(B, model.cfg.horizon, model.cfg.action_dim)
        err = raw - Y
        loss = float(np.mean(err**2))
        dpred = (2.0 / err.size) * err.reshape(B, -1)
        dw2 = np.clip(h.T @ dpred, -1, 1)
        db2 = np.clip(dpred.sum(0), -1, 1)
        dh = dpred @ model.mlp.w2.T * (1 - h**2)
        dw1 = np.clip(x.T @ dh, -1, 1)
        db1 = np.clip(dh.sum(0), -1, 1)
        model.mlp.w2 -= lr * dw2
        model.mlp.b2 -= lr * db2
        model.mlp.w1 -= lr * dw1
        model.mlp.b1 -= lr * db1
        pred = model.mlp.forward(X, Nom)
        mae = float(np.mean(np.abs(pred[..., 0:3] - Y[..., 0:3])))
        hist.append({"epoch": epoch, "loss": loss, "trans_mae": mae})
        if epoch % 50 == 0 or epoch == epochs - 1:
            print(f"[{model.model_id.value}] mlp epoch={epoch} loss={loss:.5f} mae={mae:.5f}")
    zbase = zero_residual_baseline(Y)
    pred = model.mlp.forward(X, Nom)
    return {
        "history_tail": hist[-5:],
        "final": hist[-1],
        "initial": hist[0],
        "residual_errors": residual_errors(pred, Y),
        "zero_residual_baseline": zbase,
        "beats_zero_residual": residual_errors(pred, Y)["l1"] < zbase["l1"],
    }


def eval_skills(model: FormalPolicy, samples: list[QRMTrainingSampleV1]) -> dict:
    y_true = [s.coarse_intent.skill_type for s in samples]
    y_pred = []
    for s in samples:
        out = model.predict(
            s.observation,
            nominal=np.asarray(s.nominal_action_chunk.values) if model.uses_residual else None,
        )
        y_pred.append(out.coarse.skill_type if out.coarse else "")
    return {
        "skill_accuracy": skill_accuracy(y_true, y_pred),
        "macro_f1": macro_f1(y_true, y_pred),
        "n": len(samples),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Train Q0/Q1/Q2 formal models")
    p.add_argument("--dataset", default="data/qrm_lite/manifests/real-v1.jsonl")
    p.add_argument("--models", default="Q0,Q1,Q2", help="comma list of Q0,Q1,Q2")
    p.add_argument("--epochs-coarse", type=int, default=300)
    p.add_argument("--epochs-mlp", type=int, default=400)
    p.add_argument("--lr", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=20260731)
    p.add_argument("--out-dir", default="artifacts/qrm_lite/beta1")
    p.add_argument("--report", default="reports/qrm-lite-beta1-q012-train.md")
    p.add_argument("--report-json", default="reports/qrm-lite-beta1-q012-train.json")
    args = p.parse_args(argv)

    np.random.seed(args.seed)
    dataset_path = Path(args.dataset)
    all_samples = load_samples(dataset_path)
    train = [sample for sample in all_samples if sample.split == "train"]
    val = [sample for sample in all_samples if sample.split == "val"] or [
        sample for sample in all_samples if sample.split == "test"
    ]
    if not train:
        # fallback: all
        train = all_samples
        val = train[: max(1, len(train) // 5)]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_hashes = sorted(
        {
            str(sample.provenance.get("dataset_manifest_hash", ""))
            for sample in all_samples
        }
    )
    report: dict = {
        "schema_version": "QRMLiteBetaQ012TrainV2",
        "status": "PASS",
        "dataset": args.dataset,
        "dataset_sha256": sha256_file(dataset_path),
        "dataset_manifest_hashes": manifest_hashes,
        "seed": args.seed,
        "n_samples": len(all_samples),
        "n_train": len(train),
        "n_val": len(val),
        "synthetic_samples": sum(sample.synthetic for sample in all_samples),
        "models": {},
    }

    wanted = [m.strip().upper() for m in args.models.split(",") if m.strip()]
    id_map = {
        "Q0": FormalModelId.Q0,
        "Q1": FormalModelId.Q1,
        "Q2": FormalModelId.Q2,
        "Q0_COARSE_ONLY": FormalModelId.Q0,
        "Q1_COARSE_MLP_RESIDUAL": FormalModelId.Q1,
        "Q2_COARSE_MLP_FAILURE_CONTEXT": FormalModelId.Q2,
    }

    for key in wanted:
        mid = id_map[key]
        model = build_formal_model(mid)
        coarse_stats = train_coarse(model, train, args.epochs_coarse, args.lr)
        mlp_stats = None
        if model.uses_residual:
            mlp_stats = train_mlp(model, train, args.epochs_mlp, args.lr * 0.5)
        val_stats = eval_skills(model, val)
        # save weights
        ckpt = out_dir / f"{mid.name}.npz"
        np.savez(
            ckpt,
            model_id=mid.value,
            coarse_w1=model.coarse.w1,
            coarse_b1=model.coarse.b1,
            coarse_w2=model.coarse.w2,
            coarse_b2=model.coarse.b2,
            mlp_w1=model.mlp.w1,
            mlp_b1=model.mlp.b1,
            mlp_w2=model.mlp.w2,
            mlp_b2=model.mlp.b2,
        )
        report["models"][mid.value] = {
            "checkpoint": str(ckpt),
            "uses_failure_context": model.uses_failure_context,
            "uses_residual": model.uses_residual,
            "coarse": coarse_stats,
            "mlp": mlp_stats,
            "val": val_stats,
        }

    # majority-class baseline on val
    from collections import Counter

    maj = Counter(s.coarse_intent.skill_type for s in train).most_common(1)[0][0]
    maj_acc = skill_accuracy([s.coarse_intent.skill_type for s in val], [maj] * len(val))
    report["majority_class_baseline_acc"] = maj_acc
    report["flow_status"] = "IMPLEMENTED_NOT_SELECTED"

    Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# QRM-Lite Beta-1 Q0/Q1/Q2 train", ""]
    for mid, st in report["models"].items():
        lines.append(f"## {mid}")
        lines.append(f"- val skill acc: {st['val']['skill_accuracy']:.3f} (macro-F1 {st['val']['macro_f1']:.3f})")
        lines.append(f"- coarse final: `{st['coarse']['final']}`")
        if st["mlp"]:
            lines.append(f"- mlp beats zero residual: {st['mlp']['beats_zero_residual']}")
            lines.append(f"- residual errors: `{st['mlp']['residual_errors']}`")
        lines.append("")
    lines.append(f"Majority baseline acc: {maj_acc:.3f}")
    lines.append("Flow: IMPLEMENTED_NOT_SELECTED")
    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
