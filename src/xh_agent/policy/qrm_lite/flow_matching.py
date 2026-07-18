"""Conditional flow-matching utilities (numpy + optional torch)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FlowMatchingSpec:
    horizon: int = 4
    action_dim: int = 10
    beta_a: float = 1.0
    beta_b: float = 1.5


def sample_timesteps(batch_size: int, spec: FlowMatchingSpec, rng: np.random.Generator) -> np.ndarray:
    # Beta(1, 1.5) as in the paper; fallback uniform if needed.
    try:
        t = rng.beta(spec.beta_a, spec.beta_b, size=(batch_size,)).astype(np.float64)
    except Exception:
        t = rng.uniform(0.0, 1.0, size=(batch_size,)).astype(np.float64)
    return t


def make_interpolant(
    noise: np.ndarray,
    action: np.ndarray,
    t: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """x_t = (1-t) eps + t a ; target velocity u = a - eps (rectified flow / linear path)."""
    # t: [B]
    tt = t.reshape(-1, 1, 1)
    x_t = (1.0 - tt) * noise + tt * action
    u = action - noise
    return x_t, u


def euler_integrate(
    x0: np.ndarray,
    velocity_fn,
    steps: int = 10,
) -> np.ndarray:
    """Integrate from t=0 (noise) to t=1 (action) with fixed Euler steps."""
    x = np.asarray(x0, dtype=np.float64).copy()
    dt = 1.0 / steps
    for i in range(steps):
        t = np.full((x.shape[0],), i * dt, dtype=np.float64)
        v = velocity_fn(x, t)
        x = x + dt * v
    return x


def masked_mse(pred: np.ndarray, target: np.ndarray, mask: np.ndarray | None = None) -> float:
    err = (pred - target) ** 2
    if mask is None:
        return float(np.mean(err))
    m = np.asarray(mask, dtype=np.float64)
    return float(np.sum(err * m) / np.maximum(np.sum(m), 1.0))
