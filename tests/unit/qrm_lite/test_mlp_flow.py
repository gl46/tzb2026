from __future__ import annotations

import numpy as np

from xh_agent.policy.qrm_lite.flow_matching import make_interpolant, sample_timesteps, FlowMatchingSpec
from xh_agent.policy.qrm_lite.flow_refiner import FlowRefinerConfig, FlowResidualRefiner, train_flow_numpy_step
from xh_agent.policy.qrm_lite.mlp_refiner import MLPRefinerConfig, MLPResidualRefiner
from xh_agent.policy.qrm_lite.transforms import build_identity_action_chunk


def test_mlp_shape_and_bounds():
    cfg = MLPRefinerConfig(context_dim=32, horizon=4, action_dim=10, max_translation_m=0.05)
    m = MLPResidualRefiner(cfg)
    ctx = np.zeros(32)
    nom = build_identity_action_chunk(4)
    out = m.forward(ctx, nom)
    assert out.shape == (4, 10)
    assert np.all(np.abs(out[:, 0:3]) <= 0.05 + 1e-9)
    assert np.all(out[:, 9] >= 0.0) and np.all(out[:, 9] <= 1.0)


def test_flow_forward_backward_and_seed():
    cfg = FlowRefinerConfig(context_dim=32, horizon=4, action_dim=10, hidden=64, n_layers=2, ode_steps=4, seed=0)
    m = FlowResidualRefiner(cfg)
    ctx = np.random.default_rng(0).normal(size=(8, 32))
    nom = np.stack([build_identity_action_chunk(4) for _ in range(8)])
    act = nom + 0.01
    loss1 = m.flow_loss(act, ctx, nom, rng=np.random.default_rng(1))
    loss2 = train_flow_numpy_step(m, act, ctx, nom, lr=1e-2, rng=np.random.default_rng(1))
    assert np.isfinite(loss1) and np.isfinite(loss2)
    s1 = m.sample(ctx[0], nom[0], seed=123)
    s2 = m.sample(ctx[0], nom[0], seed=123)
    assert s1.shape == (4, 10)
    assert np.allclose(s1, s2)


def test_flow_matching_interpolant():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(4, 4, 10))
    eps = rng.normal(size=a.shape)
    t = sample_timesteps(4, FlowMatchingSpec(), rng)
    xt, u = make_interpolant(eps, a, t)
    assert xt.shape == a.shape
    assert np.allclose(u, a - eps)
