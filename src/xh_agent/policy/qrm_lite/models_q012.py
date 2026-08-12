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
    required_tensors = {
        "coarse_w1",
        "coarse_b1",
        "coarse_w2",
        "coarse_b2",
        "mlp_w1",
        "mlp_b1",
        "mlp_w2",
        "mlp_b2",
    }
    required_keys = {"model_id", *required_tensors}
    metadata_keys = {"checkpoint_schema_version", "architecture_revision"}

    def scalar_text(payload: np.lib.npyio.NpzFile, key: str) -> str:
        value = np.asarray(payload[key])
        if value.shape != ():
            raise ValueError(f"QRM checkpoint metadata {key} must be scalar")
        return str(value.item())

    with np.load(path, allow_pickle=False) as payload:
        keys = set(payload.files)
        missing = sorted(required_keys - keys)
        if missing:
            raise ValueError(f"QRM checkpoint missing fields: {missing}")
        unknown = sorted(keys - required_keys - metadata_keys)
        if unknown:
            raise ValueError(f"QRM checkpoint has unsupported fields: {unknown}")
        observed_model_id = scalar_text(payload, "model_id")
        if expected_model_id is not None and observed_model_id != expected_model_id:
            raise ValueError(
                f"QRM checkpoint model mismatch: {observed_model_id} != "
                f"{expected_model_id}"
            )

        current = build_formal_model(observed_model_id)
        current_shapes = {
            "coarse_w1": current.coarse.w1.shape,
            "coarse_b1": current.coarse.b1.shape,
            "coarse_w2": current.coarse.w2.shape,
            "coarse_b2": current.coarse.b2.shape,
            "mlp_w1": current.mlp.w1.shape,
            "mlp_b1": current.mlp.b1.shape,
            "mlp_w2": current.mlp.w2.shape,
            "mlp_b2": current.mlp.b2.shape,
        }
        legacy = build_formal_model(
            observed_model_id,
            cfg=Q012Config(
                context_skill_vocab=tuple(LEGACY_BETA1_SKILL_VOCAB),
                coarse_base_skills=tuple(LEGACY_BETA1_COARSE_SKILLS),
            ),
        )
        legacy_shapes = {
            "coarse_w1": legacy.coarse.w1.shape,
            "coarse_b1": legacy.coarse.b1.shape,
            "coarse_w2": legacy.coarse.w2.shape,
            "coarse_b2": legacy.coarse.b2.shape,
            "mlp_w1": legacy.mlp.w1.shape,
            "mlp_b1": legacy.mlp.b1.shape,
            "mlp_w2": legacy.mlp.w2.shape,
            "mlp_b2": legacy.mlp.b2.shape,
        }
        observed_shapes = {
            name: tuple(np.asarray(payload[name]).shape)
            for name in sorted(required_tensors)
        }
        if observed_shapes == current_shapes:
            model = current
            revision = "M2B_Q012_V1"
            if metadata_keys - keys:
                raise ValueError(
                    "M2B_Q012_V1 checkpoint requires schema and architecture metadata"
                )
        elif observed_shapes == legacy_shapes:
            model = legacy
            revision = "M2A_BETA1_LEGACY_V1"
            if bool(metadata_keys & keys) and metadata_keys - keys:
                raise ValueError(
                    "legacy checkpoint metadata must include schema and revision together"
                )
        else:
            mismatches = {
                name: {
                    "observed": observed_shapes[name],
                    "m2b": current_shapes[name],
                    "legacy": legacy_shapes[name],
                }
                for name in sorted(required_tensors)
                if observed_shapes[name]
                not in {current_shapes[name], legacy_shapes[name]}
            }
            raise ValueError(
                "unsupported QRM checkpoint tensor layout; tensors may not be "
                f"padded or truncated: {mismatches or observed_shapes}"
            )

        if metadata_keys <= keys:
            schema = scalar_text(payload, "checkpoint_schema_version")
            declared_revision = scalar_text(payload, "architecture_revision")
            if schema != "QRMFormalCheckpointV1":
                raise ValueError(
                    f"unsupported QRM checkpoint schema: {schema}"
                )
            if declared_revision != revision:
                raise ValueError(
                    "QRM checkpoint revision/layout mismatch: "
                    f"{declared_revision} != {revision}"
                )

        tensors: dict[str, np.ndarray] = {}
        for name in sorted(required_tensors):
            value = np.asarray(payload[name])
            if not np.issubdtype(value.dtype, np.number):
                raise ValueError(f"QRM checkpoint tensor {name} is not numeric")
            if not np.all(np.isfinite(value)):
                raise ValueError(f"QRM checkpoint tensor {name} is non-finite")
            tensors[name] = value.copy()

    for name in ("w1", "b1", "w2", "b2"):
        setattr(model.coarse, name, tensors[f"coarse_{name}"])
        setattr(model.mlp, name, tensors[f"mlp_{name}"])
    model.meta_checkpoint_revision = revision
    return model


FORMAL_MODEL_TABLE: dict[str, str] = {
    FormalModelId.Q0.value: "Coarse-only industrial skill head",
    FormalModelId.Q1.value: "Coarse + bounded MLP residual (default continuous path)",
    FormalModelId.Q2.value: "Q1 + FailureContext (core Beta-1 ablation)",
}
