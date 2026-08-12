"""ADR-0020 M2C Q0/Q1/Q2 architecture with public track pointers.

``M2C_Q012_V2`` retains the frozen V1 coarse-skill semantics while adding two
heads on the same public-only hidden representation:

* a masked 9-class pointer (eight canonical public track slots plus ``NONE``),
* a 7-class destination enum (six registered bin cells plus ``NONE``).

Checkpoint loading is deliberately exact.  The revision, public-slot layout,
label order, metadata, every tensor shape, and finite numeric contents must all
match; this module never pads, truncates, or reinterprets a checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.coarse_policy import decode_coarse_intent
from xh_agent.policy.qrm_lite.context import build_context_vector, context_dim
from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV2,
    FailureContextV1,
    FailureType,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.flow_status import FLOW_STATUS
from xh_agent.policy.qrm_lite.mlp_refiner import MLPRefinerConfig, MLPResidualRefiner
from xh_agent.policy.qrm_lite.models_q012 import (
    FormalModelId,
    FormalPolicy,
    ModelOutput,
    RECOVERY_SKILLS,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import (
    PUBLIC_TRACK_ENCODING_REVISION,
    PUBLIC_TRACK_NORMALIZATION,
    PUBLIC_TRACK_POSE_FRAME,
    PUBLIC_TRACK_SLOT_COUNT,
    PUBLIC_TRACK_SLOT_FEATURE_DIM,
    PUBLIC_TRACK_SLOT_FEATURE_NAMES,
    canonical_track_slots,
    encode_public_track_slots,
)


ARCHITECTURE_REVISION = "M2C_Q012_V2"
CHECKPOINT_SCHEMA_VERSION = "QRMFormalCheckpointV2"
POINTER_LABELS = tuple(
    [f"SLOT_{index}" for index in range(PUBLIC_TRACK_SLOT_COUNT)] + ["NONE"]
)
DESTINATION_LABELS = tuple(
    [f"BIN_CELL_{index}" for index in range(6)] + ["NONE"]
)

if PUBLIC_TRACK_SLOT_COUNT != 8:
    raise RuntimeError("M2C_Q012_V2 requires exactly eight public track slots")
if PUBLIC_TRACK_SLOT_FEATURE_DIM != len(PUBLIC_TRACK_SLOT_FEATURE_NAMES):
    raise RuntimeError("M2C_Q012_V2 public slot feature contract changed")


@dataclass
class ModelOutputV2(ModelOutput):
    coarse: CoarseIntentV2 | None = None
    pointer_probabilities: np.ndarray | None = None
    destination_probabilities: np.ndarray | None = None


@dataclass(frozen=True)
class Q012V2TensorShapes:
    coarse_w1: tuple[int, ...]
    coarse_b1: tuple[int, ...]
    coarse_w2: tuple[int, ...]
    coarse_b2: tuple[int, ...]
    pointer_w: tuple[int, ...]
    pointer_b: tuple[int, ...]
    destination_w: tuple[int, ...]
    destination_b: tuple[int, ...]
    mlp_w1: tuple[int, ...]
    mlp_b1: tuple[int, ...]
    mlp_w2: tuple[int, ...]
    mlp_b2: tuple[int, ...]

    def as_dict(self) -> dict[str, tuple[int, ...]]:
        return {
            name: tuple(value)
            for name, value in self.__dict__.items()
        }


@dataclass
class FormalPolicyV2(FormalPolicy):
    """Formal Q0/Q1/Q2 policy with one shared public-slot representation."""

    model_id: FormalModelId
    pointer_w: np.ndarray = field(init=False, repr=False)
    pointer_b: np.ndarray = field(init=False, repr=False)
    destination_w: np.ndarray = field(init=False, repr=False)
    destination_b: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # FormalPolicy is not a dataclass; call its constructor explicitly.
        FormalPolicy.__init__(self, self.model_id)
        self.base_context_dim = context_dim(
            backbone_dim=self.cfg.backbone_dim,
            joint_dim=self.cfg.joint_dim,
            history_len=self.cfg.history_len,
            action_dim=self.cfg.action_dim,
            skill_vocab=self.cfg.context_skill_vocab,
        )
        self.context_dim = (
            self.base_context_dim
            + PUBLIC_TRACK_SLOT_COUNT * PUBLIC_TRACK_SLOT_FEATURE_DIM
        )
        self.coarse.in_dim = self.context_dim
        rng = np.random.default_rng(0)
        scale = np.sqrt(2.0 / (self.context_dim + self.cfg.hidden))
        self.coarse.w1 = rng.normal(
            0.0,
            scale,
            size=(self.context_dim, self.cfg.hidden),
        )
        self.coarse.b1 = np.zeros((self.cfg.hidden,), dtype=np.float64)
        self.pointer_w = rng.normal(
            0.0,
            np.sqrt(2.0 / (self.cfg.hidden + len(POINTER_LABELS))),
            size=(self.cfg.hidden, len(POINTER_LABELS)),
        )
        self.pointer_b = np.zeros((len(POINTER_LABELS),), dtype=np.float64)
        self.destination_w = rng.normal(
            0.0,
            np.sqrt(2.0 / (self.cfg.hidden + len(DESTINATION_LABELS))),
            size=(self.cfg.hidden, len(DESTINATION_LABELS)),
        )
        self.destination_b = np.zeros(
            (len(DESTINATION_LABELS),), dtype=np.float64
        )
        self.mlp = MLPResidualRefiner(
            MLPRefinerConfig(
                context_dim=self.context_dim,
                horizon=self.cfg.horizon,
                action_dim=self.cfg.action_dim,
                hidden=self.cfg.hidden * 2,
                max_translation_m=0.03,
            )
        )
        self.meta_checkpoint_revision = ARCHITECTURE_REVISION

    def _encode_v2(
        self,
        observation: QRMObservationV1,
        *,
        backbone_vec: np.ndarray | None = None,
    ) -> tuple[np.ndarray, Any]:
        observation_for_context = observation
        if not self.uses_failure_context:
            observation_for_context = observation.model_copy(deep=True)
            observation_for_context.failure_context = FailureContextV1()
        base = build_context_vector(
            observation_for_context,
            backbone_vec=backbone_vec,
            backbone_dim=self.cfg.backbone_dim,
            joint_dim=self.cfg.joint_dim,
            history_len=self.cfg.history_len,
            action_dim=self.cfg.action_dim,
            skill_vocab=self.cfg.context_skill_vocab,
        )
        slots = canonical_track_slots(
            observation.perception_tracks,
            k=PUBLIC_TRACK_SLOT_COUNT,
        )
        slot_features = np.asarray(
            encode_public_track_slots(slots),
            dtype=np.float64,
        ).reshape(-1)
        expected_slot_width = (
            PUBLIC_TRACK_SLOT_COUNT * PUBLIC_TRACK_SLOT_FEATURE_DIM
        )
        if slot_features.shape != (expected_slot_width,):
            raise ValueError(
                "public track slot encoder shape mismatch: "
                f"{slot_features.shape} != {(expected_slot_width,)}"
            )
        context = np.concatenate([base, slot_features])
        if context.shape != (self.context_dim,):
            raise ValueError(
                f"M2C context shape mismatch: {context.shape} != "
                f"{(self.context_dim,)}"
            )
        if not np.all(np.isfinite(context)):
            raise ValueError("M2C public model context contains non-finite values")
        return context, slots

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        values = np.asarray(logits, dtype=np.float64)
        maximum = np.max(values)
        unnormalized = np.exp(values - maximum)
        total = float(np.sum(unnormalized))
        if not np.isfinite(total) or total <= 0.0:
            raise ValueError("M2C head logits cannot be normalized")
        return unnormalized / total

    def _forward_shared(
        self,
        context: np.ndarray,
        valid_mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        hidden = np.tanh(
            np.clip(context @ self.coarse.w1 + self.coarse.b1, -20.0, 20.0)
        )
        coarse_logits = hidden @ self.coarse.w2 + self.coarse.b2
        pointer_logits = hidden @ self.pointer_w + self.pointer_b
        destination_logits = hidden @ self.destination_w + self.destination_b
        mask = np.asarray(valid_mask, dtype=bool)
        if mask.shape != (PUBLIC_TRACK_SLOT_COUNT,):
            raise ValueError(
                "public track valid mask shape mismatch: "
                f"{mask.shape} != {(PUBLIC_TRACK_SLOT_COUNT,)}"
            )
        pointer_logits = np.asarray(pointer_logits, dtype=np.float64).copy()
        pointer_logits[:PUBLIC_TRACK_SLOT_COUNT][~mask] = -np.inf
        if not np.all(np.isfinite(coarse_logits)):
            raise ValueError("M2C coarse head produced non-finite logits")
        if not np.isfinite(pointer_logits[-1]):
            raise ValueError("M2C pointer NONE logit is non-finite")
        if not np.all(np.isfinite(destination_logits)):
            raise ValueError("M2C destination head produced non-finite logits")
        return (
            coarse_logits,
            pointer_logits,
            destination_logits,
            self._softmax(pointer_logits),
            self._softmax(destination_logits),
        )

    def predict(
        self,
        obs: QRMObservationV1,
        *,
        nominal: np.ndarray | None = None,
        backbone_vec: np.ndarray | None = None,
        moveit_accept_fn=None,
    ) -> ModelOutputV2:
        context, slots = self._encode_v2(obs, backbone_vec=backbone_vec)
        (
            coarse_logits,
            pointer_logits,
            destination_logits,
            pointer_probabilities,
            destination_probabilities,
        ) = self._forward_shared(context, slots.valid_mask)
        coarse_v1 = decode_coarse_intent(coarse_logits, self.label_space)
        pointer_index = int(np.argmax(pointer_logits))
        destination_index = int(np.argmax(destination_logits))
        target_track_id = None
        if pointer_index < PUBLIC_TRACK_SLOT_COUNT:
            track = slots.tracks[pointer_index]
            if track is None:
                raise ValueError("masked public track slot was selected")
            target_track_id = track.track_id
        destination_cell = (
            None
            if destination_index == len(DESTINATION_LABELS) - 1
            else DESTINATION_LABELS[destination_index]
        )
        coarse_payload = coarse_v1.model_dump(mode="python")
        coarse_payload.pop("schema_version", None)
        coarse_payload["target_track_id"] = target_track_id
        coarse_payload["destination_cell"] = destination_cell
        coarse = CoarseIntentV2.model_validate(coarse_payload)
        recovery = (
            coarse.recovery_mode
            if coarse.recovery_mode in RECOVERY_SKILLS
            else coarse.skill_type
        )
        output = ModelOutputV2(
            model_id=self.model_id,
            coarse=coarse,
            recovery_skill=(
                recovery if recovery in RECOVERY_SKILLS else None
            ),
            used_failure_context=self.uses_failure_context,
            pointer_probabilities=pointer_probabilities,
            destination_probabilities=destination_probabilities,
            meta={
                "flow_status": FLOW_STATUS,
                "architecture_revision": ARCHITECTURE_REVISION,
                "context_dim": self.context_dim,
                "public_track_slot_count": PUBLIC_TRACK_SLOT_COUNT,
                "public_track_slot_feature_dim": PUBLIC_TRACK_SLOT_FEATURE_DIM,
                "target_track_id_provenance": (
                    "MODEL" if target_track_id is not None else "NONE"
                ),
                "destination_cell_provenance": (
                    "MODEL" if destination_cell is not None else "NONE"
                ),
            },
        )
        if not self.uses_residual:
            return output
        if nominal is None:
            raise ValueError("Q1/Q2 require geometric nominal action chunk")
        residual = self.mlp.forward(context, nominal)
        output.residual = residual
        output.residual_safety = self.safety.combine_and_filter(
            nominal,
            residual,
            moveit_accept_fn=moveit_accept_fn,
        )
        return output

    def tensor_shapes(self) -> Q012V2TensorShapes:
        return Q012V2TensorShapes(
            coarse_w1=self.coarse.w1.shape,
            coarse_b1=self.coarse.b1.shape,
            coarse_w2=self.coarse.w2.shape,
            coarse_b2=self.coarse.b2.shape,
            pointer_w=self.pointer_w.shape,
            pointer_b=self.pointer_b.shape,
            destination_w=self.destination_w.shape,
            destination_b=self.destination_b.shape,
            mlp_w1=self.mlp.w1.shape,
            mlp_b1=self.mlp.b1.shape,
            mlp_w2=self.mlp.w2.shape,
            mlp_b2=self.mlp.b2.shape,
        )

    def checkpoint_metadata(self) -> dict[str, Any]:
        return {
            "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
            "architecture_revision": ARCHITECTURE_REVISION,
            "model_id": self.model_id.value,
            "base_context_dim": self.base_context_dim,
            "context_dim": self.context_dim,
            "hidden_dim": self.cfg.hidden,
            "horizon": self.cfg.horizon,
            "action_dim": self.cfg.action_dim,
            "public_track_slot_count": PUBLIC_TRACK_SLOT_COUNT,
            "public_track_slot_feature_dim": PUBLIC_TRACK_SLOT_FEATURE_DIM,
            "public_track_encoding_revision": PUBLIC_TRACK_ENCODING_REVISION,
            "public_track_pose_frame": PUBLIC_TRACK_POSE_FRAME,
            "public_track_normalization": PUBLIC_TRACK_NORMALIZATION,
            "slot_feature_names": list(PUBLIC_TRACK_SLOT_FEATURE_NAMES),
            "pointer_labels": list(POINTER_LABELS),
            "destination_labels": list(DESTINATION_LABELS),
            "skill_labels": list(self.label_space.skills),
            "grasp_family_labels": list(self.label_space.grasp_families),
            "recovery_mode_labels": list(self.label_space.recovery_modes),
            "failure_type_labels": [item.value for item in FailureType],
            "n_translation_bins": self.label_space.n_trans_bins,
            "n_rotation_bins": self.label_space.n_rot_bins,
            "context_skill_vocab": list(self.cfg.context_skill_vocab),
            "tensor_shapes": {
                name: list(shape)
                for name, shape in self.tensor_shapes().as_dict().items()
            },
        }


TENSOR_ATTRIBUTES = {
    "coarse_w1": ("coarse", "w1"),
    "coarse_b1": ("coarse", "b1"),
    "coarse_w2": ("coarse", "w2"),
    "coarse_b2": ("coarse", "b2"),
    "pointer_w": (None, "pointer_w"),
    "pointer_b": (None, "pointer_b"),
    "destination_w": (None, "destination_w"),
    "destination_b": (None, "destination_b"),
    "mlp_w1": ("mlp", "w1"),
    "mlp_b1": ("mlp", "b1"),
    "mlp_w2": ("mlp", "w2"),
    "mlp_b2": ("mlp", "b2"),
}


def build_formal_model_v2(
    model_id: str | FormalModelId,
) -> FormalPolicyV2:
    parsed = (
        model_id
        if isinstance(model_id, FormalModelId)
        else FormalModelId(model_id)
    )
    return FormalPolicyV2(parsed)


def _tensor(model: FormalPolicyV2, name: str) -> np.ndarray:
    owner, attribute = TENSOR_ATTRIBUTES[name]
    source = model if owner is None else getattr(model, owner)
    return np.asarray(getattr(source, attribute))


def save_formal_checkpoint_v2(
    path: str | Path,
    model: FormalPolicyV2,
) -> None:
    metadata_json = json.dumps(
        model.checkpoint_metadata(),
        sort_keys=True,
        separators=(",", ":"),
    )
    tensors = {name: _tensor(model, name) for name in TENSOR_ATTRIBUTES}
    for name, value in tensors.items():
        if not np.issubdtype(value.dtype, np.number):
            raise ValueError(f"M2C checkpoint tensor {name} is not numeric")
        if not np.all(np.isfinite(value)):
            raise ValueError(f"M2C checkpoint tensor {name} is non-finite")
    np.savez(
        path,
        metadata_json=metadata_json,
        **tensors,
    )


def load_formal_checkpoint_v2(
    path: str | Path,
    *,
    expected_model_id: str | None = None,
) -> FormalPolicyV2:
    required = {"metadata_json", *TENSOR_ATTRIBUTES}
    with np.load(path, allow_pickle=False) as payload:
        keys = set(payload.files)
        missing = sorted(required - keys)
        unknown = sorted(keys - required)
        if missing:
            raise ValueError(f"M2C checkpoint missing fields: {missing}")
        if unknown:
            raise ValueError(f"M2C checkpoint has unsupported fields: {unknown}")
        raw_metadata = np.asarray(payload["metadata_json"])
        if raw_metadata.shape != ():
            raise ValueError("M2C checkpoint metadata_json must be scalar")
        try:
            metadata = json.loads(str(raw_metadata.item()))
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("M2C checkpoint metadata_json is invalid") from error
        if not isinstance(metadata, dict):
            raise ValueError("M2C checkpoint metadata must be an object")
        model_id = metadata.get("model_id")
        if expected_model_id is not None and model_id != expected_model_id:
            raise ValueError(
                f"M2C checkpoint model mismatch: {model_id} != "
                f"{expected_model_id}"
            )
        try:
            model = build_formal_model_v2(str(model_id))
        except ValueError as error:
            raise ValueError(f"unsupported M2C checkpoint model: {model_id}") from error
        expected_metadata = model.checkpoint_metadata()
        if metadata != expected_metadata:
            differing = sorted(
                key
                for key in set(metadata) | set(expected_metadata)
                if metadata.get(key) != expected_metadata.get(key)
            )
            raise ValueError(
                "M2C checkpoint metadata/layout mismatch: "
                f"{differing}"
            )
        expected_shapes = model.tensor_shapes().as_dict()
        tensors: dict[str, np.ndarray] = {}
        for name, expected_shape in expected_shapes.items():
            value = np.asarray(payload[name])
            if value.shape != expected_shape:
                raise ValueError(
                    f"M2C checkpoint tensor {name} shape mismatch: "
                    f"{value.shape} != {expected_shape}"
                )
            if not np.issubdtype(value.dtype, np.number):
                raise ValueError(f"M2C checkpoint tensor {name} is not numeric")
            if not np.all(np.isfinite(value)):
                raise ValueError(f"M2C checkpoint tensor {name} is non-finite")
            tensors[name] = value.copy()

    for name, value in tensors.items():
        owner, attribute = TENSOR_ATTRIBUTES[name]
        target = model if owner is None else getattr(model, owner)
        setattr(target, attribute, value)
    model.meta_checkpoint_revision = ARCHITECTURE_REVISION
    return model
