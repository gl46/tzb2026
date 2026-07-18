"""Safety adapter: denormalize, residual bounds, workspace pre-check, MoveIt handoff."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.transforms import (
    ActionNormStats,
    camera_delta_to_base_delta,
    camera_r6d_to_ee_relative_rotation,
    clip_residual_chunk,
    reject_nonfinite,
)


@dataclass
class SafetyLimits:
    max_translation_m: float = 0.05
    max_r6d: float = 0.5
    max_step_speed_mps: float = 0.25
    workspace_min_xyz: tuple[float, float, float] = (0.15, -0.45, 0.05)
    workspace_max_xyz: tuple[float, float, float] = (0.75, 0.45, 0.75)
    fps: float = 5.0


@dataclass
class SafetyDecision:
    accepted: bool
    reason: str
    final_chunk: np.ndarray | None = None
    base_translation_chunk: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class SafetyAdapter:
    def __init__(
        self,
        limits: SafetyLimits | None = None,
        norm: ActionNormStats | None = None,
    ) -> None:
        self.limits = limits or SafetyLimits()
        self.norm = norm

    def denormalize(self, chunk: np.ndarray) -> np.ndarray:
        x = np.asarray(chunk, dtype=np.float64)
        if self.norm is not None:
            x = self.norm.denormalize(x)
        reject_nonfinite(x)
        return x

    def apply_residual_bounds(self, residual: np.ndarray) -> np.ndarray:
        return clip_residual_chunk(
            residual,
            max_translation_m=self.limits.max_translation_m,
            max_r6d=self.limits.max_r6d,
        )

    def combine(self, nominal: np.ndarray, residual: np.ndarray) -> np.ndarray:
        n = np.asarray(nominal, dtype=np.float64)
        r = self.apply_residual_bounds(self.denormalize(residual))
        if n.shape != r.shape:
            raise ValueError(f"nominal/residual shape mismatch: {n.shape} vs {r.shape}")
        # translation + gripper additive; for 6D rotation residual we add in r6d space then rely on
        # downstream conversion — alpha keeps additive residual for simplicity and clips.
        out = n.copy()
        out[..., 0:3] = n[..., 0:3] + r[..., 0:3]
        # residual r6d is delta-from-identity; absolute = nominal + residual
        out[..., 3:9] = n[..., 3:9] + r[..., 3:9]
        out[..., 9] = np.clip(r[..., 9], 0.0, 1.0)
        reject_nonfinite(out)
        return out

    def workspace_ok(self, ee_xyz_base: np.ndarray, base_deltas: np.ndarray) -> tuple[bool, str]:
        pos = np.asarray(ee_xyz_base, dtype=np.float64).reshape(3)
        for i, d in enumerate(np.asarray(base_deltas, dtype=np.float64).reshape(-1, 3)):
            pos = pos + d
            for a, (lo, hi) in enumerate(
                zip(self.limits.workspace_min_xyz, self.limits.workspace_max_xyz)
            ):
                if pos[a] < lo or pos[a] > hi:
                    return False, f"workspace_violation_step_{i}_axis_{a}"
            speed = float(np.linalg.norm(d) * self.limits.fps)
            if speed > self.limits.max_step_speed_mps:
                return False, f"speed_violation_step_{i}_{speed:.3f}"
        return True, "ok"

    def to_moveit_skill_params(
        self,
        final_chunk_cam: np.ndarray,
        *,
        base_T_cam: np.ndarray,
        base_T_ee: np.ndarray,
        ee_xyz_base: np.ndarray,
    ) -> SafetyDecision:
        try:
            reject_nonfinite(final_chunk_cam)
        except ValueError as exc:
            return SafetyDecision(False, f"nonfinite:{exc}")

        chunk = np.asarray(final_chunk_cam, dtype=np.float64)
        base_deltas = []
        for row in chunk:
            d_base = camera_delta_to_base_delta(row[0:3], base_T_cam)
            base_deltas.append(d_base)
            # rotation convert smoke (ensures r6d valid)
            _ = camera_r6d_to_ee_relative_rotation(row[3:9], base_T_cam, base_T_ee)
        base_deltas_arr = np.stack(base_deltas, axis=0)
        ok, reason = self.workspace_ok(ee_xyz_base, base_deltas_arr)
        if not ok:
            return SafetyDecision(False, reason, meta={"base_deltas": base_deltas_arr.tolist()})
        return SafetyDecision(
            True,
            "accepted",
            final_chunk=chunk,
            base_translation_chunk=base_deltas_arr,
            meta={
                "coordinate_frame_out": "base",
                "note": "MoveIt still owns IK/collision; this adapter only pre-filters",
            },
        )

    def filter_candidate(
        self,
        nominal: np.ndarray,
        residual: np.ndarray,
        *,
        base_T_cam: np.ndarray,
        base_T_ee: np.ndarray,
        ee_xyz_base: np.ndarray,
    ) -> SafetyDecision:
        try:
            final = self.combine(nominal, residual)
        except ValueError as exc:
            return SafetyDecision(False, f"combine_failed:{exc}")
        return self.to_moveit_skill_params(
            final,
            base_T_cam=base_T_cam,
            base_T_ee=base_T_ee,
            ee_xyz_base=ee_xyz_base,
        )
