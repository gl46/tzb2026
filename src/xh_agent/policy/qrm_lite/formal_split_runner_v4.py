"""Versioned formal wire contracts for the ADR-0024 V4 model path.

The historical V2 protocol remains byte-for-byte untouched.  This module
defines the first V4-only transport boundary: a replayed
``FormalPublicObservationV4`` is HMAC-bound to the trained ``M2C_Q012_V4``
bundle, decoded through the frozen K=8 pointer vocabulary, and copied into the
Isaac execute request.  It does not construct waypoints, execute physics, or
claim that the Phase-2 deployment bindings are available.
"""

from __future__ import annotations

import hmac
import math
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, TypeVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.contracts import CoarseIntentV2, FailureType
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
    validate_executed_intent_history_v2,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    DESTINATION_CLASS_LABELS,
    HeadPredictionV2,
    QWEN_HEAD_TENSORS,
    QWEN_MODEL_ID,
    QWEN_MODEL_REVISION,
    REGISTERED_DESTINATION_CELLS,
    SHA256_PATTERN,
    canonical_sha256,
    hmac_sha256,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2C_Q012_V4_SKILL_LABELS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    POINTER_CLASS_LABELS,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    PUBLIC_TRACK_POINTER_CLASS_COUNT_V4,
    PUBLIC_TRACK_POINTER_NONE_INDEX_V4,
)
from xh_agent.policy.qrm_lite.qwen_prompt_v4 import render_qwen_public_prompt_v4
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    ParameterProvenanceV2,
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
    RuntimeSkillRequestV2,
    resolve_registered_skill_v2,
    validate_runtime_mapping_v2,
)


FORMAL_WIRE_PROTOCOL_V4 = "M2C_FORMAL_SPLIT_RUNNER_V4"
FORMAL_INFERENCE_PATH_V4 = "/v1/m2c/qwen-coarse-v4/predict"
QWEN_ARCHITECTURE_REVISION_V4 = "M2C_Q012_V4"
PUBLIC_OBSERVATION_REVISION_V4 = "FormalPublicObservationV4"
PUBLIC_TRACK_ASSOCIATOR_REVISION_V4 = "PublicTrackAssociatorV2"

_T = TypeVar("_T", bound=BaseModel)
IsaacWireMessageTypeV4 = Literal[
    "ISAAC_CAPTURE_RESPONSE_V4",
    "ISAAC_EXECUTE_REQUEST_V4",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QwenBundleRuntimeBindingV4(StrictModel):
    """Exact V4 trained bundle and offline model snapshot used by node2."""

    schema_version: Literal["QwenBundleRuntimeBindingV4"] = "QwenBundleRuntimeBindingV4"
    architecture_revision: Literal["M2C_Q012_V4"] = "M2C_Q012_V4"
    public_observation_revision: Literal["FormalPublicObservationV4"] = "FormalPublicObservationV4"
    public_track_associator_revision: Literal["PublicTrackAssociatorV2"] = "PublicTrackAssociatorV2"
    public_track_candidate_revision: Literal["PublicTrackCandidateV4"] = "PublicTrackCandidateV4"
    public_track_candidate_count: Literal[8] = 8
    pointer_class_count: Literal[9] = 9
    model_id: Literal[QWEN_MODEL_ID] = QWEN_MODEL_ID
    model_revision: Literal[QWEN_MODEL_REVISION] = QWEN_MODEL_REVISION
    bundle_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    bundle_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    bundle_sha256: str = Field(pattern=SHA256_PATTERN)
    head_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    head_deployment_file_sha256: str = Field(pattern=SHA256_PATTERN)
    head_deployment_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    checkpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    adapter_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    training_dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    training_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    training_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    s6_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    s6_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    association_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_selector_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    model_cache_dir: str = Field(min_length=1)
    model_cache_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    local_files_only: Literal[True] = True
    failure_context: Literal["on", "off"]
    training_complete: Literal[True] = True
    physical_evaluation_executed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_offline_revision_snapshot(self) -> "QwenBundleRuntimeBindingV4":
        path = Path(self.model_cache_dir)
        expected_suffix = Path(
            "models--Qwen--Qwen3.5-4B",
            "snapshots",
            QWEN_MODEL_REVISION,
        )
        if not path.is_absolute() or tuple(path.parts[-3:]) != expected_suffix.parts:
            raise ValueError("formal V4 Qwen cache is not the frozen revision snapshot")
        return self


class FormalInferenceRequestV4(StrictModel):
    schema_version: Literal["FormalInferenceRequestV4"] = "FormalInferenceRequestV4"
    protocol: Literal[FORMAL_WIRE_PROTOCOL_V4] = FORMAL_WIRE_PROTOCOL_V4
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    request_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    sent_at_ns: int = Field(gt=0)
    instruction: Literal["recover from a public PATH_BLOCKED manipulation failure"] = (
        "recover from a public PATH_BLOCKED manipulation failure"
    )
    current_phase: Literal["RECOVERY"] = "RECOVERY"
    failure_type: Literal["PATH_BLOCKED"] = "PATH_BLOCKED"
    executed_intent_history: list[PublicExecutedIntentHistoryItemV2] = Field(
        default_factory=list,
        max_length=7,
    )
    prior_decisions_sha256: str = Field(pattern=SHA256_PATTERN)
    bundle: QwenBundleRuntimeBindingV4
    observation: FormalPublicObservationV4
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def replayed_observation_and_history_are_exact(self) -> "FormalInferenceRequestV4":
        validate_executed_intent_history_v2(
            self.executed_intent_history,
            expected_length=self.decision_index,
        )
        if self.prior_decisions_sha256 != canonical_sha256(self.executed_intent_history):
            raise ValueError("formal V4 prior-decisions hash differs from public history")
        if any(
            item.execution_attribution != "MODEL_SELECTED_REGISTERED_SKILL"
            for item in self.executed_intent_history
        ):
            raise ValueError("formal V4 runtime history contains non-model execution")
        if self.sent_at_ns <= self.observation.captured_at_ns:
            raise ValueError("formal V4 inference request does not follow its fresh capture")
        if (
            self.observation.association_deployment_sha256
            != self.bundle.association_deployment_sha256
            or self.observation.association_deployment.capture_source_implementation_sha256
            != self.bundle.capture_source_implementation_sha256
            or self.observation.declared_attribute_binding.selector_source_implementation_sha256
            != self.bundle.declared_attribute_selector_implementation_sha256
        ):
            raise ValueError("formal V4 observation differs from frozen public deployment")
        return self


class SignedInferenceRequestV4(StrictModel):
    schema_version: Literal["SignedInferenceRequestV4"] = "SignedInferenceRequestV4"
    payload: FormalInferenceRequestV4
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    hmac_sha256: str = Field(pattern=SHA256_PATTERN)


class FormalInferenceResponseV4(StrictModel):
    schema_version: Literal["FormalInferenceResponseV4"] = "FormalInferenceResponseV4"
    protocol: Literal[FORMAL_WIRE_PROTOCOL_V4] = FORMAL_WIRE_PROTOCOL_V4
    run_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    request_payload_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_payload_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    executed_intent_history_sha256: str = Field(pattern=SHA256_PATTERN)
    completed_at_ns: int = Field(gt=0)
    bundle: QwenBundleRuntimeBindingV4
    prompt_sha256: str = Field(pattern=SHA256_PATTERN)
    pooled_feature_sha256: str = Field(pattern=SHA256_PATTERN)
    head_tensor_sha256: dict[str, str]
    skill: HeadPredictionV2
    pointer: HeadPredictionV2
    destination: HeadPredictionV2
    intent: CoarseIntentV2
    confidence: float = Field(ge=0.0, le=1.0)
    model_owned: Literal[True] = True
    task_spec_fallback_used: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_v4_three_head_decode(self) -> "FormalInferenceResponseV4":
        if set(self.head_tensor_sha256) != set(QWEN_HEAD_TENSORS):
            raise ValueError("formal V4 response does not bind the exact three-head tensors")
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in self.head_tensor_sha256.values()
        ):
            raise ValueError("formal V4 response contains a malformed tensor hash")
        exact = (
            (self.skill, list(M2C_Q012_V4_SKILL_LABELS)),
            (self.pointer, list(POINTER_CLASS_LABELS)),
            (self.destination, list(DESTINATION_CLASS_LABELS)),
        )
        for head, labels in exact:
            if head.labels != labels:
                raise ValueError("formal response label order is not M2C_Q012_V4")
        if self.pointer.selected_index == PUBLIC_TRACK_POINTER_NONE_INDEX_V4:
            if self.intent.target_track_id is not None:
                raise ValueError("formal V4 pointer NONE differs from decoded target")
        elif self.intent.target_track_id is None:
            raise ValueError("formal V4 selected pointer lost its public literal")
        expected_destination = (
            None if self.destination.selected_label == "NONE" else self.destination.selected_label
        )
        if self.intent.skill_type != self.skill.selected_label:
            raise ValueError("formal V4 intent skill differs from skill head")
        if self.intent.destination_cell != expected_destination:
            raise ValueError("formal V4 intent destination differs from destination head")
        if self.intent.failure_type_aux != FailureType.PATH_BLOCKED:
            raise ValueError("formal V4 response lost PATH_BLOCKED context")
        return self


class SignedInferenceResponseV4(StrictModel):
    schema_version: Literal["SignedInferenceResponseV4"] = "SignedInferenceResponseV4"
    payload: FormalInferenceResponseV4
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    hmac_sha256: str = Field(pattern=SHA256_PATTERN)


class IsaacCaptureResponseV4(StrictModel):
    schema_version: Literal["IsaacCaptureResponseV4"] = "IsaacCaptureResponseV4"
    protocol: Literal[FORMAL_WIRE_PROTOCOL_V4] = FORMAL_WIRE_PROTOCOL_V4
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation: FormalPublicObservationV4
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    real_physics: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def observation_digest_is_exact(self) -> "IsaacCaptureResponseV4":
        if self.formal_observation_sha256 != self.observation.wire_sha256:
            raise ValueError("Isaac V4 capture response observation digest differs")
        return self


class RuntimeSkillRequestV4(StrictModel):
    """V4 role-ranked runtime request; no lexicographic V2 slot reinterpretation."""

    schema_version: Literal["RuntimeSkillRequestV4"] = "RuntimeSkillRequestV4"
    model_output_schema: Literal["CoarseIntentV2"] = "CoarseIntentV2"
    public_track_candidate_revision: Literal["PublicTrackCandidateV4"] = "PublicTrackCandidateV4"
    canonical_public_tracks_sha256: str = Field(pattern=SHA256_PATTERN)
    model_class_id: str = Field(min_length=1)
    skill: str = Field(min_length=1)
    task_target_track_id: Literal[None] = None
    model_target_track_id: str | None = None
    model_target_slot: int | None = Field(default=None, ge=0, le=7)
    target_track_provenance: ParameterProvenanceV2 = ParameterProvenanceV2.NONE
    canonical_track_ids: list[str | None] = Field(min_length=8, max_length=8)
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_provenance: dict[str, ParameterProvenanceV2] = Field(default_factory=dict)
    coordinate_frame: str = Field(min_length=1)
    units: str = Field(min_length=1)
    current_phase: Literal["RECOVERY"] = "RECOVERY"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    residual_values: list[list[float]] | None = None
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def role_ranked_slots_and_pointer_are_exact(self) -> "RuntimeSkillRequestV4":
        populated = [item for item in self.canonical_track_ids if item is not None]
        if (
            self.canonical_track_ids[: len(populated)] != populated
            or any(item is not None for item in self.canonical_track_ids[len(populated) :])
            or len(populated) != len(set(populated))
        ):
            raise ValueError("formal V4 runtime candidate slots are not a unique prefix")
        if self.model_target_track_id is None:
            if (
                self.model_target_slot is not None
                or self.target_track_provenance != ParameterProvenanceV2.NONE
            ):
                raise ValueError("formal V4 NONE pointer retains a slot/provenance")
        elif (
            self.model_target_slot is None
            or self.canonical_track_ids[self.model_target_slot] != self.model_target_track_id
            or self.target_track_provenance != ParameterProvenanceV2.MODEL
        ):
            raise ValueError("formal V4 model pointer differs from its role-ranked slot")
        if any(
            value == ParameterProvenanceV2.TASK_SPEC_FALLBACK
            for value in self.parameter_provenance.values()
        ):
            raise ValueError("formal V4 runtime parameters contain TaskSpec fallback")
        return self


class IsaacExecuteRequestV4(StrictModel):
    schema_version: Literal["IsaacExecuteRequestV4"] = "IsaacExecuteRequestV4"
    protocol: Literal[FORMAL_WIRE_PROTOCOL_V4] = FORMAL_WIRE_PROTOCOL_V4
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_public_tracks_sha256: str = Field(pattern=SHA256_PATTERN)
    inference_response_sha256: str = Field(pattern=SHA256_PATTERN)
    executed_intent_history_sha256: str = Field(pattern=SHA256_PATTERN)
    observation: FormalPublicObservationV4
    runtime_request: RuntimeSkillRequestV4
    task_spec_fallback_allowed: Literal[False] = False
    requested_physical_skill_count: Literal[1] = 1
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def full_v4_capture_and_pointer_are_bound(self) -> "IsaacExecuteRequestV4":
        observation = self.observation
        expected = {
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "canonical_public_tracks_sha256": observation.canonical_public_tracks_sha256,
        }
        if any(getattr(self, name) != value for name, value in expected.items()):
            raise ValueError("Isaac V4 execute request crosses its replayed observation")
        runtime = self.runtime_request
        if runtime.canonical_track_ids != observation.canonical_slots:
            raise ValueError("formal V4 runtime slots differ from replayed K=8 candidates")
        if runtime.canonical_public_tracks_sha256 != observation.canonical_public_tracks_sha256:
            raise ValueError("formal V4 runtime candidate digest differs from replayed candidates")
        return self


class SignedIsaacWireMessageV4(StrictModel):
    schema_version: Literal["SignedIsaacWireMessageV4"] = "SignedIsaacWireMessageV4"
    message_type: IsaacWireMessageTypeV4
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    hmac_sha256: str = Field(pattern=SHA256_PATTERN)


def _verify_payload_hmac(
    payload: BaseModel,
    payload_sha256: str,
    signature: str,
    secret: bytes,
) -> None:
    expected_payload = canonical_sha256(payload)
    expected_hmac = hmac_sha256(payload, secret)
    if not hmac.compare_digest(payload_sha256, expected_payload):
        raise ValueError("formal V4 payload SHA-256 mismatch")
    if not hmac.compare_digest(signature, expected_hmac):
        raise ValueError("formal V4 payload HMAC mismatch")


def sign_inference_request_v4(
    payload: FormalInferenceRequestV4,
    secret: bytes,
) -> SignedInferenceRequestV4:
    return SignedInferenceRequestV4(
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        hmac_sha256=hmac_sha256(payload, secret),
    )


def verify_inference_request_v4(
    raw: Mapping[str, Any],
    secret: bytes,
) -> SignedInferenceRequestV4:
    message = SignedInferenceRequestV4.model_validate(raw)
    _verify_payload_hmac(
        message.payload,
        message.payload_sha256,
        message.hmac_sha256,
        secret,
    )
    return message


def sign_inference_response_v4(
    payload: FormalInferenceResponseV4,
    secret: bytes,
) -> SignedInferenceResponseV4:
    return SignedInferenceResponseV4(
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        hmac_sha256=hmac_sha256(payload, secret),
    )


def verify_inference_response_v4(
    raw: Mapping[str, Any],
    secret: bytes,
) -> SignedInferenceResponseV4:
    message = SignedInferenceResponseV4.model_validate(raw)
    _verify_payload_hmac(
        message.payload,
        message.payload_sha256,
        message.hmac_sha256,
        secret,
    )
    return message


def sign_isaac_wire_message_v4(
    message_type: IsaacWireMessageTypeV4,
    payload: BaseModel,
    secret: bytes,
) -> SignedIsaacWireMessageV4:
    dumped = payload.model_dump(mode="json")
    payload_sha256 = canonical_sha256(dumped)
    authenticated = {
        "message_type": message_type,
        "payload": dumped,
        "payload_sha256": payload_sha256,
    }
    return SignedIsaacWireMessageV4(
        message_type=message_type,
        payload=dumped,
        payload_sha256=payload_sha256,
        hmac_sha256=hmac_sha256(authenticated, secret),
    )


def verify_isaac_wire_message_v4(
    raw: Mapping[str, Any],
    secret: bytes,
    *,
    expected_type: IsaacWireMessageTypeV4,
    model: type[_T],
) -> tuple[SignedIsaacWireMessageV4, _T]:
    message = SignedIsaacWireMessageV4.model_validate(raw)
    if message.message_type != expected_type:
        raise ValueError("formal V4 Isaac message type differs")
    if message.payload_sha256 != canonical_sha256(message.payload):
        raise ValueError("formal V4 Isaac payload SHA-256 mismatch")
    authenticated = {
        "message_type": message.message_type,
        "payload": message.payload,
        "payload_sha256": message.payload_sha256,
    }
    if not hmac.compare_digest(message.hmac_sha256, hmac_sha256(authenticated, secret)):
        raise ValueError("formal V4 Isaac wire HMAC mismatch")
    return message, model.model_validate(message.payload)


def runtime_qwen_prompt_v4(request: FormalInferenceRequestV4) -> str:
    """Render the exact V4 training-time public prompt from a wire request."""

    return render_qwen_public_prompt_v4(
        candidate_payload=request.observation.observation.candidate_payload,
        decision_index=request.decision_index,
        executed_intent_history=request.executed_intent_history,
        use_failure_context=request.bundle.failure_context == "on",
    )


def _wire_logits(
    values: Sequence[float],
    *,
    expected: int,
    mask: Sequence[bool] | None = None,
) -> list[float | None]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.shape != (expected,):
        raise ValueError("formal V4 model head has the wrong shape")
    mask_array = (
        np.ones(array.shape, dtype=bool)
        if mask is None
        else np.asarray(mask, dtype=bool).reshape(-1)
    )
    if mask_array.shape != array.shape:
        raise ValueError("formal V4 head mask/logit shape mismatch")
    output: list[float | None] = []
    for valid, value in zip(mask_array.tolist(), array.tolist()):
        if not valid:
            output.append(None)
        elif not math.isfinite(value):
            raise ValueError("formal V4 unmasked head logit is NaN/Inf")
        else:
            output.append(float(value))
    return output


def _selected_index(values: Sequence[float | None]) -> int:
    return max(
        ((index, value) for index, value in enumerate(values) if value is not None),
        key=lambda item: (float(item[1]), -item[0]),
    )[0]


def _head_confidence(values: Sequence[float | None]) -> float:
    finite = np.asarray([value for value in values if value is not None], dtype=np.float64)
    exponent = np.exp(finite - np.max(finite))
    return float(np.max(exponent / exponent.sum()))


def build_inference_response_from_logits_v4(
    request: FormalInferenceRequestV4,
    *,
    skill_logits: Sequence[float],
    pointer_logits: Sequence[float],
    destination_logits: Sequence[float],
    prompt_sha256: str,
    pooled_feature_sha256: str,
    head_tensor_sha256: dict[str, str],
    completed_at_ns: int,
) -> FormalInferenceResponseV4:
    """Decode the exact three V4 heads against the replayed K=8 slots."""

    if completed_at_ns <= request.sent_at_ns:
        raise ValueError("formal V4 inference completion does not follow its request")
    valid_mask = request.observation.observation.candidate_payload.valid_mask
    skill_wire = _wire_logits(
        skill_logits,
        expected=len(M2C_Q012_V4_SKILL_LABELS),
    )
    pointer_wire = _wire_logits(
        pointer_logits,
        expected=PUBLIC_TRACK_POINTER_CLASS_COUNT_V4,
        mask=[*valid_mask, True],
    )
    destination_wire = _wire_logits(
        destination_logits,
        expected=len(DESTINATION_CLASS_LABELS),
    )
    skill_index = _selected_index(skill_wire)
    pointer_index = _selected_index(pointer_wire)
    destination_index = _selected_index(destination_wire)
    target_track_id = (
        None
        if pointer_index == PUBLIC_TRACK_POINTER_NONE_INDEX_V4
        else request.observation.canonical_slots[pointer_index]
    )
    destination_cell = (
        None
        if DESTINATION_CLASS_LABELS[destination_index] == "NONE"
        else REGISTERED_DESTINATION_CELLS[destination_index]
    )
    skill = M2C_Q012_V4_SKILL_LABELS[skill_index]
    intent = CoarseIntentV2(
        skill_type=skill,
        target_track_id=target_track_id,
        destination_cell=destination_cell,
        grasp_family="top_down" if skill in {"GRASP", "REGRASP"} else "unknown",
        reobserve_flag=skill == "REOBSERVE",
        failure_type_aux=FailureType.PATH_BLOCKED,
    )
    return FormalInferenceResponseV4(
        run_id=request.run_id,
        request_id=request.request_id,
        decision_index=request.decision_index,
        request_payload_sha256=canonical_sha256(request),
        formal_observation_sha256=request.observation.wire_sha256,
        candidate_payload_sha256=request.observation.canonical_public_tracks_sha256,
        capture_receipt_sha256=request.observation.capture_receipt_sha256,
        executed_intent_history_sha256=request.prior_decisions_sha256,
        completed_at_ns=completed_at_ns,
        bundle=request.bundle,
        prompt_sha256=prompt_sha256,
        pooled_feature_sha256=pooled_feature_sha256,
        head_tensor_sha256=head_tensor_sha256,
        skill=HeadPredictionV2(
            labels=list(M2C_Q012_V4_SKILL_LABELS),
            logits=skill_wire,
            selected_index=skill_index,
            selected_label=M2C_Q012_V4_SKILL_LABELS[skill_index],
        ),
        pointer=HeadPredictionV2(
            labels=list(POINTER_CLASS_LABELS),
            logits=pointer_wire,
            selected_index=pointer_index,
            selected_label=POINTER_CLASS_LABELS[pointer_index],
        ),
        destination=HeadPredictionV2(
            labels=list(DESTINATION_CLASS_LABELS),
            logits=destination_wire,
            selected_index=destination_index,
            selected_label=DESTINATION_CLASS_LABELS[destination_index],
        ),
        intent=intent,
        confidence=min(
            _head_confidence(skill_wire),
            _head_confidence(pointer_wire),
            _head_confidence(destination_wire),
        ),
    )


def validate_inference_response_binding_v4(
    request: FormalInferenceRequestV4,
    response: FormalInferenceResponseV4,
) -> None:
    """Cross-check every response field that requires the originating request."""

    expected = {
        "run_id": request.run_id,
        "request_id": request.request_id,
        "decision_index": request.decision_index,
        "request_payload_sha256": canonical_sha256(request),
        "formal_observation_sha256": request.observation.wire_sha256,
        "candidate_payload_sha256": request.observation.canonical_public_tracks_sha256,
        "capture_receipt_sha256": request.observation.capture_receipt_sha256,
        "executed_intent_history_sha256": request.prior_decisions_sha256,
        "bundle": request.bundle,
    }
    if any(getattr(response, name) != value for name, value in expected.items()):
        raise ValueError("formal V4 inference response crosses request/bundle/observation")
    if response.completed_at_ns <= request.sent_at_ns:
        raise ValueError("formal V4 inference response completion precedes request")
    pointer_index = response.pointer.selected_index
    selected_track = (
        None
        if pointer_index == PUBLIC_TRACK_POINTER_NONE_INDEX_V4
        else request.observation.canonical_slots[pointer_index]
    )
    if response.intent.target_track_id != selected_track:
        raise ValueError("formal V4 decoded pointer differs from the fresh candidate literal")


def runtime_request_from_inference_v4(
    request: FormalInferenceRequestV4,
    response: FormalInferenceResponseV4,
    registry: RuntimeSkillRegistryV2,
) -> RuntimeSkillRequestV4:
    """Bind one V4 model response to its role-ranked slots without V2 resorting."""

    validate_inference_response_binding_v4(request, response)
    pointer_index = response.pointer.selected_index
    selected_track = (
        None
        if pointer_index == PUBLIC_TRACK_POINTER_NONE_INDEX_V4
        else request.observation.canonical_slots[pointer_index]
    )
    selected_skill = response.intent.skill_type
    canonical, alias, _ = resolve_registered_skill_v2(registry, selected_skill)
    spec = registry.skills.get(canonical or "")
    class_candidates = [
        f"coarse.recovery.{selected_skill}",
        f"coarse.skill.{selected_skill}",
    ]
    model_class_id = next(
        (
            candidate
            for candidate in class_candidates
            if spec is not None and candidate in spec.model_class_ids
        ),
        class_candidates[0],
    )
    parameters: dict[str, object] = {}
    provenance: dict[str, ParameterProvenanceV2] = {}
    allowed = (
        set(spec.required_parameters) | set(spec.optional_parameters) if spec is not None else set()
    )
    if (
        spec is not None
        and alias is None
        and "grasp_family" in allowed
        and response.intent.grasp_family != "unknown"
    ):
        parameters["grasp_family"] = response.intent.grasp_family
        provenance["grasp_family"] = ParameterProvenanceV2.MODEL
    if response.intent.destination_cell is not None:
        parameters["destination"] = response.intent.destination_cell
        provenance["destination"] = ParameterProvenanceV2.MODEL
    return RuntimeSkillRequestV4(
        model_output_schema=registry.model_output_schema,
        canonical_public_tracks_sha256=request.observation.canonical_public_tracks_sha256,
        model_class_id=model_class_id,
        skill=selected_skill,
        task_target_track_id=None,
        model_target_track_id=selected_track,
        model_target_slot=(None if selected_track is None else pointer_index),
        target_track_provenance=(
            ParameterProvenanceV2.NONE if selected_track is None else ParameterProvenanceV2.MODEL
        ),
        canonical_track_ids=request.observation.canonical_slots,
        parameters=parameters,
        parameter_provenance=provenance,
        coordinate_frame=(spec.coordinate_frame if spec is not None else "UNRESOLVED"),
        units=(spec.units if spec is not None else "UNRESOLVED"),
        current_phase="RECOVERY",
        confidence=response.confidence,
        residual_values=None,
    )


def validate_runtime_mapping_v4(
    request: RuntimeSkillRequestV4,
    observation: FormalPublicObservationV4,
    registry: RuntimeSkillRegistryV2,
    *,
    ik_check: Any = None,
    collision_check: Any = None,
    safety_check: Any = None,
    bin_cell_targets_provider: Any = None,
) -> RuntimeSkillMappingResultV2:
    """Apply the frozen V2 registry semantics without reordering V4 on wire.

    The V2 registry's membership logic predates role-ranked candidates and
    requires lexicographic slots.  A local projection is therefore used only
    inside that validator.  The selected public literal is unchanged and the
    returned slot/gate trace are restored to the externally frozen V4 index.
    """

    if (
        request.canonical_track_ids != observation.canonical_slots
        or request.canonical_public_tracks_sha256 != observation.canonical_public_tracks_sha256
    ):
        raise ValueError("formal V4 mapping request differs from replayed candidates")
    populated = [item for item in request.canonical_track_ids if item is not None]
    sorted_ids = sorted(populated)
    projected_slots: list[str | None] = [*sorted_ids, *([None] * (8 - len(sorted_ids)))]
    projected_target_slot = (
        None
        if request.model_target_track_id is None
        else projected_slots.index(request.model_target_track_id)
    )
    projected = RuntimeSkillRequestV2(
        model_output_schema=request.model_output_schema,
        model_class_id=request.model_class_id,
        skill=request.skill,
        task_target_track_id=None,
        model_target_track_id=request.model_target_track_id,
        model_target_slot=projected_target_slot,
        target_track_provenance=request.target_track_provenance,
        canonical_track_ids=projected_slots,
        parameters=request.parameters,
        parameter_provenance=request.parameter_provenance,
        coordinate_frame=request.coordinate_frame,
        units=request.units,
        current_phase=request.current_phase,
        confidence=request.confidence,
        residual_values=request.residual_values,
    )
    result = validate_runtime_mapping_v2(
        projected,
        registry,
        ik_check=ik_check,
        collision_check=collision_check,
        safety_check=safety_check,
        bin_cell_targets_provider=bin_cell_targets_provider,
    )
    if result.target_track_id is None:
        return result
    external_slot = request.canonical_track_ids.index(result.target_track_id)
    trace = [dict(entry) for entry in result.gate_trace]
    for entry in trace:
        if entry.get("gate") == "track" and entry.get("status") == "PASS":
            entry["slot"] = external_slot
    return result.model_copy(
        update={
            "target_track_slot": external_slot,
            "gate_trace": trace,
        }
    )
