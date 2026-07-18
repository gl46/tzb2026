"""Hard residual safety bounds for Beta-1 (before MoveIt).

QRM never bypasses MoveIt. Residual is clipped then rejected/fallback if unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from xh_agent.policy.qrm_lite.transforms import reject_nonfinite


@dataclass(frozen=True)
class ResidualSafetyLimits:
    """Default Beta-1 clip bounds."""

    max_translation_m: float = 0.03  # ±3 cm / axis
    max_rotation_deg: float = 15.0  # ±15°
    max_gripper_width_delta_m: float = 0.01  # ±1 cm
    speed_bins: tuple[str, ...] = ("slow", "medium", "fast")
    default_speed_bin: str = "medium"


OutcomeKind = Literal[
    "residual_accepted",
    "residual_clipped",
    "moveit_rejected",
    "fallback_to_nominal",
]


@dataclass
class ResidualSafetyResult:
    outcome: OutcomeKind
    residual_raw: np.ndarray
    residual_clipped: np.ndarray
    final_candidate: np.ndarray
    reasons: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _rotation_delta_norm_from_r6d(r6d: np.ndarray) -> float:
    """Approximate rotation magnitude from residual-from-identity 6D vector.

    Residual r6d is stored as delta-from-identity columns; magnitude of the
    first two column deltas correlates with small-angle rotation.
    """
    x = np.asarray(r6d, dtype=np.float64).reshape(-1)
    if x.size < 6:
        return 0.0
    # identity 6D is [1,0,0, 0,1,0]; residual deltas are near zero in alpha/beta1
    # If absolute 6D is passed, convert to delta first.
    identity = np.array([1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    if np.linalg.norm(x - identity) < np.linalg.norm(x):
        delta = x - identity
    else:
        delta = x
    # map column perturbation to rough degrees (empirical small-angle scale)
    return float(np.linalg.norm(delta) * 57.2957795 * 0.5)


class ResidualSafetyFilter:
    def __init__(self, limits: ResidualSafetyLimits | None = None) -> None:
        self.limits = limits or ResidualSafetyLimits()

    def clip_residual(self, residual: np.ndarray) -> tuple[np.ndarray, list[str]]:
        r = np.asarray(residual, dtype=np.float64).copy()
        if r.ndim == 1:
            r = r.reshape(1, -1)
        reject_nonfinite(r)
        reasons: list[str] = []
        lim = self.limits
        # translation
        before_t = r[..., 0:3].copy()
        r[..., 0:3] = np.clip(r[..., 0:3], -lim.max_translation_m, lim.max_translation_m)
        if not np.allclose(before_t, r[..., 0:3]):
            reasons.append("clip_translation")
        # rotation residual in r6d slots 3:9 — scale-clip by max rotation proxy
        max_r = lim.max_rotation_deg
        for i in range(r.shape[0]):
            mag = _rotation_delta_norm_from_r6d(r[i, 3:9])
            if mag > max_r + 1e-9 and mag > 0:
                scale = max_r / mag
                r[i, 3:9] = r[i, 3:9] * scale
                reasons.append(f"clip_rotation_step_{i}")
        # gripper: treat as absolute open fraction [0,1] residual target; also bound delta if provided in meta
        before_g = r[..., 9].copy()
        r[..., 9] = np.clip(r[..., 9], 0.0, 1.0)
        if not np.allclose(before_g, r[..., 9]):
            reasons.append("clip_gripper")
        return r, sorted(set(reasons))

    def combine_and_filter(
        self,
        nominal: np.ndarray,
        residual: np.ndarray,
        *,
        moveit_accept_fn=None,
    ) -> ResidualSafetyResult:
        nom = np.asarray(nominal, dtype=np.float64)
        raw = np.asarray(residual, dtype=np.float64)
        if nom.shape != raw.shape and raw.ndim == 1:
            raw = raw.reshape(nom.shape)
        clipped, reasons = self.clip_residual(raw)
        final = nom.copy()
        final[..., 0:3] = nom[..., 0:3] + clipped[..., 0:3]
        final[..., 3:9] = nom[..., 3:9] + clipped[..., 3:9]
        final[..., 9] = clipped[..., 9]
        reject_nonfinite(final)

        outcome: OutcomeKind = "residual_accepted" if not reasons else "residual_clipped"
        if moveit_accept_fn is not None:
            ok, why = moveit_accept_fn(final)
            if not ok:
                return ResidualSafetyResult(
                    outcome="fallback_to_nominal",
                    residual_raw=raw,
                    residual_clipped=clipped,
                    final_candidate=nom,
                    reasons=reasons + [f"moveit_rejected:{why}", "fallback_to_nominal"],
                    meta={"moveit_ok": False},
                )
            if why:
                reasons = reasons + [f"moveit:{why}"]
        return ResidualSafetyResult(
            outcome=outcome,
            residual_raw=raw,
            residual_clipped=clipped,
            final_candidate=final,
            reasons=reasons,
            meta={"moveit_ok": True if moveit_accept_fn is not None else None},
        )


def summarize_outcomes(results: list[ResidualSafetyResult]) -> dict[str, int]:
    counts = {
        "residual_accepted": 0,
        "residual_clipped": 0,
        "moveit_rejected": 0,
        "fallback_to_nominal": 0,
    }
    for r in results:
        if r.outcome in counts:
            counts[r.outcome] += 1
        if any(x.startswith("moveit_rejected") for x in r.reasons):
            counts["moveit_rejected"] += 1
    return counts
