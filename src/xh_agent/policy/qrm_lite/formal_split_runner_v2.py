"""Fail-closed wire contracts for the split M2C model-owned chain runner.

The trained Qwen world model runs on the training host while Isaac remains a
single, persistent physics process on the simulator host.  Every wire message
is canonical-JSON/HMAC bound.  The policy request contains only a fresh public
RGB-D capture and public tracks; simulator identity and Teacher fields have no
place in the schema.

This module does not implement or emulate physics.  In particular, it cannot
manufacture :class:`PhysicalSkillReceiptV2`: that receipt is accepted only in
a signed response from a separately frozen real-Isaac endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace
from typing import Any, Literal, Mapping, Sequence, TypeVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV2,
    FailureContextV1,
    FailureType,
    PerceptionTrackV1,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
    prompt_executed_intent_history_v2,
    validate_executed_intent_history_v2,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    EXPECTED_PATH_BLOCKED_CHAIN,
    ModelOwnedChainDecisionV2,
    ModelOwnedChainEpisodeV2,
    NONE_DESTINATION_CLASS,
    NONE_POINTER_CLASS,
    PhysicalSkillReceiptV2,
    PublicObservationReceiptV2,
    REGISTERED_DESTINATION_CELLS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
    M2C_Q012_V2_SKILL_LABELS,
    POINTER_CLASS_LABELS,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import (
    PUBLIC_TRACK_SLOT_COUNT,
    canonical_track_slots,
)
from xh_agent.policy.qrm_lite.runtime_adapter_v2 import build_runtime_skill_request_v2
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    ParameterProvenanceV2,
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
    RuntimeSkillRequestV2,
)


QWEN_MODEL_ID = "Qwen/Qwen3.5-4B"
QWEN_MODEL_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
QWEN_ARCHITECTURE_REVISION = "M2C_Q012_V2"
FORMAL_WIRE_PROTOCOL = "M2C_FORMAL_SPLIT_RUNNER_V2"
FORMAL_INFERENCE_PATH = "/v1/m2c/qwen-coarse-v2/predict"
FORMAL_ISAAC_START_PATH = "/v1/m2c/isaac/start"
FORMAL_ISAAC_CAPTURE_PATH = "/v1/m2c/isaac/capture"
FORMAL_ISAAC_EXECUTE_PATH = "/v1/m2c/isaac/execute"
FORMAL_ISAAC_FINALIZE_PATH = "/v1/m2c/isaac/finalize"
QWEN_HEAD_TENSORS: tuple[str, ...] = (
    "skill_w",
    "skill_b",
    "pointer_w",
    "pointer_b",
    "destination_w",
    "destination_b",
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
TRACK_ID_PATTERN = r"^track-[A-Za-z0-9._:-]+$"
_T = TypeVar("_T", bound=BaseModel)
WireMessageType = Literal[
    "ISAAC_START_REQUEST",
    "ISAAC_START_RESPONSE",
    "ISAAC_CAPTURE_REQUEST",
    "ISAAC_CAPTURE_RESPONSE",
    "ISAAC_EXECUTE_REQUEST",
    "ISAAC_EXECUTE_RESPONSE",
    "ISAAC_FINALIZE_REQUEST",
    "ISAAC_FINALIZE_RESPONSE",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FrozenStrictModel(BaseModel):
    """Recursively immutable-by-shape contract used for physical plans.

    Plan models contain only scalars and tuples of frozen models, so Pydantic's
    frozen outer models cannot hide a mutable list/dict that an executor could
    alter after pre-execution validation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_json_bytes(payload: Any) -> bytes:
    """Serialize one Pydantic/JSON payload deterministically."""

    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    elif isinstance(payload, (list, tuple)):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in payload
        ]
    elif isinstance(payload, Mapping):
        payload = {
            key: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
            for key, value in payload.items()
        }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash a directory including relative names and file bytes."""

    if not root.is_dir():
        raise FileNotFoundError(root)
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"tree has no files: {root}")
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def named_array_sha256(name: str, value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
        raise ValueError(f"array {name} is nonnumeric or non-finite")
    header = canonical_json_bytes(
        {"dtype": array.dtype.str, "name": name, "shape": list(array.shape)}
    )
    return hashlib.sha256(header + b"\0" + array.tobytes(order="C")).hexdigest()


def qwen_head_tensor_sha256(heads: Any) -> dict[str, str]:
    tensors = heads.tensors()
    if set(tensors) != set(QWEN_HEAD_TENSORS):
        raise ValueError("formal model does not have the exact three-head tensor set")
    return {name: named_array_sha256(name, tensors[name]) for name in QWEN_HEAD_TENSORS}


def physical_receipt_sha256(receipt: PhysicalSkillReceiptV2) -> str:
    core = receipt.model_dump(mode="json")
    core.pop("receipt_sha256")
    return canonical_sha256(core)


def read_hmac_secret(path: Path) -> bytes:
    """Read one host-local HMAC key through a single non-following file descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("formal endpoint secret must be a non-symlink regular file") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("formal endpoint secret is not a regular file")
        if metadata.st_uid != os.geteuid():
            raise PermissionError("formal endpoint secret is not owned by the current user")
        if metadata.st_mode & 0o077:
            raise PermissionError("formal endpoint secret file must have mode 0600 or stricter")
        if metadata.st_nlink != 1:
            raise PermissionError("formal endpoint secret file must have exactly one hard link")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        secret = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(secret) < 32:
        raise ValueError("formal endpoint HMAC key must contain at least 32 bytes")
    return secret


def hmac_sha256(payload: Any, secret: bytes) -> str:
    if len(secret) < 32:
        raise ValueError("formal endpoint HMAC key must contain at least 32 bytes")
    return hmac.new(secret, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


class PublicAssetInlineV2(StrictModel):
    """One hash-bound public sensor asset transported to node2."""

    schema_version: Literal["PublicAssetInlineV2"] = "PublicAssetInlineV2"
    uri: str = Field(pattern=r"^dataset://[^\s]+$")
    sha256: str = Field(pattern=SHA256_PATTERN)
    media_type: Literal["image/png", "image/jpeg", "application/x-npy"]
    data_base64: str = Field(min_length=1)

    @model_validator(mode="after")
    def bytes_match_hash_and_uri_is_safe(self) -> "PublicAssetInlineV2":
        relative = self.uri.removeprefix("dataset://")
        if relative.startswith("/") or ".." in relative.split("/"):
            raise ValueError("public asset URI escapes its evidence root")
        try:
            payload = base64.b64decode(self.data_base64, validate=True)
        except ValueError as exc:
            raise ValueError("public asset is not canonical base64") from exc
        if not payload or hashlib.sha256(payload).hexdigest() != self.sha256:
            raise ValueError("public asset bytes differ from declared SHA-256")
        return self

    def decoded(self) -> bytes:
        return base64.b64decode(self.data_base64, validate=True)


class FormalPublicObservationV2(StrictModel):
    """Fresh public policy input; no evaluator-only role labels are included."""

    schema_version: Literal["FormalPublicObservationV2"] = "FormalPublicObservationV2"
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    previous_physical_completed_at_ns: int = Field(ge=0)
    source: Literal["PUBLIC_RGBD"] = "PUBLIC_RGBD"
    fresh: Literal[True] = True
    rgb: PublicAssetInlineV2
    depth: PublicAssetInlineV2
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    perception_tracks: list[PerceptionTrackV1] = Field(min_length=1)
    canonical_slots: list[str | None] = Field(
        min_length=PUBLIC_TRACK_SLOT_COUNT,
        max_length=PUBLIC_TRACK_SLOT_COUNT,
    )
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def public_and_fresh(self) -> "FormalPublicObservationV2":
        if self.captured_at_ns <= self.previous_physical_completed_at_ns:
            raise ValueError("capture is not newer than the previous physical event")
        if self.rgb.media_type not in {"image/png", "image/jpeg"}:
            raise ValueError("Qwen RGB input must be PNG or JPEG")
        if self.depth.media_type != "application/x-npy":
            raise ValueError("formal public depth transport must be an NPY array")
        for track in self.perception_tracks:
            if not re.fullmatch(TRACK_ID_PATTERN, track.track_id):
                raise ValueError("policy input contains a non-public track identifier")
            public_text = " ".join(
                value for value in (track.category, track.crop_uri) if value is not None
            ).lower()
            if (
                "/world/" in public_text
                or "gazebo_perfect" in public_text
                or re.search(r"(?:^|[^a-z0-9])cylinder_[0-9]+", public_text)
            ):
                raise ValueError("policy track fields contain simulator identity")
        slots = canonical_track_slots(self.perception_tracks)
        if list(slots.track_ids) != self.canonical_slots:
            raise ValueError("canonical K=8 slots differ from fresh public tracks")
        return self


class QwenBundleRuntimeBindingV2(StrictModel):
    """Exact trained bundle and offline base-model cache used by node2."""

    schema_version: Literal["QwenBundleRuntimeBindingV2"] = "QwenBundleRuntimeBindingV2"
    architecture_revision: Literal[QWEN_ARCHITECTURE_REVISION] = QWEN_ARCHITECTURE_REVISION
    model_id: Literal[QWEN_MODEL_ID] = QWEN_MODEL_ID
    model_revision: Literal[QWEN_MODEL_REVISION] = QWEN_MODEL_REVISION
    bundle_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    head_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    adapter_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    model_cache_dir: str = Field(min_length=1)
    model_cache_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    local_files_only: Literal[True] = True
    failure_context: Literal["on", "off"]
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def cache_binding_is_an_absolute_revision_snapshot(self) -> "QwenBundleRuntimeBindingV2":
        path = Path(self.model_cache_dir)
        expected_suffix = Path(
            "models--Qwen--Qwen3.5-4B",
            "snapshots",
            QWEN_MODEL_REVISION,
        )
        if not path.is_absolute() or tuple(path.parts[-3:]) != expected_suffix.parts:
            raise ValueError("formal Qwen cache binding is not the fixed revision snapshot")
        return self


class FormalInferenceRequestV2(StrictModel):
    schema_version: Literal["FormalInferenceRequestV2"] = "FormalInferenceRequestV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
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
    bundle: QwenBundleRuntimeBindingV2
    observation: FormalPublicObservationV2
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def public_history_is_exact_prefix(self) -> "FormalInferenceRequestV2":
        validate_executed_intent_history_v2(
            self.executed_intent_history,
            expected_length=self.decision_index,
        )
        if self.prior_decisions_sha256 != canonical_sha256(self.executed_intent_history):
            raise ValueError("prior-decisions hash differs from public executed-intent history")
        if any(
            item.execution_attribution != "MODEL_SELECTED_REGISTERED_SKILL"
            for item in self.executed_intent_history
        ):
            raise ValueError("formal runtime history contains scripted supervision")
        return self


class SignedInferenceRequestV2(StrictModel):
    schema_version: Literal["SignedInferenceRequestV2"] = "SignedInferenceRequestV2"
    payload: FormalInferenceRequestV2
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    hmac_sha256: str = Field(pattern=SHA256_PATTERN)


class HeadPredictionV2(StrictModel):
    labels: list[str] = Field(min_length=1)
    # Masked pointer classes are serialized as null; NaN/Inf never cross wire.
    logits: list[float | None] = Field(min_length=1)
    selected_index: int = Field(ge=0)
    selected_label: str = Field(min_length=1)
    selection: Literal["ARGMAX_TEMPERATURE_0_LOWER_INDEX_TIE"] = (
        "ARGMAX_TEMPERATURE_0_LOWER_INDEX_TIE"
    )

    @model_validator(mode="after")
    def selection_is_exact(self) -> "HeadPredictionV2":
        if len(self.labels) != len(self.logits):
            raise ValueError("head labels/logits length mismatch")
        if self.selected_index >= len(self.labels):
            raise ValueError("head selected index is out of bounds")
        if self.labels[self.selected_index] != self.selected_label:
            raise ValueError("head selected label differs from selected index")
        finite = [
            (index, float(value)) for index, value in enumerate(self.logits) if value is not None
        ]
        if not finite or any(not math.isfinite(value) for _, value in finite):
            raise ValueError("head has no finite logits or contains NaN/Inf")
        expected = max(finite, key=lambda item: (item[1], -item[0]))[0]
        if expected != self.selected_index:
            raise ValueError("head selection is not deterministic lower-index argmax")
        return self


class FormalInferenceResponseV2(StrictModel):
    schema_version: Literal["FormalInferenceResponseV2"] = "FormalInferenceResponseV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    request_payload_sha256: str = Field(pattern=SHA256_PATTERN)
    executed_intent_history_sha256: str = Field(pattern=SHA256_PATTERN)
    completed_at_ns: int = Field(gt=0)
    bundle: QwenBundleRuntimeBindingV2
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
    def exact_three_head_decode(self) -> "FormalInferenceResponseV2":
        if set(self.head_tensor_sha256) != set(QWEN_HEAD_TENSORS):
            raise ValueError("formal response does not bind the exact three-head tensors")
        if any(
            not re.fullmatch(SHA256_PATTERN, value) for value in self.head_tensor_sha256.values()
        ):
            raise ValueError("formal response contains a malformed head tensor hash")
        if self.executed_intent_history_sha256 == "0" * 64:
            raise ValueError("formal response has an invalid history binding")
        exact = (
            (self.skill, list(M2C_Q012_V2_SKILL_LABELS)),
            (self.pointer, list(POINTER_CLASS_LABELS)),
            (self.destination, list(DESTINATION_CLASS_LABELS)),
        )
        for head, labels in exact:
            if head.labels != labels:
                raise ValueError("formal response label order is not M2C_Q012_V2")
        expected_target = (
            None
            if self.pointer.selected_index == NONE_POINTER_CLASS
            else self.pointer.selected_label
        )
        # The pointer label is SLOT_i; the literal public track is validated by
        # the requester because only it owns the corresponding fresh capture.
        if expected_target is None and self.intent.target_track_id is not None:
            raise ValueError("pointer NONE differs from decoded target")
        if expected_target is not None and self.intent.target_track_id is None:
            raise ValueError("selected pointer lost its public literal")
        expected_destination = (
            None
            if self.destination.selected_index == NONE_DESTINATION_CLASS
            else self.destination.selected_label
        )
        if self.intent.skill_type != self.skill.selected_label:
            raise ValueError("intent skill differs from skill head")
        if self.intent.destination_cell != expected_destination:
            raise ValueError("intent destination differs from destination head")
        if self.intent.failure_type_aux != FailureType.PATH_BLOCKED:
            raise ValueError("formal response lost PATH_BLOCKED context")
        return self


class SignedInferenceResponseV2(StrictModel):
    schema_version: Literal["SignedInferenceResponseV2"] = "SignedInferenceResponseV2"
    payload: FormalInferenceResponseV2
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    hmac_sha256: str = Field(pattern=SHA256_PATTERN)


class PublicRoleBindingV2(StrictModel):
    """Evaluator journal roles derived only by committed public selectors."""

    schema_version: Literal["PublicRoleBindingV2"] = "PublicRoleBindingV2"
    blocker_track_id: str | None = Field(default=None, pattern=TRACK_ID_PATTERN)
    task_target_track_id: str | None = Field(default=None, pattern=TRACK_ID_PATTERN)
    source: Literal["FROZEN_PUBLIC_SELECTOR"] = "FROZEN_PUBLIC_SELECTOR"
    selector_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    simulator_identity_used: Literal[False] = False


class IsaacEndpointBindingV2(StrictModel):
    """Deployment declaration required before a formal host may connect."""

    schema_version: Literal["IsaacEndpointBindingV2"] = "IsaacEndpointBindingV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    endpoint_base_url: str = Field(pattern=r"^https?://[^\s]+$")
    host: str = Field(min_length=1)
    implementation_path: str = Field(min_length=1)
    implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_backend_path: str = Field(min_length=1)
    physical_backend_sha256: str = Field(pattern=SHA256_PATTERN)
    public_role_selector_path: str = Field(min_length=1)
    public_role_selector_sha256: str = Field(pattern=SHA256_PATTERN)
    frozen_v4_probe_sha256: Literal[
        "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
    ]
    real_physics: Literal[True] = True
    mocked_physics: Literal[False] = False
    scripted_decision_source: Literal[False] = False
    ready_for_formal_execution: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class IsaacStartRequestV2(StrictModel):
    schema_version: Literal["IsaacStartRequestV2"] = "IsaacStartRequestV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_id: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_registry_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    bundle: QwenBundleRuntimeBindingV2
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class IsaacStartResponseV2(StrictModel):
    schema_version: Literal["IsaacStartResponseV2"] = "IsaacStartResponseV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    start_request_sha256: str = Field(pattern=SHA256_PATTERN)
    failure_observed_at_ns: int = Field(gt=0)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_backend_sha256: str = Field(pattern=SHA256_PATTERN)
    real_physics: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class IsaacCaptureRequestV2(StrictModel):
    schema_version: Literal["IsaacCaptureRequestV2"] = "IsaacCaptureRequestV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    previous_physical_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )


class IsaacCaptureResponseV2(StrictModel):
    schema_version: Literal["IsaacCaptureResponseV2"] = "IsaacCaptureResponseV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation: FormalPublicObservationV2
    public_roles: PublicRoleBindingV2
    real_physics: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def roles_are_current_public_tracks(self) -> "IsaacCaptureResponseV2":
        track_ids = {track.track_id for track in self.observation.perception_tracks}
        for track_id in (
            self.public_roles.blocker_track_id,
            self.public_roles.task_target_track_id,
        ):
            if track_id is not None and track_id not in track_ids:
                raise ValueError("public role is absent from the fresh capture")
        return self


class IsaacExecuteRequestV2(StrictModel):
    schema_version: Literal["IsaacExecuteRequestV2"] = "IsaacExecuteRequestV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    inference_response_sha256: str = Field(pattern=SHA256_PATTERN)
    executed_intent_history_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_request: RuntimeSkillRequestV2
    task_spec_fallback_allowed: Literal[False] = False
    requested_physical_skill_count: Literal[1] = 1
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def recovery_target_is_never_task_fallback(self) -> "IsaacExecuteRequestV2":
        if self.runtime_request.current_phase != "RECOVERY":
            raise ValueError("formal model-owned execution must remain in RECOVERY")
        if self.runtime_request.target_track_provenance == (
            ParameterProvenanceV2.TASK_SPEC_FALLBACK
        ):
            raise ValueError("TaskSpec fallback is forbidden in formal recovery")
        if any(
            value == ParameterProvenanceV2.TASK_SPEC_FALLBACK
            for value in self.runtime_request.parameter_provenance.values()
        ):
            raise ValueError("TaskSpec parameter fallback is forbidden in formal recovery")
        return self


ExactPhaseCommandV2 = Literal[
    "CARTESIAN_POSE",
    "GRIPPER_POSITION",
    "ATTACH_CONTACT_ENTITY",
    "REMOVE_ATTACHMENT",
    "PUBLIC_RGBD_CAPTURE",
    "PUBLIC_TRACK_REASSOCIATION",
]


class ExactExecutionPhaseGatesV2(FrozenStrictModel):
    """All required non-actuating checks for one exact physical phase."""

    schema_version: Literal["ExactExecutionPhaseGatesV2"] = "ExactExecutionPhaseGatesV2"
    ik: Literal["PASS"] = "PASS"
    joint_limits: Literal["PASS"] = "PASS"
    swept_collision: Literal["PASS"] = "PASS"
    controller: Literal["PASS"] = "PASS"
    safety: Literal["PASS"] = "PASS"
    ik_detail: str = Field(min_length=1)
    joint_limits_detail: str = Field(min_length=1)
    swept_collision_detail: str = Field(min_length=1)
    controller_detail: str = Field(min_length=1)
    safety_detail: str = Field(min_length=1)


class ExactExecutionPhaseV2(FrozenStrictModel):
    """One fully specified phase; the executor may not fill in parameters."""

    schema_version: Literal["ExactExecutionPhaseV2"] = "ExactExecutionPhaseV2"
    phase_index: int = Field(ge=0)
    phase_name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    command: ExactPhaseCommandV2
    goal_position_world_m: tuple[float, float, float] | None = None
    orientation_world_wxyz: tuple[float, float, float, float] | None = None
    gripper_position_m: float | None = Field(default=None, ge=0.0, le=0.08)
    steps: int = Field(ge=0)
    collision_phase: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    allowed_robot_contact_paths: tuple[str, ...] = ()
    allowed_external_contact_paths: tuple[str, ...] = ()
    public_target_track_id: str | None = Field(default=None, pattern=TRACK_ID_PATTERN)
    public_capture_label: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    contact_entity_selection: Literal[
        "NONE",
        "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST",
    ] = "NONE"
    gates: ExactExecutionPhaseGatesV2

    @model_validator(mode="after")
    def command_is_fully_bound(self) -> "ExactExecutionPhaseV2":
        numeric = [
            *(self.goal_position_world_m or ()),
            *(self.orientation_world_wxyz or ()),
            *(() if self.gripper_position_m is None else (self.gripper_position_m,)),
        ]
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("exact execution phase contains NaN/Inf")
        if self.command == "CARTESIAN_POSE":
            if (
                self.goal_position_world_m is None
                or self.orientation_world_wxyz is None
                or self.gripper_position_m is not None
                or self.steps <= 0
            ):
                raise ValueError("Cartesian phase lacks an exact pose/orientation/step count")
            norm = math.sqrt(sum(value * value for value in self.orientation_world_wxyz))
            if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-4):
                raise ValueError("Cartesian phase orientation is not a unit quaternion")
        elif self.command == "GRIPPER_POSITION":
            if (
                self.gripper_position_m is None
                or self.goal_position_world_m is not None
                or self.orientation_world_wxyz is not None
                or self.steps <= 0
            ):
                raise ValueError("gripper phase lacks one exact target/step count")
        elif (
            self.goal_position_world_m is not None
            or self.orientation_world_wxyz is not None
            or self.gripper_position_m is not None
            or self.steps != 0
        ):
            raise ValueError("non-motion phase contains unbound motion parameters")
        if self.command == "ATTACH_CONTACT_ENTITY":
            if (
                self.contact_entity_selection
                != "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"
                or not self.allowed_external_contact_paths
            ):
                raise ValueError("attachment phase lacks its exact contact allowlist/selector")
        elif self.contact_entity_selection != "NONE":
            raise ValueError("non-attachment phase contains a contact-entity selector")
        if self.command == "PUBLIC_RGBD_CAPTURE":
            if self.public_capture_label is None or self.public_target_track_id is not None:
                raise ValueError("public capture phase lacks its exact public label")
        elif self.command == "PUBLIC_TRACK_REASSOCIATION":
            if self.public_target_track_id is None or self.public_capture_label is not None:
                raise ValueError("public reassociation phase lacks its exact public pointer")
        elif self.public_target_track_id is not None or self.public_capture_label is not None:
            raise ValueError("physical phase contains public logical-action parameters")
        return self


class ExactExecutionPlanV2(FrozenStrictModel):
    """Immutable plan constructed and fully gated before any model actuation."""

    schema_version: Literal["ExactExecutionPlanV2"] = "ExactExecutionPlanV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_skill: str = Field(min_length=1)
    runtime_action: str = Field(min_length=1)
    execution_parameters_sha256: str = Field(pattern=SHA256_PATTERN)
    target_track_id: str | None = Field(default=None, pattern=TRACK_ID_PATTERN)
    phases: tuple[ExactExecutionPhaseV2, ...] = Field(min_length=1)
    constructed_before_physical_execution: Literal[True] = True
    executor_parameter_adaptation_allowed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def phases_are_an_exact_sequence(self) -> "ExactExecutionPlanV2":
        if tuple(phase.phase_index for phase in self.phases) != tuple(range(len(self.phases))):
            raise ValueError("exact execution plan phase indices are not contiguous")
        names = tuple(phase.phase_name for phase in self.phases)
        if len(names) != len(set(names)):
            raise ValueError("exact execution plan phase names are not unique")
        if any(
            phase.public_target_track_id is not None
            and phase.public_target_track_id != self.target_track_id
            for phase in self.phases
        ):
            raise ValueError("exact execution phase pointer differs from plan pointer")
        return self


class IsaacExecuteResponseV2(StrictModel):
    schema_version: Literal["IsaacExecuteResponseV2"] = "IsaacExecuteResponseV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    inference_response_sha256: str = Field(pattern=SHA256_PATTERN)
    mapping: RuntimeSkillMappingResultV2
    exact_execution_plan: ExactExecutionPlanV2 | None = None
    exact_execution_plan_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    executed_exact_execution_plan_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    physical_skill_receipts: list[PhysicalSkillReceiptV2] = Field(
        min_length=1,
        max_length=1,
    )
    mapping_and_all_preexecution_gates_ran_in_isaac: Literal[True] = True
    requested_skill_was_physically_executed: bool
    real_physics: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def receipt_matches_mapping(self) -> "IsaacExecuteResponseV2":
        receipt = self.physical_skill_receipts[0]
        if receipt.receipt_sha256 != physical_receipt_sha256(receipt):
            raise ValueError("physical receipt SHA-256 is not its canonical semantic digest")
        if self.mapping.status == "VALID":
            if self.mapping.fallback_required:
                raise ValueError("VALID mapping unexpectedly requires fallback")
            if self.mapping.execution_attribution != "MODEL_SELECTED_REGISTERED_SKILL":
                raise ValueError("physical execution attribution is not model-only")
            if receipt.execution_source != "MODEL_SELECTED_REGISTERED_SKILL":
                raise ValueError("VALID mapping did not execute the model-selected skill")
            if receipt.executed_skill != self.mapping.canonical_skill:
                raise ValueError("physical receipt skill differs from mapped model skill")
            physical_commands = {
                "CARTESIAN_POSE",
                "GRIPPER_POSITION",
                "ATTACH_CONTACT_ENTITY",
                "REMOVE_ATTACHMENT",
            }
            plan = self.exact_execution_plan
            if plan is None:
                raise ValueError("VALID mapping has no immutable exact execution plan")
            plan_sha256 = canonical_sha256(plan)
            if (
                self.exact_execution_plan_sha256 != plan_sha256
                or self.executed_exact_execution_plan_sha256 != plan_sha256
            ):
                raise ValueError("exact execution plan hash/execution binding differs")
            if (
                plan.run_id != self.run_id
                or plan.session_id != self.session_id
                or plan.decision_index != self.decision_index
                or plan.observation_id != self.observation_id
                or plan.canonical_skill != self.mapping.canonical_skill
                or plan.runtime_action != self.mapping.runtime_action
                or plan.execution_parameters_sha256
                != canonical_sha256(self.mapping.execution_parameters)
                or plan.target_track_id != self.mapping.target_track_id
            ):
                raise ValueError("exact execution plan differs from mapped decision")
            plan_has_physical_command = any(
                phase.command in physical_commands for phase in plan.phases
            )
            if not plan_has_physical_command:
                raise ValueError("formal VALID mapping has no physical exact-plan command")
            if not receipt.physically_executed:
                raise ValueError(
                    "physical receipt attribution differs from exact plan command types"
                )
            if not self.requested_skill_was_physically_executed:
                raise ValueError("response physical-execution flag differs from exact plan")
            gate_status = {
                entry.get("gate"): entry.get("status") for entry in self.mapping.gate_trace
            }
            for gate in (
                "schema",
                "track",
                "protocol",
                "ik",
                "collision",
                "controller",
                "safety",
                "exact_plan",
            ):
                if gate_status.get(gate) != "PASS":
                    raise ValueError(f"formal mapping gate {gate} did not pass in Isaac")
            plan_trace = next(
                entry for entry in self.mapping.gate_trace if entry.get("gate") == "exact_plan"
            )
            if plan_trace.get("plan_sha256") != plan_sha256:
                raise ValueError("mapping exact-plan gate does not bind the canonical plan")
        else:
            if not self.mapping.fallback_required:
                raise ValueError("INVALID mapping did not require fallback")
            if receipt.execution_source != "NO_PHYSICAL_EXECUTION":
                raise ValueError("INVALID mapping falsely attributes an unexecuted fallback")
            if receipt.physically_executed:
                raise ValueError("INVALID mapping is terminal NO_PHYSICAL_EXECUTION under ADR-0024")
            if not receipt.fallback_reason or not receipt.fallback_reason.startswith(
                "PHYSICAL_FALLBACK_NOT_EXECUTED:"
            ):
                raise ValueError("INVALID mapping lacks terminal no-execution evidence")
            if receipt.executed_skill != "NO_PHYSICAL_EXECUTION":
                raise ValueError("INVALID mapping receipt falsely names a physical skill")
            if self.requested_skill_was_physically_executed:
                raise ValueError("INVALID mapping claims the requested skill was physical")
            if any(
                value is not None
                for value in (
                    self.exact_execution_plan,
                    self.exact_execution_plan_sha256,
                    self.executed_exact_execution_plan_sha256,
                )
            ):
                raise ValueError("INVALID mapping claims an exact model execution plan")
        return self


def validate_isaac_execute_request_mapping_v2(
    request: IsaacExecuteRequestV2,
    registry: RuntimeSkillRegistryV2,
    *,
    ik_check: Any,
    collision_check: Any,
    controller_check: Any,
    safety_check: Any,
    exact_plan_getter: Any,
) -> RuntimeSkillMappingResultV2:
    """Required Isaac-side remapping with all delegated gates injected.

    A physical endpoint must call this after authenticating the request and
    before executing anything.  The host's request is untrusted; merely
    echoing a host-provided mapping can never satisfy ``IsaacExecuteResponseV2``.
    """

    from xh_agent.policy.qrm_lite.skill_registry_v2 import validate_runtime_mapping_v2

    for name, check in (
        ("ik", ik_check),
        ("collision", collision_check),
        ("controller", controller_check),
        ("safety", safety_check),
        ("exact_plan", exact_plan_getter),
    ):
        if check is None or not callable(check):
            raise ValueError(f"real Isaac endpoint did not inject the {name} gate")
    mapping = validate_runtime_mapping_v2(
        request.runtime_request,
        registry,
        ik_check=ik_check,
        collision_check=collision_check,
        safety_check=safety_check,
    )
    if mapping.status == "VALID":
        try:
            controller_accepted, controller_detail = controller_check(
                str(mapping.runtime_action),
                dict(mapping.execution_parameters),
            )
        except Exception as exc:
            raise ValueError(
                "real Isaac endpoint controller pre-execution gate raised "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(controller_accepted, bool):
            raise ValueError(
                "real Isaac endpoint controller pre-execution gate did not "
                "return a boolean decision"
            )
        mapping.gate_trace.append(
            {
                "gate": "controller",
                "status": "PASS" if controller_accepted else "INVALID",
                "detail": controller_detail,
            }
        )
        if not controller_accepted:
            from xh_agent.policy.qrm_lite.skill_registry_v2 import MappingRejectionV2

            mapping.status = "INVALID"
            mapping.rejection_reason = MappingRejectionV2.SAFETY_REJECTION
            mapping.fallback_required = True
            mapping.execution_attribution = "NO_PHYSICAL_EXECUTION"
    if mapping.status == "VALID":
        try:
            exact_plan = exact_plan_getter(
                str(mapping.runtime_action),
                dict(mapping.execution_parameters),
            )
        except Exception as exc:
            from xh_agent.policy.qrm_lite.skill_registry_v2 import MappingRejectionV2

            mapping.status = "INVALID"
            mapping.rejection_reason = MappingRejectionV2.SAFETY_REJECTION
            mapping.fallback_required = True
            mapping.execution_attribution = "NO_PHYSICAL_EXECUTION"
            mapping.gate_trace.append(
                {
                    "gate": "exact_plan",
                    "status": "INVALID",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            if not isinstance(exact_plan, ExactExecutionPlanV2):
                raise ValueError("real Isaac endpoint did not return ExactExecutionPlanV2")
            if (
                exact_plan.run_id != request.run_id
                or exact_plan.session_id != request.session_id
                or exact_plan.decision_index != request.decision_index
                or exact_plan.observation_id != request.observation_id
                or exact_plan.capture_receipt_sha256 != request.capture_receipt_sha256
                or exact_plan.canonical_skill != mapping.canonical_skill
                or exact_plan.runtime_action != mapping.runtime_action
                or exact_plan.execution_parameters_sha256
                != canonical_sha256(mapping.execution_parameters)
                or exact_plan.target_track_id != mapping.target_track_id
            ):
                raise ValueError("real Isaac exact plan differs from remapped request")
            mapping.gate_trace.append(
                {
                    "gate": "exact_plan",
                    "status": "PASS",
                    "plan_sha256": canonical_sha256(exact_plan),
                    "phase_count": len(exact_plan.phases),
                }
            )
    trace = {entry.get("gate"): entry.get("status") for entry in mapping.gate_trace}
    if mapping.status == "VALID":
        for gate in (
            "schema",
            "protocol",
            "ik",
            "collision",
            "controller",
            "safety",
            "exact_plan",
        ):
            if trace.get(gate) != "PASS":
                raise ValueError(f"real Isaac endpoint did not pass mapping gate {gate}")
    else:
        if "INVALID" not in trace.values():
            raise ValueError("INVALID Isaac mapping has no rejecting gate trace")
        # The rejecting gate was run before fallback.  Remaining physical
        # mapping gates are explicitly not run; they may not be represented as
        # PASS because the model intent never reached them.
        for gate in ("ik", "collision", "controller", "safety", "exact_plan"):
            if gate not in trace:
                mapping.gate_trace.append(
                    {
                        "gate": gate,
                        "status": "NOT_RUN",
                        "detail": "earlier mapping gate rejected model intent",
                    }
                )
    return mapping


class IsaacFinalizeRequestV2(StrictModel):
    schema_version: Literal["IsaacFinalizeRequestV2"] = "IsaacFinalizeRequestV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    last_physical_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    decisions_observed: Literal[8] = 8


class IsaacFinalizeResponseV2(StrictModel):
    schema_version: Literal["IsaacFinalizeResponseV2"] = "IsaacFinalizeResponseV2"
    protocol: Literal[FORMAL_WIRE_PROTOCOL] = FORMAL_WIRE_PROTOCOL
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    evaluated_at_ns: int = Field(gt=0)
    final_task_success: bool
    outcome_used_as_policy_input: Literal[False] = False
    real_physics: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class SignedWireMessageV2(StrictModel):
    """Typed payloads are parsed after this generic authenticated envelope."""

    schema_version: Literal["SignedWireMessageV2"] = "SignedWireMessageV2"
    message_type: WireMessageType
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    hmac_sha256: str = Field(pattern=SHA256_PATTERN)


def sign_inference_request(
    payload: FormalInferenceRequestV2,
    secret: bytes,
) -> SignedInferenceRequestV2:
    return SignedInferenceRequestV2(
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        hmac_sha256=hmac_sha256(payload, secret),
    )


def sign_inference_response(
    payload: FormalInferenceResponseV2,
    secret: bytes,
) -> SignedInferenceResponseV2:
    return SignedInferenceResponseV2(
        payload=payload,
        payload_sha256=canonical_sha256(payload),
        hmac_sha256=hmac_sha256(payload, secret),
    )


def verify_inference_request(
    raw: Mapping[str, Any],
    secret: bytes,
) -> SignedInferenceRequestV2:
    message = SignedInferenceRequestV2.model_validate(raw)
    _verify_hash_and_hmac(message.payload, message.payload_sha256, message.hmac_sha256, secret)
    return message


def verify_inference_response(
    raw: Mapping[str, Any],
    secret: bytes,
) -> SignedInferenceResponseV2:
    message = SignedInferenceResponseV2.model_validate(raw)
    _verify_hash_and_hmac(message.payload, message.payload_sha256, message.hmac_sha256, secret)
    return message


def sign_wire_message(
    message_type: WireMessageType,
    payload: BaseModel,
    secret: bytes,
) -> SignedWireMessageV2:
    dumped = payload.model_dump(mode="json")
    payload_sha256 = canonical_sha256(dumped)
    authenticated = {
        "message_type": message_type,
        "payload": dumped,
        "payload_sha256": payload_sha256,
    }
    return SignedWireMessageV2(
        message_type=message_type,
        payload=dumped,
        payload_sha256=payload_sha256,
        hmac_sha256=hmac_sha256(authenticated, secret),
    )


def verify_wire_message(
    raw: Mapping[str, Any],
    *,
    expected_type: str,
    payload_model: type[_T],
    secret: bytes,
) -> tuple[SignedWireMessageV2, _T]:
    message = SignedWireMessageV2.model_validate(raw)
    if message.message_type != expected_type:
        raise ValueError(f"wire message type mismatch: {message.message_type} != {expected_type}")
    actual_sha256 = canonical_sha256(message.payload)
    if not hmac.compare_digest(actual_sha256, message.payload_sha256):
        raise ValueError("wire payload SHA-256 mismatch")
    authenticated = {
        "message_type": message.message_type,
        "payload": message.payload,
        "payload_sha256": message.payload_sha256,
    }
    actual_hmac = hmac_sha256(authenticated, secret)
    if not hmac.compare_digest(actual_hmac, message.hmac_sha256):
        raise ValueError("wire message type/payload HMAC mismatch")
    return message, payload_model.model_validate(message.payload)


def _verify_hash_and_hmac(
    payload: Any,
    expected_sha256: str,
    expected_hmac: str,
    secret: bytes,
) -> None:
    actual_sha256 = canonical_sha256(payload)
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ValueError("wire payload SHA-256 mismatch")
    actual_hmac = hmac_sha256(payload, secret)
    if not hmac.compare_digest(actual_hmac, expected_hmac):
        raise ValueError("wire payload HMAC mismatch")


def runtime_qwen_prompt(
    observation: FormalPublicObservationV2,
    *,
    use_failure_context: bool,
    executed_intent_history: Sequence[PublicExecutedIntentHistoryItemV2] = (),
    expected_history_length: int | None = None,
) -> str:
    """Build the exact public K=8 Qwen prompt used by the training path."""

    slots = canonical_track_slots(observation.perception_tracks)
    public_tracks = [
        None
        if track is None
        else {
            "track_id": track.track_id,
            "category": track.category,
            "confidence": round(track.confidence, 4),
            "pose_xyzquat": track.pose_xyzquat,
        }
        for track in slots.tracks
    ]
    payload = {
        "task": "recover from a public PATH_BLOCKED manipulation failure",
        "canonical_public_track_slots_k8": public_tracks,
        "valid_mask": slots.valid_mask.tolist(),
        "failure_context": {"failure_type": "PATH_BLOCKED" if use_failure_context else "MASKED"},
        "public_executed_intent_history": prompt_executed_intent_history_v2(
            executed_intent_history,
            expected_length=(
                len(executed_intent_history)
                if expected_history_length is None
                else expected_history_length
            ),
        ),
        "allowed_skills": list(M2C_Q012_V2_SKILL_LABELS),
        "allowed_pointer_classes": list(POINTER_CLASS_LABELS),
        "allowed_destinations": list(DESTINATION_CLASS_LABELS),
    }
    return (
        "Select one CoarseIntentV2 skill, one literal K=8 public-track "
        "pointer (or NONE), and one registered destination cell (or NONE). "
        "Continuous coordinates and simulator truth are unavailable. Context:\n"
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def _wire_logits(
    values: Sequence[float], *, mask: Sequence[bool] | None = None
) -> list[float | None]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if mask is None:
        mask_array = np.ones(array.shape, dtype=bool)
    else:
        mask_array = np.asarray(mask, dtype=bool).reshape(-1)
        if mask_array.shape != array.shape:
            raise ValueError("head mask/logit shape mismatch")
    output: list[float | None] = []
    for valid, value in zip(mask_array.tolist(), array.tolist()):
        if not valid:
            output.append(None)
        elif not math.isfinite(value):
            raise ValueError("unmasked model head logit is NaN/Inf")
        else:
            output.append(float(value))
    return output


def build_inference_response_from_logits(
    request: FormalInferenceRequestV2,
    *,
    skill_logits: Sequence[float],
    pointer_logits: Sequence[float],
    destination_logits: Sequence[float],
    prompt_sha256: str,
    pooled_feature_sha256: str,
    head_tensor_sha256: dict[str, str],
    completed_at_ns: int,
) -> FormalInferenceResponseV2:
    """Deterministically decode three real Qwen-head outputs."""

    slots = canonical_track_slots(request.observation.perception_tracks)
    pointer_mask = [*slots.valid_mask.tolist(), True]
    skill_wire = _wire_logits(skill_logits)
    pointer_wire = _wire_logits(pointer_logits, mask=pointer_mask)
    destination_wire = _wire_logits(destination_logits)

    def selected(values: list[float | None]) -> int:
        return max(
            ((index, value) for index, value in enumerate(values) if value is not None),
            key=lambda item: (float(item[1]), -item[0]),
        )[0]

    skill_index = selected(skill_wire)
    pointer_index = selected(pointer_wire)
    destination_index = selected(destination_wire)
    target_track_id = (
        None if pointer_index == NONE_POINTER_CLASS else slots.track_ids[pointer_index]
    )
    destination_cell = (
        None
        if destination_index == NONE_DESTINATION_CLASS
        else REGISTERED_DESTINATION_CELLS[destination_index]
    )
    skill = M2C_Q012_V2_SKILL_LABELS[skill_index]
    intent = CoarseIntentV2(
        skill_type=skill,
        target_track_id=target_track_id,
        destination_cell=destination_cell,
        grasp_family="top_down" if skill in {"GRASP", "REGRASP"} else "unknown",
        reobserve_flag=skill == "REOBSERVE",
        failure_type_aux=FailureType.PATH_BLOCKED,
    )

    def confidence(values: list[float | None]) -> float:
        finite = np.asarray([value for value in values if value is not None], dtype=np.float64)
        exponent = np.exp(finite - np.max(finite))
        return float(np.max(exponent / exponent.sum()))

    return FormalInferenceResponseV2(
        run_id=request.run_id,
        request_id=request.request_id,
        decision_index=request.decision_index,
        request_payload_sha256=canonical_sha256(request),
        executed_intent_history_sha256=request.prior_decisions_sha256,
        completed_at_ns=completed_at_ns,
        bundle=request.bundle,
        prompt_sha256=prompt_sha256,
        pooled_feature_sha256=pooled_feature_sha256,
        head_tensor_sha256=head_tensor_sha256,
        skill=HeadPredictionV2(
            labels=list(M2C_Q012_V2_SKILL_LABELS),
            logits=skill_wire,
            selected_index=skill_index,
            selected_label=M2C_Q012_V2_SKILL_LABELS[skill_index],
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
            confidence(skill_wire),
            confidence(pointer_wire),
            confidence(destination_wire),
        ),
    )


def runtime_request_from_inference(
    request: FormalInferenceRequestV2,
    response: FormalInferenceResponseV2,
    registry: RuntimeSkillRegistryV2,
) -> RuntimeSkillRequestV2:
    """Bind model output to the same fresh slots without a TaskSpec fallback."""

    if response.request_payload_sha256 != canonical_sha256(request):
        raise ValueError("inference response is not bound to this request")
    if response.completed_at_ns <= request.sent_at_ns:
        raise ValueError("inference response completion precedes its request")
    if response.bundle != request.bundle:
        raise ValueError("inference response bundle differs from request")
    if response.executed_intent_history_sha256 != request.prior_decisions_sha256:
        raise ValueError("inference response history binding differs from request")
    slots = canonical_track_slots(request.observation.perception_tracks)
    selected_track = (
        None
        if response.pointer.selected_index == NONE_POINTER_CLASS
        else slots.track_ids[response.pointer.selected_index]
    )
    if response.intent.target_track_id != selected_track:
        raise ValueError("decoded public pointer differs from the fresh slot literal")
    observation = QRMObservationV1(
        episode_id=request.run_id,
        step_id=request.decision_index,
        timestamp_ns=request.observation.captured_at_ns,
        instruction=request.instruction,
        # Deliberately absent: RECOVERY may never fill the model pointer from TaskSpec.
        task_target_track_id=None,
        rgb_uri=request.observation.rgb.uri,
        depth_uri=request.observation.depth.uri,
        current_skill_stage="RECOVERY",
        perception_tracks=request.observation.perception_tracks,
        failure_context=FailureContextV1(failure_type=FailureType.PATH_BLOCKED),
    )
    decision = SimpleNamespace(
        coarse=response.intent,
        recovery_skill=None,
        confidence=response.confidence,
    )
    runtime_request = build_runtime_skill_request_v2(observation, decision, registry)
    if runtime_request.target_track_provenance == ParameterProvenanceV2.TASK_SPEC_FALLBACK:
        raise ValueError("runtime adapter attempted a TaskSpec recovery fallback")
    return runtime_request


def append_public_executed_intent_history(
    history: Sequence[PublicExecutedIntentHistoryItemV2],
    inference: SignedInferenceResponseV2,
    execution: IsaacExecuteResponseV2,
) -> list[PublicExecutedIntentHistoryItemV2]:
    """Append only an externally executed, VALID model-owned decision."""

    response = inference.payload
    expected_index = len(history)
    if response.decision_index != expected_index or execution.decision_index != expected_index:
        raise ValueError("cannot append a gapped/reordered executed-intent history")
    if execution.inference_response_sha256 != inference.payload_sha256:
        raise ValueError("physical execution is not bound to the inference response")
    if execution.mapping.status != "VALID" or execution.mapping.fallback_required:
        raise ValueError("fallback/INVALID execution cannot enter model-owned history")
    if execution.mapping.execution_attribution != "MODEL_SELECTED_REGISTERED_SKILL":
        raise ValueError("execution attribution is not model-only")
    receipt = execution.physical_skill_receipts[0]
    if receipt.execution_source != "MODEL_SELECTED_REGISTERED_SKILL":
        raise ValueError("fallback receipt cannot enter model-owned history")
    if not receipt.physically_executed:
        raise ValueError("non-executed physical receipt cannot enter model-owned history")
    nonpassing_gates = [
        gate_name
        for gate_name in (
            "schema_gate",
            "stale_track_gate",
            "frame_unit_gate",
            "ik_gate",
            "collision_gate",
            "controller_gate",
            "safety_gate",
        )
        if getattr(receipt, gate_name) != "PASS"
    ]
    if nonpassing_gates:
        raise ValueError(
            "non-passing physical receipt cannot enter model-owned history: "
            + ",".join(nonpassing_gates)
        )
    if receipt.collision_or_safety_violation:
        raise ValueError("unsafe physical receipt cannot enter model-owned history")
    if receipt.completed_at_ns <= receipt.started_at_ns:
        raise ValueError("invalid physical receipt timing cannot enter model-owned history")
    if receipt.fallback_reason is not None:
        raise ValueError("fallback-marked receipt cannot enter model-owned history")
    if receipt.teacher_used or receipt.privileged_truth_policy_input:
        raise ValueError("Teacher/truth-tainted receipt cannot enter model-owned history")
    appended = [
        *history,
        PublicExecutedIntentHistoryItemV2(
            decision_index=expected_index,
            selected_skill=response.intent.skill_type,
            target_track_id=response.intent.target_track_id,
            destination_cell=response.intent.destination_cell,
            physical_receipt_sha256=receipt.receipt_sha256,
            execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        ),
    ]
    return appended


def journal_decision_from_wire(
    inference: SignedInferenceResponseV2,
    capture: IsaacCaptureResponseV2,
    execution: IsaacExecuteResponseV2,
) -> ModelOwnedChainDecisionV2:
    """Project authenticated external evidence into the frozen strict journal."""

    response = inference.payload
    if (
        response.run_id != capture.run_id
        or response.run_id != execution.run_id
        or response.decision_index != capture.decision_index
        or response.decision_index != execution.decision_index
        or capture.observation.observation_id != execution.observation_id
        or inference.payload_sha256 != execution.inference_response_sha256
    ):
        raise ValueError("capture, inference, and execution are not the same decision cycle")
    mapping = execution.mapping
    pointer = response.pointer.selected_index
    destination = response.destination.selected_index
    mapping_status: Literal["VALID", "INVALID_POINTER", "STALE_TRACK", "INVALID_CELL", "INVALID"]
    if mapping.status == "VALID":
        mapping_status = "VALID"
    else:
        rejection = mapping.rejection_reason.value if mapping.rejection_reason else "INVALID"
        mapping_status = {
            "INVALID_POINTER": "INVALID_POINTER",
            "STALE_TRACK": "STALE_TRACK",
            "INVALID_DESTINATION_CELL": "INVALID_CELL",
            "DESTINATION_RESOLUTION_REJECTION": "INVALID_CELL",
        }.get(rejection, "INVALID")
    target_provenance = "MODEL" if response.intent.target_track_id is not None else "NONE"
    destination_provenance = "MODEL" if response.intent.destination_cell is not None else "NONE"
    return ModelOwnedChainDecisionV2(
        decision_id=response.request_id,
        step_index=response.decision_index,
        observation=PublicObservationReceiptV2(
            observation_id=capture.observation.observation_id,
            captured_at_ns=capture.observation.captured_at_ns,
            rgb_sha256=capture.observation.rgb.sha256,
            depth_sha256=capture.observation.depth.sha256,
            perception_track_ids=[
                track.track_id for track in capture.observation.perception_tracks
            ],
            pointer_slots=[
                track_id for track_id in capture.observation.canonical_slots if track_id is not None
            ],
            blocker_track_id=capture.public_roles.blocker_track_id,
            task_target_track_id=capture.public_roles.task_target_track_id,
        ),
        model_output_sha256=inference.payload_sha256,
        selected_skill=response.intent.skill_type,
        skill_provenance="MODEL",
        target_track_id=response.intent.target_track_id,
        target_pointer_class=pointer,
        target_provenance=target_provenance,
        destination_cell=response.intent.destination_cell,
        destination_class=destination,
        destination_provenance=destination_provenance,
        mapping_status=mapping_status,
        physical_skill_receipts=execution.physical_skill_receipts,
    )


def build_episode_from_external_evidence(
    *,
    run_id: str,
    failure_observed_at_ns: int,
    final_task_success: bool,
    decisions: list[ModelOwnedChainDecisionV2],
) -> ModelOwnedChainEpisodeV2:
    if [decision.step_index for decision in decisions] != list(range(8)):
        raise ValueError("formal episode decisions are not the complete ordered eight-step chain")
    return ModelOwnedChainEpisodeV2(
        episode_id=run_id,
        failure_observed_at_ns=failure_observed_at_ns,
        final_task_success=final_task_success,
        decisions=decisions,
    )


def validate_expected_chain_is_not_runner_selected(
    response: FormalInferenceResponseV2,
) -> None:
    """Check the bounded chain without changing model attribution.

    The expected skill is never a request field and never enters the Qwen
    prompt.  A mismatch remains a genuine model failure and must not cause the
    runner to substitute a fixed continuation.
    """

    expected = EXPECTED_PATH_BLOCKED_CHAIN[response.decision_index]
    if response.intent.skill_type != expected:
        raise ValueError(
            f"model selected {response.intent.skill_type}; bounded step requires {expected}"
        )
