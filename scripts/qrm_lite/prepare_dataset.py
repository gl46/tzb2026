#!/usr/bin/env python3
"""Build QRM-Lite alpha dataset from existing logs + synthetic geometric fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import translation_bins_from_delta
from xh_agent.policy.qrm_lite.contracts import (
    CameraFrameActionChunkV1,
    CoarseIntentV1,
    FailureContextV1,
    FailureType,
    HistoryStepV1,
    PerceptionTrackV1,
    QRMObservationV1,
    QRMTrainingSampleV1,
)
from xh_agent.policy.qrm_lite.transforms import build_identity_action_chunk, pose_xyzquat_to_mat


SKILLS = ["APPROACH", "GRASP", "LIFT", "MOVE", "PLACE", "RELEASE", "REGRASP", "REOBSERVE"]
FAILS = [
    FailureType.NONE,
    FailureType.EMPTY_GRASP,
    FailureType.DROP_OR_SLIP,
    FailureType.RELEASE_FAILURE,
    FailureType.UNSTABLE_PLACEMENT,
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _base_T_cam() -> list[float]:
    # Simple look-down camera above table
    T = np.eye(4)
    T[:3, 3] = np.array([0.5, 0.0, 0.9])
    # camera optical: z forward down-ish
    # rotation: x right, y down, z forward (approx look at origin)
    yaw = math.pi
    pitch = math.pi / 2
    Rz = np.array(
        [[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]]
    )
    Ry = np.array(
        [
            [math.cos(pitch), 0, math.sin(pitch)],
            [0, 1, 0],
            [-math.sin(pitch), 0, math.cos(pitch)],
        ]
    )
    T[:3, :3] = Rz @ Ry
    return T.reshape(-1).tolist()


def _make_chunk(
    horizon: int,
    residual_scale: float,
    rng: random.Random,
    *,
    skill: str = "APPROACH",
    fail: FailureType = FailureType.NONE,
) -> list[list[float]]:
    """Deterministic-ish residual so context features can overfit.

    Residuals are a function of skill/failure (+ small seeded noise), not pure noise.
    """
    skill_hash = sum(ord(c) for c in skill) % 7
    fail_hash = list(FailureType).index(fail) if fail in list(FailureType) else 0
    base = np.array(
        [
            0.01 * ((skill_hash % 3) - 1),
            0.01 * ((fail_hash % 3) - 1),
            -0.015 if skill in {"APPROACH", "GRASP"} else 0.01,
        ],
        dtype=np.float64,
    )
    rows = []
    for t in range(horizon):
        noise = np.array([rng.uniform(-0.003, 0.003) for _ in range(3)], dtype=np.float64)
        d = np.clip(base * residual_scale / 0.03 + noise, -residual_scale, residual_scale)
        # residual r6d is a *delta from identity* (near zeros), not absolute 6D.
        r6d = [
            0.0,
            0.02 * (fail_hash - 4) / 10.0,
            0.0,
            0.0,
            0.02 * (skill_hash - 3) / 10.0,
            0.0,
        ]
        if skill in {"GRASP", "RELEASE"}:
            grip = 1.0 if skill == "GRASP" else 0.0
        elif fail == FailureType.EMPTY_GRASP:
            grip = 0.2
        else:
            grip = 0.5
        # slight time progression
        d = d * (1.0 + 0.05 * t)
        rows.append([float(d[0]), float(d[1]), float(d[2]), *r6d, float(grip)])
    return rows


def _map_failure(raw: str | None) -> FailureType:
    if not raw:
        return FailureType.NONE
    key = raw.upper().replace("-", "_")
    aliases = {
        "EMPTY_GRASP": FailureType.EMPTY_GRASP,
        "DROP": FailureType.DROP_OR_SLIP,
        "SLIP": FailureType.DROP_OR_SLIP,
        "DROP_OR_SLIP": FailureType.DROP_OR_SLIP,
        "RELEASE_FAILURE": FailureType.RELEASE_FAILURE,
        "UNSTABLE_PLACEMENT": FailureType.UNSTABLE_PLACEMENT,
    }
    return aliases.get(key, FailureType.UNKNOWN)


def sample_from_episode_row(row: dict[str, Any], idx: int, horizon: int, rng: random.Random) -> QRMTrainingSampleV1:
    ep = str(row.get("episode_id", f"ep-{idx}"))
    fail = _map_failure(row.get("failure_type"))
    skill = rng.choice(SKILLS)
    residual = _make_chunk(horizon, 0.03, rng, skill=skill, fail=fail)
    nominal = build_identity_action_chunk(horizon).tolist()
    # target = nominal translation + residual translation etc.
    target = []
    for n, r in zip(nominal, residual):
        t = list(n)
        t[0] = n[0] + r[0]
        t[1] = n[1] + r[1]
        t[2] = n[2] + r[2]
        # absolute 6D = identity 6D + residual delta
        for i in range(6):
            t[3 + i] = n[3 + i] + r[3 + i]
        t[9] = r[9]
        target.append(t)
    dx, dy, dz = residual[0][0], residual[0][1], residual[0][2]
    intent = CoarseIntentV1(
        skill_type=skill,
        target_track_id="track-0",
        grasp_family=rng.choice(["top_down", "side", "industrial_detachable"]),
        recovery_mode="reobserve" if fail != FailureType.NONE else "none",
        reobserve_flag=fail != FailureType.NONE,
        coarse_translation_bins=translation_bins_from_delta(dx, dy, dz),
        coarse_rotation_bins=[2, 2, 2],
        failure_type_aux=fail,
    )
    obs = QRMObservationV1(
        episode_id=ep,
        step_id=int(row.get("step_id", 0) or 0),
        instruction=str(row.get("instruction", "pick the red cube and place into the bin")),
        rgb_uri=str(row.get("rgb_uri", f"synthetic://{ep}.png")),
        camera_intrinsics=[525.0, 0, 320.0, 0, 525.0, 240.0, 0, 0, 1],
        camera_extrinsics_base_T_cam=_base_T_cam(),
        joint_position=[0.0] * 7 + [0.04],
        end_effector_pose_base=[0.4, 0.0, 0.35, 1, 0, 0, 0],
        gripper_state=0.0 if skill != "GRASP" else 0.8,
        current_skill_stage=skill,
        perception_tracks=[
            PerceptionTrackV1(track_id="track-0", category="cube", confidence=0.82, pose_xyzquat=[0.35, 0.1, 0.2, 1, 0, 0, 0])
        ],
        history=[
            HistoryStepV1(
                step_id=0,
                end_effector_pose=[0.38, 0.0, 0.4, 1, 0, 0, 0],
                action_summary=[0, 0, -0.01, 1, 0, 0, 0, 1, 0, 0.0],
                skill_type="APPROACH",
            )
        ],
        failure_context=FailureContextV1(
            last_skill=skill,
            expected_predicates=["grasped"] if skill == "GRASP" else [],
            observed_predicates=[] if fail == FailureType.EMPTY_GRASP else ["grasped"] if skill == "LIFT" else [],
            predicate_residual=["missing:grasped"] if fail == FailureType.EMPTY_GRASP else [],
            failure_type=fail,
            retry_count=1 if fail != FailureType.NONE else 0,
            attempted_recoveries=["reobserve"] if fail != FailureType.NONE else [],
            last_action_summary=skill,
            last_target_track_id="track-0",
        ),
    )
    chunk_kwargs = dict(fps=5.0, is_residual=True)
    return QRMTrainingSampleV1(
        sample_id=f"{ep}-{idx}",
        episode_id=ep,
        seed=int(row.get("seed", idx)),
        split="train",
        observation=obs,
        coarse_intent=intent,
        nominal_action_chunk=CameraFrameActionChunkV1(values=nominal, is_residual=False, **{k: v for k, v in chunk_kwargs.items() if k != "is_residual"}),
        residual_action_chunk=CameraFrameActionChunkV1(values=residual, **chunk_kwargs),
        target_action_chunk=CameraFrameActionChunkV1(values=target, is_residual=False, fps=5.0),
        simulator_supervision={
            "task_success": bool(row.get("task_success", fail == FailureType.NONE)),
            "failure_type": fail.value,
            "source_row": {k: row[k] for k in list(row)[:12]},
        },
        provenance={
            "source": str(row.get("source", "episode_log_or_synthetic")),
            "builder": "scripts/qrm_lite/prepare_dataset.py",
        },
        synthetic=bool(row.get("synthetic", True)),
    )


def load_seed_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        elif path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                rows.extend(data)
            elif isinstance(data, dict) and "episodes" in data:
                rows.extend(data["episodes"])
    return rows


def synthesize_rows(n: int, rng: random.Random) -> list[dict[str, Any]]:
    rows = []
    for i in range(n):
        fail = rng.choice(FAILS)
        rows.append(
            {
                "episode_id": f"syn-{i:04d}",
                "failure_type": fail.value,
                "task_success": fail == FailureType.NONE,
                "instruction": rng.choice(
                    [
                        "pick the red cube into bin A",
                        "grasp the metal sleeve and place on tray",
                        "regrasp the dropped gear",
                    ]
                ),
                "seed": i,
                "synthetic": True,
                "source": "geometric_fixture",
            }
        )
    return rows


def assign_splits(samples: list[QRMTrainingSampleV1], val_ratio: float = 0.1) -> None:
    # episode-level split
    episodes = sorted({s.episode_id for s in samples})
    rng = random.Random(0)
    rng.shuffle(episodes)
    n_val = max(1, int(len(episodes) * val_ratio)) if len(episodes) > 5 else max(1, len(episodes) // 5)
    val_set = set(episodes[:n_val])
    for s in samples:
        s.split = "val" if s.episode_id in val_set else "train"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Prepare QRM-Lite alpha dataset")
    p.add_argument("--seed-jsonl", action="append", default=[], help="Existing episode jsonl paths")
    p.add_argument("--n-synthetic", type=int, default=120)
    p.add_argument("--horizon", type=int, default=4)
    p.add_argument("--out-manifest", default="data/qrm_lite/manifests/alpha-dataset.json")
    p.add_argument("--out-jsonl", default="data/qrm_lite/manifests/alpha-dataset.jsonl")
    p.add_argument("--report", default="reports/qrm-lite-dataset.md")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    rng = random.Random(args.seed)
    seed_paths = [Path(x) for x in args.seed_jsonl]
    # default local seed if present
    default_seed = Path("data/episodes/p0-empty-grasp-failures.jsonl")
    if default_seed.exists() and default_seed not in seed_paths:
        seed_paths.append(default_seed)

    rows = load_seed_rows(seed_paths)
    for r in rows:
        r.setdefault("source", "existing_episode_log")
        r.setdefault("synthetic", False)
    if len(rows) < args.n_synthetic:
        rows.extend(synthesize_rows(args.n_synthetic - len(rows), rng))

    samples = [sample_from_episode_row(r, i, args.horizon, rng) for i, r in enumerate(rows)]
    assign_splits(samples)

    out_manifest = Path(args.out_manifest)
    out_jsonl = Path(args.out_jsonl)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(s.model_dump_json() + "\n")

    fail_counts: dict[str, int] = {}
    for s in samples:
        ft = s.observation.failure_context.failure_type.value
        fail_counts[ft] = fail_counts.get(ft, 0) + 1
    summary = {
        "n_samples": len(samples),
        "n_episodes": len({s.episode_id for s in samples}),
        "n_train": sum(1 for s in samples if s.split == "train"),
        "n_val": sum(1 for s in samples if s.split == "val"),
        "failure_counts": fail_counts,
        "synthetic_count": sum(1 for s in samples if s.synthetic),
        "real_log_count": sum(1 for s in samples if not s.synthetic),
        "horizon": args.horizon,
        "action_dim": 10,
        "seed_paths": [str(p) for p in seed_paths],
        "jsonl": str(out_jsonl),
        "manifest_sha": _sha(out_jsonl.read_text(encoding="utf-8")),
    }
    out_manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "\n".join(
            [
                "# QRM-Lite alpha dataset",
                "",
                f"- samples: {summary['n_samples']}",
                f"- episodes: {summary['n_episodes']}",
                f"- train/val: {summary['n_train']}/{summary['n_val']}",
                f"- synthetic: {summary['synthetic_count']} (geometric fixtures, not Gazebo truth)",
                f"- from real logs: {summary['real_log_count']}",
                f"- failure counts: `{json.dumps(fail_counts)}`",
                f"- manifest: `{out_manifest}`",
                f"- jsonl: `{out_jsonl}`",
                "",
                "Split is by episode_id, not random adjacent frames.",
                "Online observations do not include simulator perfect poses.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
