"""Structured context encoders: robot state, history, FailureContext."""

from __future__ import annotations

from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.contracts import FailureContextV1, FailureType, QRMObservationV1


def _finite_vec(values: list[float], size: int, fill: float = 0.0) -> np.ndarray:
    arr = np.full((size,), fill, dtype=np.float64)
    if not values:
        return arr
    n = min(size, len(values))
    chunk = np.asarray(values[:n], dtype=np.float64)
    chunk = np.nan_to_num(chunk, nan=0.0, posinf=0.0, neginf=0.0)
    arr[:n] = chunk
    return arr


_SKILL_VOCAB = [
    "OBSERVE",
    "APPROACH",
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REGRASP",
    "REOBSERVE",
    "SAFE_PLACE_NON_TARGET",
    "REASSOCIATE_TARGET",
    "RETRY_RELEASE",
    "STOP",
    "BACKOFF",
    "ASK_CLARIFICATION",
    "UNKNOWN",
]


def encode_robot_state(obs: QRMObservationV1, joint_dim: int = 8) -> np.ndarray:
    joints = _finite_vec(obs.joint_position, joint_dim)
    ee = _finite_vec(obs.end_effector_pose_base, 7)
    grip = np.asarray([obs.gripper_state], dtype=np.float64)
    skill = (obs.current_skill_stage or "UNKNOWN").upper()
    if skill not in _SKILL_VOCAB:
        skill = "UNKNOWN"
    skill_oh = np.zeros((len(_SKILL_VOCAB),), dtype=np.float64)
    skill_oh[_SKILL_VOCAB.index(skill)] = 1.0
    return np.concatenate([joints, ee, grip, skill_oh], axis=0)


def encode_history(obs: QRMObservationV1, history_len: int = 4, action_dim: int = 10) -> np.ndarray:
    rows: list[np.ndarray] = []
    hist = list(obs.history)[-history_len:]
    pad = history_len - len(hist)
    for _ in range(pad):
        rows.append(np.zeros((7 + action_dim,), dtype=np.float64))
    for step in hist:
        ee = _finite_vec(step.end_effector_pose, 7)
        act = _finite_vec(step.action_summary, action_dim)
        rows.append(np.concatenate([ee, act], axis=0))
    return np.concatenate(rows, axis=0)


_FAILURE_INDEX = {ft: i for i, ft in enumerate(FailureType)}


def encode_failure_context(ctx: FailureContextV1 | None, n_types: int | None = None) -> np.ndarray:
    ctx = ctx or FailureContextV1()
    n = n_types or len(FailureType)
    onehot = np.zeros((n,), dtype=np.float64)
    idx = _FAILURE_INDEX.get(ctx.failure_type, _FAILURE_INDEX[FailureType.UNKNOWN])
    if idx < n:
        onehot[idx] = 1.0
    residual_count = float(len(ctx.predicate_residual))
    retry = float(ctx.retry_count)
    recovery_count = float(len(ctx.attempted_recoveries))
    extras = np.asarray(
        [residual_count / 10.0, min(retry / 5.0, 1.0), min(recovery_count / 5.0, 1.0)],
        dtype=np.float64,
    )
    return np.concatenate([onehot, extras], axis=0)


def build_context_vector(
    obs: QRMObservationV1,
    *,
    backbone_vec: np.ndarray | None = None,
    backbone_dim: int = 0,
    joint_dim: int = 8,
    history_len: int = 4,
    action_dim: int = 10,
) -> np.ndarray:
    parts = [
        encode_robot_state(obs, joint_dim=joint_dim),
        encode_history(obs, history_len=history_len, action_dim=action_dim),
        encode_failure_context(obs.failure_context),
    ]
    if backbone_vec is not None:
        parts.insert(0, np.asarray(backbone_vec, dtype=np.float64).reshape(-1))
    elif backbone_dim > 0:
        parts.insert(0, np.zeros((backbone_dim,), dtype=np.float64))
    return np.concatenate(parts, axis=0)


def context_dim(
    *,
    backbone_dim: int = 0,
    joint_dim: int = 8,
    history_len: int = 4,
    action_dim: int = 10,
    n_failure_types: int | None = None,
) -> int:
    n = n_failure_types or len(FailureType)
    # joints + ee(7) + grip(1) + skill one-hot + history + failure one-hot/extras
    return (
        backbone_dim
        + joint_dim
        + 7
        + 1
        + len(_SKILL_VOCAB)
        + history_len * (7 + action_dim)
        + n
        + 3
    )


def observation_to_text(obs: QRMObservationV1) -> str:
    """Serialize structured fields into a short language prompt for the VLM."""
    fc = obs.failure_context
    tracks = ", ".join(f"{t.track_id}:{t.category or '?'}@{t.confidence:.2f}" for t in obs.perception_tracks[:5])
    return (
        f"Instruction: {obs.instruction}\n"
        f"Skill stage: {obs.current_skill_stage or 'unknown'}\n"
        f"Tracks: {tracks or 'none'}\n"
        f"Failure: {fc.failure_type.value}; retry={fc.retry_count}; "
        f"residual={','.join(fc.predicate_residual) or 'none'}\n"
        f"Last skill: {fc.last_skill or 'none'}; recoveries={','.join(fc.attempted_recoveries) or 'none'}"
    )


def batch_context_matrix(samples_obs: list[QRMObservationV1], **kwargs: Any) -> np.ndarray:
    rows = [build_context_vector(o, **kwargs) for o in samples_obs]
    return np.stack(rows, axis=0)
