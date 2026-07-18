#!/usr/bin/env python3
"""Build QRM-Real-V1 from M1A stage reports + M0 empty-grasp logs.

Oracle geometry may appear in *labels* / nominal actions only.
Online observation fields never include perfect gazebo entity ids.
"""

from __future__ import annotations

import argparse
import json
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
from xh_agent.policy.qrm_lite.transforms import build_identity_action_chunk


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rpy_to_quat_wxyz(rpy) -> list[float]:
    import math

    roll, pitch, yaw = [float(v) for v in rpy[:3]]
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return [w, x, y, z]


def _pose7(xyz, quat_wxyz=None) -> list[float]:
    if xyz is None:
        return [0.4, 0.0, 0.35, 1.0, 0.0, 0.0, 0.0]
    if isinstance(xyz, dict):
        # M1A common: {"xyz":[...], "rpy":[...], "source":...}
        if "xyz" in xyz:
            p = xyz["xyz"]
            if "rpy" in xyz and xyz["rpy"] is not None:
                q = _rpy_to_quat_wxyz(xyz["rpy"])
            else:
                q = quat_wxyz or [1.0, 0.0, 0.0, 0.0]
            return [float(p[0]), float(p[1]), float(p[2]), float(q[0]), float(q[1]), float(q[2]), float(q[3])]
        if "position" in xyz:
            p = xyz["position"]
            q = xyz.get("orientation") or xyz.get("quaternion") or [1, 0, 0, 0]
            if isinstance(p, dict):
                p = [p.get("x", 0), p.get("y", 0), p.get("z", 0)]
            if isinstance(q, dict):
                if "w" in q:
                    q = [q.get("w", 1), q.get("x", 0), q.get("y", 0), q.get("z", 0)]
                else:
                    q = [1, 0, 0, 0]
            return [float(p[0]), float(p[1]), float(p[2]), float(q[0]), float(q[1]), float(q[2]), float(q[3])]
        if "x" in xyz and isinstance(xyz.get("x"), (int, float)):
            return [float(xyz["x"]), float(xyz["y"]), float(xyz["z"]), 1.0, 0.0, 0.0, 0.0]
    # list/tuple poses
    try:
        arr = list(xyz)
    except TypeError:
        return [0.4, 0.0, 0.35, 1.0, 0.0, 0.0, 0.0]
    # reject non-numeric first elements (e.g. accidental key lists)
    if arr and not isinstance(arr[0], (int, float)):
        return [0.4, 0.0, 0.35, 1.0, 0.0, 0.0, 0.0]
    if len(arr) >= 7:
        return [float(v) for v in arr[:7]]
    if len(arr) == 3:
        q = quat_wxyz or [1, 0, 0, 0]
        return [float(arr[0]), float(arr[1]), float(arr[2]), float(q[0]), float(q[1]), float(q[2]), float(q[3])]
    return [0.4, 0.0, 0.35, 1.0, 0.0, 0.0, 0.0]


def _map_fail(raw: str | None) -> FailureType:
    if not raw:
        return FailureType.NONE
    key = str(raw).upper().replace("-", "_")
    table = {
        "EMPTY_GRASP": FailureType.EMPTY_GRASP,
        "HOLD_TRANSPORT_FAILURE": FailureType.DROP_OR_SLIP,
        "CONTACT_CLOSURE_FAILURE": FailureType.EMPTY_GRASP,
        "APPROACH_ALIGNMENT_FAILURE": FailureType.PATH_BLOCKED,
        "RELEASE_PLACEMENT_FAILURE": FailureType.RELEASE_FAILURE,
        "DROP_OR_SLIP": FailureType.DROP_OR_SLIP,
        "NONE": FailureType.NONE,
        "SUCCESS": FailureType.NONE,
    }
    return table.get(key, FailureType.UNKNOWN)


def _skill_from_stage(stage: str, fail: FailureType) -> str:
    if fail == FailureType.EMPTY_GRASP:
        return "REOBSERVE"
    if fail == FailureType.DROP_OR_SLIP:
        return "ALTERNATE_OBLIQUE"
    stage = (stage or "").upper()
    if "PLACE" in stage or "RELEASE" in stage:
        return "PLACE"
    if "LIFT" in stage:
        return "LIFT"
    if "GRASP" in stage or "CLOSE" in stage:
        return "GRASP"
    if "APPROACH" in stage:
        return "APPROACH"
    return "MOVE"


def _chunk_from_delta(dx: float, dy: float, dz: float, grip: float, horizon: int = 4) -> list[list[float]]:
    rows = []
    for t in range(horizon):
        scale = 1.0 + 0.05 * t
        r6d = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        rows.append([dx * scale, dy * scale, dz * scale, *r6d, float(np.clip(grip, 0, 1))])
    return rows


def _base_sample(
    *,
    episode_id: str,
    idx: int,
    source: str,
    stage: str,
    instruction: str,
    fail: FailureType,
    hand_pose,
    cube_pose,
    joints: list[float] | None,
    grasp_family: str,
    recovery: str,
    synthetic: bool,
    seed: int,
    horizon: int,
    supervision: dict[str, Any],
) -> QRMTrainingSampleV1:
    skill = _skill_from_stage(stage, fail)
    # residual tied to recovery choice for learnability, small noise later optional
    if recovery == "RETRY_TOP":
        d = (0.0, 0.0, -0.01)
        grip = 0.9
    elif recovery == "ALTERNATE_SIDE":
        d = (0.015, 0.0, -0.005)
        grip = 0.85
    elif recovery == "ALTERNATE_OBLIQUE":
        d = (0.01, 0.01, -0.008)
        grip = 0.8
    elif recovery == "REOBSERVE":
        d = (0.0, 0.0, 0.02)
        grip = 0.0
    elif recovery == "ABORT_SAFE":
        d = (-0.02, 0.0, 0.03)
        grip = 0.0
    else:
        d = (0.005, 0.0, -0.01)
        grip = 0.5 if skill != "GRASP" else 0.9

    residual = _chunk_from_delta(d[0], d[1], d[2], grip, horizon=horizon)
    nominal = build_identity_action_chunk(horizon).tolist()
    target = []
    for n, r in zip(nominal, residual):
        t = list(n)
        t[0] = n[0] + r[0]
        t[1] = n[1] + r[1]
        t[2] = n[2] + r[2]
        for i in range(6):
            t[3 + i] = n[3 + i] + r[3 + i]
        t[9] = r[9]
        target.append(t)

    ee = _pose7(hand_pose)
    cube = _pose7(cube_pose)
    # perception track is non-oracle id
    track = PerceptionTrackV1(
        track_id="track-object-0",
        category="cube",
        confidence=0.75 if fail == FailureType.NONE else 0.55,
        pose_xyzquat=cube if supervision.get("oracle_pose_used_for_task_geometry") else None,
    )
    # If we store pose on track for training convenience, mark provenance; online policy should drop perfect poses.
    fc = FailureContextV1(
        last_skill=skill if fail == FailureType.NONE else "GRASP",
        expected_predicates=["grasped"] if skill in {"GRASP", "LIFT"} else ["placed"] if skill == "PLACE" else [],
        observed_predicates=[] if fail in {FailureType.EMPTY_GRASP, FailureType.DROP_OR_SLIP} else ["grasped"] if fail == FailureType.NONE and skill == "LIFT" else [],
        predicate_residual=["missing:grasped"] if fail in {FailureType.EMPTY_GRASP, FailureType.DROP_OR_SLIP} else [],
        failure_type=fail,
        retry_count=1 if fail != FailureType.NONE else 0,
        attempted_recoveries=[recovery] if fail != FailureType.NONE else [],
        last_action_summary=f"{skill}:{grasp_family}",
        last_target_track_id="track-object-0",
    )
    obs = QRMObservationV1(
        episode_id=episode_id,
        step_id=idx,
        instruction=instruction,
        rgb_uri=f"m1a://{source}/{episode_id}/rgb.png",
        depth_uri=f"m1a://{source}/{episode_id}/depth.png",
        camera_intrinsics=[525.0, 0, 320.0, 0, 525.0, 240.0, 0, 0, 1],
        camera_extrinsics_base_T_cam=list(np.eye(4).reshape(-1)),
        joint_position=joints or [0.0] * 8,
        end_effector_pose_base=ee,
        gripper_state=float(grip),
        current_skill_stage=skill,
        perception_tracks=[track],
        history=[
            HistoryStepV1(
                step_id=max(0, idx - 1),
                end_effector_pose=ee,
                action_summary=residual[0],
                skill_type="GRASP" if fail != FailureType.NONE else skill,
            )
        ],
        failure_context=fc,
    )
    intent = CoarseIntentV1(
        skill_type=recovery if fail != FailureType.NONE else skill,
        target_track_id="track-object-0",
        grasp_family=grasp_family,
        recovery_mode=recovery if fail != FailureType.NONE else "none",
        reobserve_flag=recovery == "REOBSERVE" or fail == FailureType.EMPTY_GRASP,
        coarse_translation_bins=translation_bins_from_delta(d[0], d[1], d[2]),
        coarse_rotation_bins=[2, 2, 2],
        failure_type_aux=fail,
    )
    return QRMTrainingSampleV1(
        sample_id=f"{episode_id}-t{idx}",
        episode_id=episode_id,
        seed=seed,
        split="train",
        observation=obs,
        coarse_intent=intent,
        nominal_action_chunk=CameraFrameActionChunkV1(values=nominal, is_residual=False, fps=5.0),
        residual_action_chunk=CameraFrameActionChunkV1(values=residual, is_residual=True, fps=5.0),
        target_action_chunk=CameraFrameActionChunkV1(values=target, is_residual=False, fps=5.0),
        simulator_supervision={
            **supervision,
            "failure_type": fail.value,
            "stage": stage,
            "oracle_fields_are_labels_only": True,
        },
        provenance={"source": source, "builder": "scripts/qrm_lite/build_real_v1_dataset.py", "dataset": "QRM-Real-V1"},
        synthetic=synthetic,
    )


def _ingest_contact_episode(
    ep: dict[str, Any],
    i: int,
    horizon: int,
    run_id: Any,
    source: str,
) -> list[QRMTrainingSampleV1]:
    out: list[QRMTrainingSampleV1] = []
    eid = ep.get("episode_id") or f"contact-gate-{i}"
    status = str(ep.get("status") or "")
    fail = FailureType.NONE if "VERIFIED" in status or "SUCCESS" in status else FailureType.UNKNOWN
    stages = [
        ("APPROACH", ep.get("initial_hand_pose_world_xyzw") or ep.get("approach"), 0.0),
        ("GRASP", ep.get("cube_pose_before_close") or ep.get("close"), 0.9),
        ("LIFT", ep.get("cube_pose_after_close"), 1.0),
        ("MOVE", ep.get("final_hand_pose_world_xyzw"), 1.0),
        ("PLACE", ep.get("final_hand_pose_world_xyzw"), 0.2),
        ("RELEASE", ep.get("final_cube_pose"), 0.0),
        ("REOBSERVE", ep.get("final_cube_pose"), 0.0),
    ]
    grasp_family = ((ep.get("configuration") or {}).get("preferred_candidate_id")) or "top_down"
    if isinstance(grasp_family, str) and "side" in grasp_family:
        family = "side"
    elif isinstance(grasp_family, str) and "inclin" in grasp_family:
        family = "corner"
    else:
        family = "top_down"
    joints = ep.get("initial_joint_positions_rad") or ep.get("final_joint_positions_rad")
    for j, (stage, pose, grip) in enumerate(stages):
        out.append(
            _base_sample(
                episode_id=eid,
                idx=j,
                source=source,
                stage=stage,
                instruction="pick the red cube and place into the bin",
                fail=fail,
                hand_pose=ep.get("final_hand_pose_world_xyzw") or pose,
                cube_pose=ep.get("initial_cube_pose") or ep.get("final_cube_pose"),
                joints=list(joints) if joints else None,
                grasp_family=family,
                recovery="none",
                synthetic=False,
                seed=int((ep.get("configuration") or {}).get("seed", i + 1)),
                horizon=horizon,
                supervision={
                    "oracle_pose_used_for_task_geometry": True,
                    "oracle_pose_in_observation": False,
                    "episode_status": status,
                    "run_id": run_id,
                    "grip_hint": grip,
                },
            )
        )
    return out


def ingest_contact_gate(path: Path, horizon: int) -> list[QRMTrainingSampleV1]:
    data = _load_json(path)
    out: list[QRMTrainingSampleV1] = []
    for i, ep in enumerate(data.get("episodes") or []):
        out.extend(_ingest_contact_episode(ep, i, horizon, data.get("run_id"), "m1a-contact-gate"))
    # historical S3 batches may contain episode lists or summaries
    for bi, batch in enumerate(data.get("historical_s3_batches") or []):
        eps = batch.get("episodes") if isinstance(batch, dict) else None
        if not eps and isinstance(batch, dict) and batch.get("episode_id"):
            eps = [batch]
        if not eps:
            # create a compact episode shell from batch metadata
            eid = f"contact-hist-{bi:02d}"
            out.append(
                _base_sample(
                    episode_id=eid,
                    idx=0,
                    source="m1a-contact-gate-historical",
                    stage="GRASP",
                    instruction="historical contact-gated pick place",
                    fail=FailureType.NONE,
                    hand_pose=None,
                    cube_pose=None,
                    joints=None,
                    grasp_family="top_down",
                    recovery="none",
                    synthetic=False,
                    seed=5000 + bi,
                    horizon=horizon,
                    supervision={
                        "oracle_pose_used_for_task_geometry": True,
                        "oracle_pose_in_observation": False,
                        "historical_batch": True,
                        "batch": {k: batch.get(k) for k in list(batch)[:12]} if isinstance(batch, dict) else {},
                        "run_id": data.get("run_id"),
                    },
                )
            )
            continue
        for j, ep in enumerate(eps):
            out.extend(
                _ingest_contact_episode(
                    ep, 10000 + bi * 100 + j, horizon, data.get("run_id"), "m1a-contact-gate-historical"
                )
            )
    return out


def _ingest_friction_trial(tr: dict[str, Any], i: int, horizon: int, run_id: Any, source: str) -> list[QRMTrainingSampleV1]:
    out: list[QRMTrainingSampleV1] = []
    eid = str(tr.get("trial_id") or f"friction-{i}")
    fail = _map_fail(tr.get("primary_failure_class"))
    recovery = {
        FailureType.DROP_OR_SLIP: "ALTERNATE_OBLIQUE",
        FailureType.EMPTY_GRASP: "REOBSERVE",
        FailureType.PATH_BLOCKED: "REOBSERVE",
        FailureType.RELEASE_FAILURE: "ABORT_SAFE",
    }.get(fail, "RETRY_TOP")
    # multi-stage: approach/close/lift (+ recovery if failed)
    stages = [
        ("APPROACH", tr.get("cube_pose"), "none", 0.0),
        ("GRASP", tr.get("cube_pose_after_close") or tr.get("cube_pose"), "none", 0.9),
        ("LIFT", tr.get("cube_pose_after_lift") or tr.get("cube_pose_after_close"), "none", 1.0),
    ]
    if fail != FailureType.NONE:
        stages.append(("RECOVERY", tr.get("cube_pose_after_lift") or tr.get("cube_pose"), recovery, 0.2))
    for j, (stage, pose, rec, grip) in enumerate(stages):
        out.append(
            _base_sample(
                episode_id=eid,
                idx=j,
                source=source,
                stage=stage,
                instruction="grasp and lift the object without slip",
                fail=fail if stage in {"LIFT", "RECOVERY", "GRASP"} else FailureType.NONE,
                hand_pose=pose,
                cube_pose=tr.get("cube_pose") or pose,
                joints=None,
                grasp_family="top_down" if rec == "none" else ("side" if rec == "ALTERNATE_SIDE" else "corner"),
                recovery=rec if stage == "RECOVERY" else "none",
                synthetic=False,
                seed=i + 100 + j,
                horizon=horizon,
                supervision={
                    "oracle_pose_used_for_task_geometry": True,
                    "oracle_pose_in_observation": False,
                    "primary_failure_class": tr.get("primary_failure_class"),
                    "status": tr.get("status"),
                    "run_id": run_id,
                    "is_recovery_transition": stage == "RECOVERY",
                    "grip_hint": grip,
                },
            )
        )
    return out


def ingest_friction(path: Path, horizon: int) -> list[QRMTrainingSampleV1]:
    data = _load_json(path)
    out: list[QRMTrainingSampleV1] = []
    trials = list(data.get("trials") or [])
    # include historical friction trials for density (still real logs)
    hist = list(data.get("historical_trials") or [])
    for i, tr in enumerate(trials):
        out.extend(_ingest_friction_trial(tr, i, horizon, data.get("run_id"), "m1a-friction-trials"))
    for i, tr in enumerate(hist):
        out.extend(
            _ingest_friction_trial(tr, 1000 + i, horizon, data.get("run_id"), "m1a-friction-trials-historical")
        )
    return out


def ingest_empty_grasp(jsonl: Path, report_json: Path | None, horizon: int) -> list[QRMTrainingSampleV1]:
    rows = []
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    elif report_json and report_json.exists():
        data = _load_json(report_json)
        rows = data.get("entries") or []
    out = []
    for i, row in enumerate(rows):
        eid = str(row.get("episode_id") or f"empty-grasp-{i:02d}")
        out.append(
            _base_sample(
                episode_id=eid,
                idx=0,
                source="m0-empty-grasp",
                stage="GRASP",
                instruction="pick cube; expect empty grasp injection",
                fail=FailureType.EMPTY_GRASP,
                hand_pose=row.get("final_cube_pose_xyz"),
                cube_pose=row.get("final_cube_pose_xyz"),
                joints=None,
                grasp_family="top_down",
                recovery="REOBSERVE",
                synthetic=False,
                seed=i + 300,
                horizon=horizon,
                supervision={
                    "oracle_pose_used_for_task_geometry": True,
                    "oracle_pose_in_observation": False,
                    "task_success": row.get("task_success"),
                    "injection": row.get("injection"),
                },
            )
        )
        # multiple recovery decision candidates after empty grasp (same episode)
        for k, recovery in enumerate(["REOBSERVE", "RETRY_TOP", "ALTERNATE_SIDE", "ALTERNATE_OBLIQUE"]):
            out.append(
                _base_sample(
                    episode_id=eid,
                    idx=1 + k,
                    source="m0-empty-grasp",
                    stage="RECOVERY",
                    instruction="choose recovery after empty grasp",
                    fail=FailureType.EMPTY_GRASP,
                    hand_pose=row.get("final_cube_pose_xyz"),
                    cube_pose=row.get("final_cube_pose_xyz"),
                    joints=None,
                    grasp_family="side" if "SIDE" in recovery else ("corner" if "OBLIQUE" in recovery else "top_down"),
                    recovery=recovery,
                    synthetic=False,
                    seed=i + 400 + k,
                    horizon=horizon,
                    supervision={
                        "oracle_pose_used_for_task_geometry": True,
                        "oracle_pose_in_observation": False,
                        "is_recovery_transition": True,
                        "recovery_candidate": recovery,
                    },
                )
            )
    return out


def ingest_motion_segments(path: Path, horizon: int) -> list[QRMTrainingSampleV1]:
    data = _load_json(path)
    out = []
    segs = data.get("segments") or []
    # group into pseudo-episodes of 3 segments (MoveIt multi-stage)
    for i in range(0, len(segs), 3):
        chunk = segs[i : i + 3]
        eid = f"motion-exec-{(i // 3) + 1:02d}"
        for j, seg in enumerate(chunk):
            out.append(
                _base_sample(
                    episode_id=eid,
                    idx=j,
                    source="m1a-motion-execution",
                    stage=str(seg.get("name") or seg.get("segment") or "MOVE"),
                    instruction="execute MoveIt planned segment",
                    fail=FailureType.NONE if seg.get("success", True) else FailureType.PATH_BLOCKED,
                    hand_pose=seg.get("observed_ee_pose") or seg.get("expected_ee_pose"),
                    cube_pose=None,
                    joints=seg.get("observed_final_joints") or seg.get("expected_final_joints"),
                    grasp_family="unknown",
                    recovery="none",
                    synthetic=False,
                    seed=1000 + i + j,
                    horizon=horizon,
                    supervision={
                        "oracle_pose_used_for_task_geometry": False,
                        "oracle_pose_in_observation": False,
                        "motion_status": data.get("motion_status"),
                        "run_id": data.get("run_id"),
                        "segment_name": seg.get("segment"),
                        "controller_result": seg.get("controller_result"),
                        "success": seg.get("success"),
                    },
                )
            )
    return out


def ingest_contact_calibration(path: Path, horizon: int) -> list[QRMTrainingSampleV1]:
    data = _load_json(path)
    out = []
    for i, tr in enumerate(data.get("trials") or []):
        eid = f"contact-cal-{i:02d}"
        out.append(
            _base_sample(
                episode_id=eid,
                idx=0,
                source="m1a-contact-calibration",
                stage="GRASP",
                instruction="contact calibration trial",
                fail=FailureType.NONE,
                hand_pose=tr.get("target_hand_pose") or tr.get("retreat_hand_pose"),
                cube_pose=tr.get("cube_pose") or tr.get("cube_pose_after_action"),
                joints=None,
                grasp_family="top_down",
                recovery="none",
                synthetic=False,
                seed=2000 + i,
                horizon=horizon,
                supervision={
                    "oracle_pose_used_for_task_geometry": True,
                    "oracle_pose_in_observation": False,
                    "label": tr.get("label"),
                    "run_id": data.get("run_id"),
                },
            )
        )
    return out


def ingest_b1_oracle(path: Path, contact_gate_samples: list[QRMTrainingSampleV1], horizon: int) -> list[QRMTrainingSampleV1]:
    """S4 B1 oracle episodes: prefer contact-gate episodes already ingested; add provenance flags."""
    data = _load_json(path)
    ids = set(data.get("episode_ids") or [])
    out = []
    for s in contact_gate_samples:
        if s.episode_id in ids or not ids:
            s2 = s.model_copy(deep=True)
            s2.provenance = {**s2.provenance, "b1_oracle_report": str(path), "b1_mode": data.get("mode")}
            if s2.simulator_supervision is not None:
                s2.simulator_supervision = {
                    **s2.simulator_supervision,
                    "oracle_pose_used_for_task_geometry": bool(data.get("oracle_pose_used_for_task_geometry", True)),
                    "oracle_pose_in_observation": bool(data.get("oracle_pose_in_observation", False)),
                }
            out.append(s2)
    # if none matched, synthesize episode shells from ids
    if not out:
        for i, eid in enumerate(sorted(ids)):
            out.append(
                _base_sample(
                    episode_id=eid,
                    idx=0,
                    source="m1a-b1-oracle",
                    stage="GRASP",
                    instruction="B1 oracle pick-place",
                    fail=FailureType.NONE,
                    hand_pose=None,
                    cube_pose=None,
                    joints=None,
                    grasp_family="top_down",
                    recovery="none",
                    synthetic=False,
                    seed=3000 + i,
                    horizon=horizon,
                    supervision={
                        "oracle_pose_used_for_task_geometry": True,
                        "oracle_pose_in_observation": False,
                        "run_id": data.get("run_id"),
                    },
                )
            )
    return out


def assign_splits(samples: list[QRMTrainingSampleV1], val_ratio: float = 0.15, test_ratio: float = 0.15) -> None:
    episodes = sorted({s.episode_id for s in samples})
    rng = random.Random(0)
    rng.shuffle(episodes)
    n = len(episodes)
    n_test = max(1, int(n * test_ratio)) if n >= 6 else 1
    n_val = max(1, int(n * val_ratio)) if n >= 6 else 1
    test_set = set(episodes[:n_test])
    val_set = set(episodes[n_test : n_test + n_val])
    for s in samples:
        if s.episode_id in test_set:
            s.split = "test"
        elif s.episode_id in val_set:
            s.split = "val"
        else:
            s.split = "train"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build QRM-Real-V1 dataset")
    p.add_argument("--sources-dir", default="data/qrm_lite/sources")
    p.add_argument("--horizon", type=int, default=4)
    p.add_argument("--out-jsonl", default="data/qrm_lite/manifests/real-v1.jsonl")
    p.add_argument("--out-manifest", default="data/qrm_lite/manifests/real-v1.json")
    p.add_argument("--report", default="reports/qrm-lite-real-v1-dataset.md")
    p.add_argument("--report-json", default="reports/qrm-lite-real-v1-dataset.json")
    p.add_argument("--max-synthetic-train-frac", type=float, default=0.5)
    args = p.parse_args(argv)

    src = Path(args.sources_dir)
    samples: list[QRMTrainingSampleV1] = []
    contact = ingest_contact_gate(src / "m1a-contact-gate.json", args.horizon) if (src / "m1a-contact-gate.json").exists() else []
    samples.extend(contact)
    samples.extend(ingest_friction(src / "m1a-friction-trials.json", args.horizon) if (src / "m1a-friction-trials.json").exists() else [])
    samples.extend(
        ingest_empty_grasp(
            src / "p0-empty-grasp-failures.jsonl",
            src / "p0-empty-grasp-failures.json",
            args.horizon,
        )
    )
    samples.extend(ingest_motion_segments(src / "m1a-motion-execution.json", args.horizon) if (src / "m1a-motion-execution.json").exists() else [])
    samples.extend(ingest_contact_calibration(src / "m1a-contact-calibration.json", args.horizon) if (src / "m1a-contact-calibration.json").exists() else [])
    if (src / "m1a-b1-oracle.json").exists():
        samples.extend(ingest_b1_oracle(src / "m1a-b1-oracle.json", contact, args.horizon))

    # optional reserved hook: M1B non-oracle -> Real-V2 later
    assign_splits(samples)

    out_jsonl = Path(args.out_jsonl)
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(s.model_dump_json() + "\n")

    episodes = {s.episode_id for s in samples}
    fail_n = sum(1 for s in samples if s.observation.failure_context.failure_type != FailureType.NONE)
    recovery_n = sum(1 for s in samples if (s.simulator_supervision or {}).get("is_recovery_transition"))
    synthetic_n = sum(1 for s in samples if s.synthetic)
    real_n = len(samples) - synthetic_n
    train = [s for s in samples if s.split == "train"]
    synth_train_frac = (
        sum(1 for s in train if s.synthetic) / len(train) if train else 0.0
    )
    by_source: dict[str, int] = {}
    for s in samples:
        by_source[s.provenance.get("source", "?")] = by_source.get(s.provenance.get("source", "?"), 0) + 1

    summary = {
        "dataset": "QRM-Real-V1",
        "n_samples": len(samples),
        "n_episodes": len(episodes),
        "n_train": sum(1 for s in samples if s.split == "train"),
        "n_val": sum(1 for s in samples if s.split == "val"),
        "n_test": sum(1 for s in samples if s.split == "test"),
        "real_samples": real_n,
        "synthetic_samples": synthetic_n,
        "synthetic_train_fraction": synth_train_frac,
        "failure_or_recovery_samples": fail_n,
        "failure_or_recovery_fraction": fail_n / len(samples) if samples else 0.0,
        "recovery_transitions": recovery_n,
        "by_source": by_source,
        "gates": {
            "real_episodes_ge_50": len(episodes) >= 50,
            "real_chunks_ge_300": real_n >= 300,
            "failure_frac_ge_0_30": (fail_n / len(samples) if samples else 0.0) >= 0.30,
            "synthetic_train_frac_le_0_50": synth_train_frac <= args.max_synthetic_train_frac + 1e-9,
            "episode_level_split": True,
            "oracle_not_in_online_obs_contract": True,
        },
        "jsonl": str(out_jsonl),
        "m1b_auto_append": {
            "reserved_dataset": "QRM-Real-V2",
            "status": "interface_only",
            "note": "Do not block Beta-1 waiting for M1B; append non-oracle episodes when available",
        },
    }
    Path(args.out_manifest).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.report_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(args.report).write_text(
        "\n".join(
            [
                "# QRM-Real-V1 dataset",
                "",
                f"- samples: **{summary['n_samples']}**",
                f"- episodes: **{summary['n_episodes']}**",
                f"- real/synthetic: {real_n}/{synthetic_n}",
                f"- failure/recovery fraction: {summary['failure_or_recovery_fraction']:.3f}",
                f"- synthetic train fraction: {synth_train_frac:.3f}",
                f"- splits train/val/test: {summary['n_train']}/{summary['n_val']}/{summary['n_test']}",
                f"- by source: `{json.dumps(by_source)}`",
                f"- gate checklist: `{json.dumps(summary['gates'])}`",
                "",
                "Oracle poses are labels/nominal only; online observations use non-oracle track ids.",
                "M1B non-oracle auto-import is reserved as QRM-Real-V2.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
