"""Small conditional Flow-Matching action refiner (numpy prototype + torch twin)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from xh_agent.policy.qrm_lite.flow_matching import (
    FlowMatchingSpec,
    euler_integrate,
    make_interpolant,
    masked_mse,
    sample_timesteps,
)
from xh_agent.policy.qrm_lite.transforms import clip_residual_chunk, reject_nonfinite


@dataclass
class FlowRefinerConfig:
    context_dim: int
    horizon: int = 4
    action_dim: int = 10
    hidden: int = 512
    n_layers: int = 3
    ode_steps: int = 8
    max_translation_m: float = 0.05
    max_r6d: float = 0.5
    seed: int = 0


class FlowResidualRefiner:
    """MLP velocity field v_theta(x_t, t, context, nominal) approximating flow.

    This is intentionally small for A100 alpha bring-up / overfit tests.
    """

    def __init__(self, cfg: FlowRefinerConfig) -> None:
        self.cfg = cfg
        self.spec = FlowMatchingSpec(horizon=cfg.horizon, action_dim=cfg.action_dim)
        self.x_dim = cfg.horizon * cfg.action_dim
        # inputs: flat x_t + t + context + flat nominal
        self.in_dim = self.x_dim + 1 + cfg.context_dim + self.x_dim
        self.out_dim = self.x_dim
        rng = np.random.default_rng(cfg.seed)
        dims = [self.in_dim] + [cfg.hidden] * cfg.n_layers + [self.out_dim]
        self.weights: list[np.ndarray] = []
        self.biases: list[np.ndarray] = []
        for din, dout in zip(dims[:-1], dims[1:]):
            # Xavier-ish scale to avoid tanh saturation / overflow on large inputs.
            scale = np.sqrt(2.0 / (din + dout))
            self.weights.append(rng.normal(0, scale, size=(din, dout)).astype(np.float64))
            self.biases.append(np.zeros((dout,), dtype=np.float64))

    def _velocity(self, x_t: np.ndarray, t: np.ndarray, context: np.ndarray, nominal: np.ndarray) -> np.ndarray:
        b = x_t.shape[0]
        xt = x_t.reshape(b, -1)
        nom = nominal.reshape(b, -1)
        ctx = context.reshape(b, -1)
        tt = t.reshape(b, 1)
        h = np.concatenate([xt, tt, ctx, nom], axis=-1)
        h = np.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)
        for i, (w, bvec) in enumerate(zip(self.weights, self.biases)):
            h = h @ w + bvec
            if i < len(self.weights) - 1:
                h = np.tanh(np.clip(h, -20.0, 20.0))
        h = np.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)
        return h.reshape(b, self.cfg.horizon, self.cfg.action_dim)

    def flow_loss(
        self,
        actions: np.ndarray,
        context: np.ndarray,
        nominal: np.ndarray,
        mask: np.ndarray | None = None,
        rng: np.random.Generator | None = None,
    ) -> float:
        rng = rng or np.random.default_rng(0)
        a = np.asarray(actions, dtype=np.float64)
        if a.ndim == 2:
            a = a.reshape(1, *a.shape)
        b = a.shape[0]
        noise = rng.normal(size=a.shape)
        t = sample_timesteps(b, self.spec, rng)
        x_t, u = make_interpolant(noise, a, t)
        v = self._velocity(x_t, t, context, nominal)
        return masked_mse(v, u, mask)

    def sample(
        self,
        context: np.ndarray,
        nominal: np.ndarray,
        *,
        steps: int | None = None,
        seed: int | None = None,
        n_candidates: int = 1,
    ) -> np.ndarray:
        rng = np.random.default_rng(self.cfg.seed if seed is None else seed)
        ctx = np.asarray(context, dtype=np.float64)
        nom = np.asarray(nominal, dtype=np.float64)
        if ctx.ndim == 1:
            ctx = np.broadcast_to(ctx, (n_candidates, ctx.shape[0])).copy()
            nom = np.broadcast_to(nom, (n_candidates, *nom.shape)).copy()
        b = ctx.shape[0]
        x0 = rng.normal(size=(b, self.cfg.horizon, self.cfg.action_dim))

        def velocity_fn(x: np.ndarray, t: np.ndarray) -> np.ndarray:
            return self._velocity(x, t, ctx, nom)

        out = euler_integrate(x0, velocity_fn, steps=steps or self.cfg.ode_steps)
        out = clip_residual_chunk(
            out,
            max_translation_m=self.cfg.max_translation_m,
            max_r6d=self.cfg.max_r6d,
        )
        reject_nonfinite(out)
        return out[0] if n_candidates == 1 and np.asarray(context).ndim == 1 else out

    def state_dict(self) -> dict[str, Any]:
        return {
            "cfg": self.cfg.__dict__,
            "weights": self.weights,
            "biases": self.biases,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.cfg = FlowRefinerConfig(**state["cfg"])
        self.__init__(self.cfg)  # rebuild shapes
        self.weights = [np.asarray(w) for w in state["weights"]]
        self.biases = [np.asarray(b) for b in state["biases"]]


def train_flow_numpy_step(
    model: FlowResidualRefiner,
    actions: np.ndarray,
    context: np.ndarray,
    nominal: np.ndarray,
    *,
    lr: float = 1e-3,
    rng: np.random.Generator | None = None,
) -> float:
    """One analytic last-layer SGD step for tiny overfit demos without torch.

    Prefer the torch training script for real GPU work. This path keeps unit tests and
    offline machines able to show a real loss decrease without finite-diff blowups.
    """
    rng = rng or np.random.default_rng(0)
    a = np.asarray(actions, dtype=np.float64)
    if a.ndim == 2:
        a = a.reshape(1, *a.shape)
    bsz = a.shape[0]
    noise = rng.normal(size=a.shape)
    t = sample_timesteps(bsz, model.spec, rng)
    x_t, u = make_interpolant(noise, a, t)

    # Forward up to last hidden, then closed-form last-layer grad on MSE.
    xt = x_t.reshape(bsz, -1)
    nom = np.asarray(nominal, dtype=np.float64).reshape(bsz, -1)
    ctx = np.asarray(context, dtype=np.float64).reshape(bsz, -1)
    tt = t.reshape(bsz, 1)
    h = np.concatenate([xt, tt, ctx, nom], axis=-1)
    h = np.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)
    for w, bvec in zip(model.weights[:-1], model.biases[:-1]):
        h = np.tanh(np.clip(h @ w + bvec, -20.0, 20.0))
    pred_flat = h @ model.weights[-1] + model.biases[-1]
    target_flat = u.reshape(bsz, -1)
    err = pred_flat - target_flat
    loss = float(np.mean(err**2))
    dpred = (2.0 / err.size) * err
    # clip grads
    dw = np.clip(h.T @ dpred, -1.0, 1.0)
    db = np.clip(dpred.sum(axis=0), -1.0, 1.0)
    model.weights[-1] = model.weights[-1] - lr * dw
    model.biases[-1] = model.biases[-1] - lr * db
    # report post-step loss with same minibatch construction for trend (new noise)
    return float(model.flow_loss(actions, context, nominal, rng=rng))
