"""Formal Beta-1 models: Q0 / Q1 / Q2 only.

Flow is IMPLEMENTED_NOT_SELECTED and is not part of this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import (
    CoarseIntentV1,
    CoarseLabelSpace,
    CoarsePolicyHead,
    default_label_space,
)
from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import FailureContextV1, QRMObservationV1
from xh_agent.policy.qrm_lite.flow_status import FLOW_STATUS
from xh_agent.policy.qrm_lite.mlp_refiner import MLPRefinerConfig, MLPResidualRefiner
from xh_agent.policy.qrm_lite.residual_safety import ResidualSafetyFilter, ResidualSafetyResult


class FormalModelId(str, Enum):
    Q0 = "Q0_COARSE_ONLY"
    Q1 = "Q1_COARSE_MLP_RESIDUAL"
    Q2 = "Q2_COARSE_MLP_FAILURE_CONTEXT"


RECOVERY_SKILLS = [
    "REOBSERVE",
    "RETRY_TOP",
    "ALTERNATE_OBLIQUE",
    "ALTERNATE_SIDE",
    "ABORT_SAFE",
]


@dataclass
class ModelOutput:
    model_id: FormalModelId
    coarse: CoarseIntentV1 | None = None
    residual: np.ndarray | None = None
    residual_safety: ResidualSafetyResult | None = None
    recovery_skill: str | None = None
    used_failure_context: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Q012Config:
    backbone_dim: int = 0
    joint_dim: int = 8
    history_len: int = 4
    action_dim: int = 10
    horizon: int = 4
    hidden: int = 256
    n_trans_bins: int = 5
    n_rot_bins: int = 5


class FormalPolicy:
    """Shared encoder + optional residual; FailureContext toggled by model id."""

    def __init__(self, model_id: FormalModelId, cfg: Q012Config | None = None) -> None:
        if model_id not in FormalModelId:
            raise ValueError(f"only Q0/Q1/Q2 formal models allowed, got {model_id}")
        self.model_id = model_id
        self.cfg = cfg or Q012Config()
        self.label_space: CoarseLabelSpace = default_label_space(
            n_trans_bins=self.cfg.n_trans_bins, n_rot_bins=self.cfg.n_rot_bins
        )
        # extend skills with recovery set for Beta-1 recovery head experiments
        skills = list(dict.fromkeys(self.label_space.skills + RECOVERY_SKILLS))
        self.label_space = CoarseLabelSpace(
            skills=skills,
            grasp_families=self.label_space.grasp_families,
            recovery_modes=list(dict.fromkeys(self.label_space.recovery_modes + RECOVERY_SKILLS)),
            n_trans_bins=self.label_space.n_trans_bins,
            n_rot_bins=self.label_space.n_rot_bins,
        )
        self.context_dim = context_dim(
            backbone_dim=self.cfg.backbone_dim,
            joint_dim=self.cfg.joint_dim,
            history_len=self.cfg.history_len,
            action_dim=self.cfg.action_dim,
        )
        self.coarse = CoarsePolicyHead(self.context_dim, self.label_space, hidden=self.cfg.hidden)
        self.mlp = MLPResidualRefiner(
            MLPRefinerConfig(
                context_dim=self.context_dim,
                horizon=self.cfg.horizon,
                action_dim=self.cfg.action_dim,
                hidden=self.cfg.hidden * 2,
                max_translation_m=0.03,
            )
        )
        self.safety = ResidualSafetyFilter()

    @property
    def uses_failure_context(self) -> bool:
        return self.model_id == FormalModelId.Q2

    @property
    def uses_residual(self) -> bool:
        return self.model_id in {FormalModelId.Q1, FormalModelId.Q2}

    def _encode(self, obs: QRMObservationV1, backbone_vec: np.ndarray | None = None) -> np.ndarray:
        obs_use = obs
        if not self.uses_failure_context:
            # Explicit ablation: zero out failure context for Q0/Q1.
            obs_use = obs.model_copy(deep=True)
            obs_use.failure_context = FailureContextV1()
        return build_context_vector(
            obs_use,
            backbone_vec=backbone_vec,
            backbone_dim=self.cfg.backbone_dim,
            joint_dim=self.cfg.joint_dim,
            history_len=self.cfg.history_len,
            action_dim=self.cfg.action_dim,
        )

    def predict(
        self,
        obs: QRMObservationV1,
        *,
        nominal: np.ndarray | None = None,
        backbone_vec: np.ndarray | None = None,
        moveit_accept_fn=None,
    ) -> ModelOutput:
        ctx = self._encode(obs, backbone_vec=backbone_vec)
        coarse = self.coarse.predict_intent(ctx)
        recovery = coarse.recovery_mode if coarse.recovery_mode in RECOVERY_SKILLS else coarse.skill_type
        out = ModelOutput(
            model_id=self.model_id,
            coarse=coarse,
            recovery_skill=recovery if recovery in RECOVERY_SKILLS else None,
            used_failure_context=self.uses_failure_context,
            meta={"flow_status": FLOW_STATUS, "context_dim": self.context_dim},
        )
        if not self.uses_residual:
            return out
        if nominal is None:
            raise ValueError("Q1/Q2 require geometric nominal action chunk")
        residual = self.mlp.forward(ctx, nominal)
        out.residual = residual
        out.residual_safety = self.safety.combine_and_filter(
            nominal, residual, moveit_accept_fn=moveit_accept_fn
        )
        return out


def build_formal_model(model_id: str | FormalModelId, cfg: Q012Config | None = None) -> FormalPolicy:
    mid = FormalModelId(model_id) if not isinstance(model_id, FormalModelId) else model_id
    return FormalPolicy(mid, cfg=cfg)


FORMAL_MODEL_TABLE: dict[str, str] = {
    FormalModelId.Q0.value: "Coarse-only industrial skill head",
    FormalModelId.Q1.value: "Coarse + bounded MLP residual (default continuous path)",
    FormalModelId.Q2.value: "Q1 + FailureContext (core Beta-1 ablation)",
}
