"""Composite QRM-Lite policy: backbone context + coarse head + residual refiner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import CoarseLabelSpace, CoarsePolicyHead, default_label_space
from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim, observation_to_text
from xh_agent.policy.qrm_lite.contracts import CoarseIntentV1, QRMObservationV1
from xh_agent.policy.qrm_lite.flow_refiner import FlowRefinerConfig, FlowResidualRefiner
from xh_agent.policy.qrm_lite.mlp_refiner import MLPRefinerConfig, MLPResidualRefiner


@dataclass
class QRMLiteConfig:
    backbone_dim: int = 0  # 0 => no backbone features in numpy path
    joint_dim: int = 8
    history_len: int = 4
    action_dim: int = 10
    horizon: int = 4
    hidden: int = 256
    refiner: Literal["mlp", "flow"] = "mlp"
    n_trans_bins: int = 5
    n_rot_bins: int = 5


@dataclass
class QRMLitePolicy:
    cfg: QRMLiteConfig = field(default_factory=QRMLiteConfig)
    label_space: CoarseLabelSpace | None = None
    coarse: CoarsePolicyHead | None = None
    mlp: MLPResidualRefiner | None = None
    flow: FlowResidualRefiner | None = None
    backbone: Any | None = None  # optional Qwen35Backbone

    def __post_init__(self) -> None:
        self.label_space = self.label_space or default_label_space(
            n_trans_bins=self.cfg.n_trans_bins,
            n_rot_bins=self.cfg.n_rot_bins,
        )
        cdim = context_dim(
            backbone_dim=self.cfg.backbone_dim,
            joint_dim=self.cfg.joint_dim,
            history_len=self.cfg.history_len,
            action_dim=self.cfg.action_dim,
        )
        self.coarse = self.coarse or CoarsePolicyHead(cdim, self.label_space, hidden=self.cfg.hidden)
        self.mlp = self.mlp or MLPResidualRefiner(
            MLPRefinerConfig(
                context_dim=cdim,
                horizon=self.cfg.horizon,
                action_dim=self.cfg.action_dim,
                hidden=self.cfg.hidden * 2,
            )
        )
        self.flow = self.flow or FlowResidualRefiner(
            FlowRefinerConfig(
                context_dim=cdim,
                horizon=self.cfg.horizon,
                action_dim=self.cfg.action_dim,
                hidden=self.cfg.hidden * 2,
            )
        )
        self.context_dim = cdim

    def encode_context(self, obs: QRMObservationV1, backbone_vec: np.ndarray | None = None) -> np.ndarray:
        return build_context_vector(
            obs,
            backbone_vec=backbone_vec,
            backbone_dim=self.cfg.backbone_dim,
            joint_dim=self.cfg.joint_dim,
            history_len=self.cfg.history_len,
            action_dim=self.cfg.action_dim,
        )

    def predict_coarse(self, obs: QRMObservationV1, backbone_vec: np.ndarray | None = None) -> CoarseIntentV1:
        assert self.coarse is not None
        ctx = self.encode_context(obs, backbone_vec=backbone_vec)
        return self.coarse.predict_intent(ctx)

    def predict_residual(
        self,
        obs: QRMObservationV1,
        nominal: np.ndarray,
        *,
        backbone_vec: np.ndarray | None = None,
        use: Literal["mlp", "flow"] | None = None,
        seed: int | None = None,
    ) -> np.ndarray:
        ctx = self.encode_context(obs, backbone_vec=backbone_vec)
        which = use or self.cfg.refiner
        if which == "flow":
            assert self.flow is not None
            return self.flow.sample(ctx, nominal, seed=seed)
        assert self.mlp is not None
        return self.mlp.forward(ctx, nominal)

    def prompt_for_backbone(self, obs: QRMObservationV1) -> str:
        return observation_to_text(obs)
