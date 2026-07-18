"""Camera / base / EE frame transforms and action normalization for QRM-Lite."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np

DIM_DEFAULT = [
    "dx",
    "dy",
    "dz",
    "r6d_0",
    "r6d_1",
    "r6d_2",
    "r6d_3",
    "r6d_4",
    "r6d_5",
    "gripper",
]


def _as_np(x: Sequence[float] | np.ndarray, shape: tuple[int, ...] | None = None) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    if shape is not None:
        arr = arr.reshape(shape)
    if not np.all(np.isfinite(arr)):
        raise ValueError("transform input contains NaN/Inf")
    return arr


def quat_wxyz_to_rotmat(q: Sequence[float]) -> np.ndarray:
    w, x, y, z = _as_np(q, (4,))
    n = np.linalg.norm([w, x, y, z])
    if n < 1e-12:
        raise ValueError("zero quaternion")
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def rotmat_to_quat_wxyz(r: np.ndarray) -> np.ndarray:
    m = _as_np(r, (3, 3))
    t = float(np.trace(m))
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return q / np.linalg.norm(q)


def pose_xyzquat_to_mat(pose: Sequence[float]) -> np.ndarray:
    p = _as_np(pose, (7,))
    t = np.eye(4)
    t[:3, :3] = quat_wxyz_to_rotmat(p[3:])
    t[:3, 3] = p[:3]
    return t


def mat_to_pose_xyzquat(mat: np.ndarray) -> np.ndarray:
    m = _as_np(mat, (4, 4))
    return np.concatenate([m[:3, 3], rotmat_to_quat_wxyz(m[:3, :3])])


def invert_se3(mat: np.ndarray) -> np.ndarray:
    m = _as_np(mat, (4, 4))
    r = m[:3, :3]
    t = m[:3, 3]
    out = np.eye(4)
    out[:3, :3] = r.T
    out[:3, 3] = -r.T @ t
    return out


def rotmat_to_r6d(r: np.ndarray) -> np.ndarray:
    m = _as_np(r, (3, 3))
    return np.concatenate([m[:, 0], m[:, 1]], axis=0)


def r6d_to_rotmat(r6d: Sequence[float]) -> np.ndarray:
    a1 = _as_np(r6d, (6,))[:3]
    a2 = _as_np(r6d, (6,))[3:]
    b1 = a1 / (np.linalg.norm(a1) + 1e-12)
    proj = np.dot(b1, a2) * b1
    b2 = a2 - proj
    b2 = b2 / (np.linalg.norm(b2) + 1e-12)
    b3 = np.cross(b1, b2)
    return np.stack([b1, b2, b3], axis=1)


@dataclass(frozen=True)
class ActionNormStats:
    """Per-dimension mean/std for action chunks."""

    mean: np.ndarray
    std: np.ndarray
    revision: str = "qrm-lite-alpha-v1"

    def normalize(self, values: np.ndarray) -> np.ndarray:
        x = _as_np(values)
        return (x - self.mean) / np.maximum(self.std, 1e-6)

    def denormalize(self, values: np.ndarray) -> np.ndarray:
        x = _as_np(values)
        out = x * np.maximum(self.std, 1e-6) + self.mean
        if not np.all(np.isfinite(out)):
            raise ValueError("denormalize produced NaN/Inf")
        return out


DEFAULT_RESIDUAL_BOUNDS = {
    "dx": 0.05,
    "dy": 0.05,
    "dz": 0.05,
    "r6d": 0.5,
    "gripper": 1.0,
}


def clip_residual_chunk(
    values: np.ndarray,
    *,
    max_translation_m: float = 0.05,
    max_r6d: float = 0.5,
    allow_nonfinite: bool = True,
) -> np.ndarray:
    x = np.asarray(values, dtype=np.float64)
    if allow_nonfinite:
        x = np.nan_to_num(x, nan=0.0, posinf=max_translation_m, neginf=-max_translation_m)
    else:
        x = _as_np(values)
    x = x.copy()
    if x.ndim == 1:
        x = x.reshape(1, -1)
    x[..., 0:3] = np.clip(x[..., 0:3], -max_translation_m, max_translation_m)
    x[..., 3:9] = np.clip(x[..., 3:9], -max_r6d, max_r6d)
    x[..., 9] = np.clip(x[..., 9], 0.0, 1.0)
    return x


def base_delta_to_camera_delta(
    delta_xyz_base: Sequence[float],
    base_T_cam: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Map a base-frame translation delta into camera optical frame."""
    d = _as_np(delta_xyz_base, (3,))
    t = _as_np(base_T_cam, (4, 4))
    r_bc = t[:3, :3]
    # p_cam = R_bc^T * p_base  (for pure vectors)
    return r_bc.T @ d


def camera_delta_to_base_delta(
    delta_xyz_cam: Sequence[float],
    base_T_cam: Sequence[float] | np.ndarray,
) -> np.ndarray:
    d = _as_np(delta_xyz_cam, (3,))
    t = _as_np(base_T_cam, (4, 4))
    return t[:3, :3] @ d


def ee_relative_rotation_to_camera_r6d(
    ee_R_delta: np.ndarray,
    base_T_cam: Sequence[float] | np.ndarray,
    base_T_ee: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Express EE local rotation residual in camera frame as 6D.

    Convention: ee_R_delta is right-multiplied on current EE rotation (local EE delta).
    Camera-frame relative rotation uses:
      R_cam = R_bc^T @ R_be @ ee_R_delta @ R_be^T @ R_bc
    which is the conjugation of the EE local delta into the camera frame.
    """
    rd = _as_np(ee_R_delta, (3, 3))
    r_bc = _as_np(base_T_cam, (4, 4))[:3, :3]
    r_be = _as_np(base_T_ee, (4, 4))[:3, :3]
    r_cam = r_bc.T @ r_be @ rd @ r_be.T @ r_bc
    return rotmat_to_r6d(r_cam)


def camera_r6d_to_ee_relative_rotation(
    r6d: Sequence[float],
    base_T_cam: Sequence[float] | np.ndarray,
    base_T_ee: Sequence[float] | np.ndarray,
) -> np.ndarray:
    r_cam = r6d_to_rotmat(r6d)
    r_bc = _as_np(base_T_cam, (4, 4))[:3, :3]
    r_be = _as_np(base_T_ee, (4, 4))[:3, :3]
    return r_be.T @ r_bc @ r_cam @ r_bc.T @ r_be


def build_identity_action_chunk(horizon: int = 4) -> np.ndarray:
    """Zero residual translation/rotation, gripper hold (0.0)."""
    out = np.zeros((horizon, 10), dtype=np.float64)
    # 6D identity: first two columns of I
    out[:, 3] = 1.0
    out[:, 7] = 1.0
    return out


def reject_nonfinite(values: Sequence[Sequence[float]] | np.ndarray) -> None:
    arr = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError("NaN/Inf rejected")
    if any(not isfinite(float(v)) for v in arr.reshape(-1)):
        raise ValueError("NaN/Inf rejected")
