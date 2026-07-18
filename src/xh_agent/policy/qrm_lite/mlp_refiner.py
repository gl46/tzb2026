"""MLP residual action chunk refiner baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.transforms import clip_residual_chunk, reject_nonfinite


@dataclass
class MLPRefinerConfig:
    context_dim: int
    horizon: int = 4
    action_dim: int = 10
    hidden: int = 512
    max_translation_m: float = 0.05
    max_r6d: float = 0.5


class MLPResidualRefiner:
    """Two-layer MLP: context (+ optional nominal flat) -> residual chunk."""

    def __init__(self, cfg: MLPRefinerConfig) -> None:
        self.cfg = cfg
        self.in_dim = cfg.context_dim + cfg.horizon * cfg.action_dim
        self.out_dim = cfg.horizon * cfg.action_dim
        rng = np.random.default_rng(0)
        s1 = np.sqrt(2.0 / (self.in_dim + cfg.hidden))
        s2 = np.sqrt(2.0 / (cfg.hidden + self.out_dim))
        self.w1 = rng.normal(0, s1, size=(self.in_dim, cfg.hidden)).astype(np.float64)
        self.b1 = np.zeros((cfg.hidden,), dtype=np.float64)
        self.w2 = rng.normal(0, s2, size=(cfg.hidden, self.out_dim)).astype(np.float64)
        self.b2 = np.zeros((self.out_dim,), dtype=np.float64)

    def forward(self, context: np.ndarray, nominal: np.ndarray) -> np.ndarray:
        c = np.asarray(context, dtype=np.float64)
        n = np.asarray(nominal, dtype=np.float64)
        if c.ndim == 1:
            c = c.reshape(1, -1)
            n = n.reshape(1, -1)
            squeeze = True
        else:
            squeeze = False
        n_flat = n.reshape(n.shape[0], -1)
        x = np.concatenate([c, n_flat], axis=-1)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        h = np.tanh(np.clip(x @ self.w1 + self.b1, -20.0, 20.0))
        y = h @ self.w2 + self.b2
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
        y = y.reshape(y.shape[0], self.cfg.horizon, self.cfg.action_dim)
        y = clip_residual_chunk(
            y,
            max_translation_m=self.cfg.max_translation_m,
            max_r6d=self.cfg.max_r6d,
        )
        reject_nonfinite(y)
        return y[0] if squeeze else y

    def state_dict(self) -> dict[str, Any]:
        return {
            "cfg": self.cfg.__dict__,
            "w1": self.w1,
            "b1": self.b1,
            "w2": self.w2,
            "b2": self.b2,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.cfg = MLPRefinerConfig(**state["cfg"])
        self.w1 = np.asarray(state["w1"])
        self.b1 = np.asarray(state["b1"])
        self.w2 = np.asarray(state["w2"])
        self.b2 = np.asarray(state["b2"])
        self.in_dim = self.cfg.context_dim + self.cfg.horizon * self.cfg.action_dim
        self.out_dim = self.cfg.horizon * self.cfg.action_dim
