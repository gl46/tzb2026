"""Formal Beta-1 models: Q0 / Q1 / Q2 only.

Flow is IMPLEMENTED_NOT_SELECTED and is not part of this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import (
    DEFAULT_GRASP_FAMILIES,
    DEFAULT_RECOVERY,
    DEFAULT_SKILLS,
    CoarseIntentV1,
    CoarseLabelSpace,
    CoarsePolicyHead,
    default_label_space,
)
from xh_agent.policy.qrm_lite.context import (
    LEGACY_BETA1_SKILL_VOCAB,
    M2B_SKILL_VOCAB,
    build_context_vector,
    context_dim,
)
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

LEGACY_BETA1_COARSE_SKILLS = [
    "OBSERVE",
    "APPROACH",
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REGRASP",
    "REOBSERVE",
    "STOP",
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
    context_skill_vocab: tuple[str, ...] = tuple(M2B_SKILL_VOCAB)
    coarse_base_skills: tuple[str, ...] = tuple(DEFAULT_SKILLS)


class FormalPolicy:
    """Shared encoder + optional residual; FailureContext toggled by model id."""

    def __init__(self, model_id: FormalModelId, cfg: Q012Config | None = None) -> None:
        if model_id not in FormalModelId:
            raise ValueError(f"only Q0/Q1/Q2 formal models allowed, got {model_id}")
        self.model_id = model_id
        self.cfg = cfg or Q012Config()
        base_space = default_label_space(
            n_trans_bins=self.cfg.n_trans_bins,
            n_rot_bins=self.cfg.n_rot_bins,
        )
        self.label_space = CoarseLabelSpace(
            skills=list(self.cfg.coarse_base_skills),
            grasp_families=list(DEFAULT_GRASP_FAMILIES),
            recovery_modes=list(DEFAULT_RECOVERY),
            n_trans_bins=base_space.n_trans_bins,
            n_rot_bins=base_space.n_rot_bins,
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
            skill_vocab=self.cfg.context_skill_vocab,
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
            skill_vocab=self.cfg.context_skill_vocab,
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


def load_formal_checkpoint(
    path: str,
    *,
    expected_model_id: str | None = None,
) -> FormalPolicy:
    """Load versioned Q0/Q1/Q2 weights without guessing tensor semantics.

    M2A checkpoints predate the three M2B recovery classes.  Their exact
    110-input/70-output architecture is a frozen, named revision; any other
    unversioned shape is rejected rather than padded or truncated.
    """
    payload = np.load(path)
    observed_model_id = str(payload["model_id"])
    if expected_model_id is not None and observed_model_id != expected_model_id:
        raise ValueError(
            f"QRM checkpoint model mismatch: {observed_model_id} != "
            f"{expected_model_id}"
        )
    input_dim = int(payload["coarse_w1"].shape[0])
    output_dim = int(payload["coarse_w2"].shape[1])
    current = build_formal_model(observed_model_id)
    current_shape = (current.context_dim, current.coarse.out_dim)
    if (input_dim, output_dim) == current_shape:
        model = current
        revision = "M2B_Q012_V1"
    elif (input_dim, output_dim) == (110, 70):
        model = build_formal_model(
            observed_model_id,
            cfg=Q012Config(
                context_skill_vocab=tuple(LEGACY_BETA1_SKILL_VOCAB),
                coarse_base_skills=tuple(LEGACY_BETA1_COARSE_SKILLS),
            ),
        )
        revision = "M2A_BETA1_LEGACY_V1"
    else:
        raise ValueError(
            "unsupported unversioned QRM checkpoint architecture: "
            f"input/output={(input_dim, output_dim)}, "
            f"known={[current_shape, (110, 70)]}"
        )
    for name in ("w1", "b1", "w2", "b2"):
        setattr(model.coarse, name, np.asarray(payload[f"coarse_{name}"]))
        setattr(model.mlp, name, np.asarray(payload[f"mlp_{name}"]))
    model.meta_checkpoint_revision = revision
    return model


FORMAL_MODEL_TABLE: dict[str, str] = {
    FormalModelId.Q0.value: "Coarse-only industrial skill head",
    FormalModelId.Q1.value: "Coarse + bounded MLP residual (default continuous path)",
    FormalModelId.Q2.value: "Q1 + FailureContext (core Beta-1 ablation)",
}
