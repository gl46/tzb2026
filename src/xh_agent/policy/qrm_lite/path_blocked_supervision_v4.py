"""ADR-0024 V4 public observation replay and exact checkpoint guards.

V4 observations carry the complete ordered public association history.  A
host loader creates a new ``PublicTrackAssociatorV2`` from an externally
frozen protocol, replays every unassociated capture, compares every public
output byte-for-byte, and only then recomputes ADR-0021 K=8 candidates.
Nothing here upgrades or reinterprets V1/V2/V3 evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Literal, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PUBLIC_TRACK_MAX_CURRENT_DETECTIONS,
    PublicAssociatedTrackV2,
    PublicAssociationCaptureV2,
    PublicAssociationDeploymentBindingV2,
    PublicAssociationSessionReceiptV2,
    PublicProprioceptionJournalBindingV2,
    PublicTrackAssociatorV2,
)
from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)


def _canonical_sha256(payload: object) -> str:
    wire = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


class PublicTrackCandidateEntryV4(_StrictModel):
    track_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    pose_present: Literal[True]
    role: Literal["ROLE_TARGET_ATTRIBUTE_MATCH", "ROLE_MANIPULABLE_OTHER"]


class PublicTrackCandidatePayloadV4(_StrictModel):
    schema_version: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    candidate_count_bound: Literal[8]
    recapture_policy: Literal["NONE"]
    candidates: list[PublicTrackCandidateEntryV4] = Field(min_length=1, max_length=8)
    valid_mask: list[bool] = Field(min_length=8, max_length=8)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    task_target_track_id_used: Literal[False]

    @model_validator(mode="after")
    def mask_is_prefix_and_ids_unique(self) -> "PublicTrackCandidatePayloadV4":
        expected = [True] * len(self.candidates) + [False] * (8 - len(self.candidates))
        if self.valid_mask != expected:
            raise ValueError("V4 candidate mask does not match candidates")
        ids = [item.track_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("V4 candidate payload repeats a track")
        return self


class PublicAssociationReplayFrameV4(_StrictModel):
    schema_version: Literal["PublicAssociationReplayFrameV4"] = "PublicAssociationReplayFrameV4"
    capture: PublicAssociationCaptureV2
    associated_tracks: list[PublicAssociatedTrackV2] = Field(
        max_length=PUBLIC_TRACK_MAX_CURRENT_DETECTIONS
    )
    associated_tracks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def output_digest_is_bound(self) -> "PublicAssociationReplayFrameV4":
        payload = [item.model_dump(mode="json") for item in self.associated_tracks]
        if self.associated_tracks_sha256 != _canonical_sha256(payload):
            raise ValueError("V4 associated-track output digest mismatch")
        return self


class PathBlockedPublicObservationV4(_StrictModel):
    """One fresh public V4 observation with its replayable history."""

    schema_version: Literal["PathBlockedPublicObservationV4"]
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    source: Literal["PUBLIC_RGBD"]
    fresh: Literal[True]
    rgb_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    depth_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_track_associator_revision: Literal["PublicTrackAssociatorV2"]
    camera_frame: str = Field(min_length=1)
    position_units: Literal["m"]
    calibration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    association_history: list[PublicAssociationReplayFrameV4] = Field(min_length=1)
    perception_tracks: list[PerceptionTrackV1] = Field(
        min_length=1,
        max_length=PUBLIC_TRACK_MAX_CURRENT_DETECTIONS,
    )
    declared_target_attribute: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    candidate_payload: PublicTrackCandidatePayloadV4
    candidate_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    task_target_track_id_used_for_candidates: Literal[False]

    @model_validator(mode="after")
    def local_shape_is_exact(self) -> "PathBlockedPublicObservationV4":
        for uri in (self.rgb_uri, self.depth_uri):
            relative = uri.removeprefix("dataset://")
            if relative.startswith("/") or ".." in relative.split("/"):
                raise ValueError("public asset URI escapes evidence root")
        final = self.association_history[-1]
        if (
            final.capture.timestamp_ns != self.captured_at_ns
            or final.capture.capture_receipt_sha256 != self.capture_receipt_sha256
        ):
            raise ValueError("V4 observation does not bind final association capture")
        if not final.capture.detections or not final.associated_tracks:
            raise ValueError("V4 final observation has no current public detection")
        return self


class PublicDeclaredTargetAttributeBindingV4(_StrictModel):
    """Independent public TaskSpec-selector receipt for one declared token.

    This binding contains no target track identity.  The caller must freeze
    its canonical digest outside the observation before loading any V4
    candidate payload.
    """

    schema_version: Literal["PublicDeclaredTargetAttributeBindingV4"] = (
        "PublicDeclaredTargetAttributeBindingV4"
    )
    declared_target_attribute: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    public_target_selector: str = Field(
        min_length=1,
        pattern=r"^visual_color=[a-z0-9_-]+$",
    )
    selector_source_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_spec_public_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def selector_and_token_are_exactly_bound(self) -> "PublicDeclaredTargetAttributeBindingV4":
        if self.public_target_selector != f"visual_color={self.declared_target_attribute}":
            raise ValueError("public target selector differs from declared attribute token")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("public declared target attribute binding digest mismatch")
        return self


class M2CQ012TensorBindingV4(_StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    shape: list[int] = Field(min_length=1)
    dtype: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class M2CQ012CheckpointBindingV4(_StrictModel):
    checkpoint_schema_version: Literal["QRMFormalCheckpointV4"]
    architecture_revision: Literal["M2C_Q012_V4"]
    public_observation_revision: Literal["PathBlockedPublicObservationV4"]
    public_track_associator_revision: Literal["PublicTrackAssociatorV2"]
    raw_detection_capacity_revision: Literal["M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1"]
    max_raw_public_detections: Literal[32]
    public_track_candidate_revision: Literal["PublicTrackCandidateV4"]
    public_track_candidate_count: Literal[8]
    pointer_class_count: Literal[9]
    recapture_policy: Literal["NONE"]
    tensors: list[M2CQ012TensorBindingV4] = Field(min_length=1)
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def metadata_and_tensor_names_are_exact(self) -> "M2CQ012CheckpointBindingV4":
        names = [item.name for item in self.tensors]
        if len(names) != len(set(names)):
            raise ValueError("V4 checkpoint metadata repeats a tensor")
        payload = self.model_dump(mode="json", exclude={"metadata_sha256"})
        if self.metadata_sha256 != _canonical_sha256(payload):
            raise ValueError("V4 checkpoint metadata digest mismatch")
        return self


class M2CQ012DeploymentManifestV4(_StrictModel):
    """Externally frozen checkpoint file and metadata binding."""

    schema_version: Literal["M2CQ012DeploymentManifestV4"] = "M2CQ012DeploymentManifestV4"
    architecture_revision: Literal["M2C_Q012_V4"] = "M2C_Q012_V4"
    checkpoint_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def manifest_is_self_consistent(self) -> "M2CQ012DeploymentManifestV4":
        expected = _canonical_sha256(
            self.model_dump(mode="json", exclude={"deployment_manifest_sha256"})
        )
        if self.deployment_manifest_sha256 != expected:
            raise ValueError("V4 checkpoint deployment manifest digest mismatch")
        return self


@dataclass(frozen=True)
class LoadedM2CQ012CheckpointV4:
    file_sha256: str
    binding: M2CQ012CheckpointBindingV4
    tensors: Mapping[str, np.ndarray]


def associated_tracks_to_perception_tracks_v4(
    tracks: list[PublicAssociatedTrackV2],
) -> list[PerceptionTrackV1]:
    return [
        PerceptionTrackV1(
            track_id=item.track_id,
            category=(
                f"{item.category}:{item.attributes.visual_color}"
                if item.attributes.visual_color
                else item.category
            ),
            confidence=item.confidence,
            pose_xyzquat=[*item.position_world_m, 0.0, 0.0, 0.0, 1.0],
        )
        for item in tracks
    ]


def recompute_candidate_payload_v4(
    observation: PathBlockedPublicObservationV4,
) -> tuple[dict[str, object], str]:
    candidates = build_public_track_candidates_v4(
        observation.perception_tracks,
        declared_target_attribute=observation.declared_target_attribute,
    )
    return canonical_candidate_payload_v4(candidates), canonical_candidate_sha256_v4(candidates)


def validate_public_observation_replay_v4(
    observation: PathBlockedPublicObservationV4,
    *,
    expected_deployment: PublicAssociationDeploymentBindingV2,
    expected_deployment_binding_sha256: str,
    expected_journal: PublicProprioceptionJournalBindingV2,
    expected_session_receipt: PublicAssociationSessionReceiptV2,
    expected_session_receipt_sha256: str,
    expected_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
    expected_attribute_binding_sha256: str,
) -> PathBlockedPublicObservationV4:
    expected_deployment = PublicAssociationDeploymentBindingV2.model_validate(
        expected_deployment.model_dump(mode="json")
        if isinstance(expected_deployment, PublicAssociationDeploymentBindingV2)
        else expected_deployment
    )
    expected_attribute_binding = PublicDeclaredTargetAttributeBindingV4.model_validate(
        expected_attribute_binding.model_dump(mode="json")
        if isinstance(expected_attribute_binding, PublicDeclaredTargetAttributeBindingV4)
        else expected_attribute_binding
    )
    if expected_deployment.deployment_binding_sha256 != expected_deployment_binding_sha256:
        raise ValueError("public association deployment differs from external expected digest")
    expected_protocol = expected_deployment.protocol
    if (
        observation.camera_frame != expected_protocol.declared_camera_frame
        or observation.position_units != expected_protocol.metric_units
        or observation.calibration_sha256 != expected_protocol.calibration_sha256
    ):
        raise ValueError("V4 observation differs from external protocol binding")
    associator = PublicTrackAssociatorV2(
        expected_deployment=expected_deployment,
        expected_deployment_binding_sha256=expected_deployment_binding_sha256,
        expected_journal=expected_journal,
        expected_session_receipt=expected_session_receipt,
        expected_session_receipt_sha256=expected_session_receipt_sha256,
    )
    replayed: list[PublicAssociatedTrackV2] = []
    for position, frame in enumerate(observation.association_history):
        replayed = associator.associate(frame.capture)
        if replayed != frame.associated_tracks:
            raise ValueError(f"V4 association replay differs at frame {position}")
    if not associator.journal_complete:
        raise ValueError("V4 association history does not consume the frozen journal")
    expected_tracks = associated_tracks_to_perception_tracks_v4(replayed)
    if observation.perception_tracks != expected_tracks:
        raise ValueError("V4 observation tracks differ from association replay")
    if expected_attribute_binding.binding_sha256 != expected_attribute_binding_sha256:
        raise ValueError("V4 declared attribute differs from external expected digest")
    if (
        observation.declared_target_attribute
        != expected_attribute_binding.declared_target_attribute
    ):
        raise ValueError("V4 declared attribute differs from public TaskSpec receipt")
    expected_payload, expected_sha = recompute_candidate_payload_v4(observation)
    if observation.candidate_payload.model_dump(mode="json") != expected_payload:
        raise ValueError("V4 candidates are not recomputable from replayed public tracks")
    if observation.candidate_payload_sha256 != expected_sha:
        raise ValueError("V4 candidate payload SHA-256 mismatch")
    return observation


def load_public_observation_v4(
    raw: str | bytes | Mapping[str, object],
    *,
    expected_deployment: PublicAssociationDeploymentBindingV2,
    expected_deployment_binding_sha256: str,
    expected_journal: PublicProprioceptionJournalBindingV2,
    expected_session_receipt: PublicAssociationSessionReceiptV2,
    expected_session_receipt_sha256: str,
    expected_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
    expected_attribute_binding_sha256: str,
) -> PathBlockedPublicObservationV4:
    if isinstance(raw, (bytes, str)):
        observation = PathBlockedPublicObservationV4.model_validate_json(raw)
    else:
        observation = PathBlockedPublicObservationV4.model_validate(raw)
    return validate_public_observation_replay_v4(
        observation,
        expected_deployment=expected_deployment,
        expected_deployment_binding_sha256=expected_deployment_binding_sha256,
        expected_journal=expected_journal,
        expected_session_receipt=expected_session_receipt,
        expected_session_receipt_sha256=expected_session_receipt_sha256,
        expected_attribute_binding=expected_attribute_binding,
        expected_attribute_binding_sha256=expected_attribute_binding_sha256,
    )


def load_checkpoint_binding_v4(
    raw: str | bytes | Mapping[str, object],
) -> M2CQ012CheckpointBindingV4:
    if isinstance(raw, (bytes, str)):
        return M2CQ012CheckpointBindingV4.model_validate_json(raw)
    return M2CQ012CheckpointBindingV4.model_validate(raw)


def canonical_checkpoint_binding_sha256_v4(
    binding: M2CQ012CheckpointBindingV4,
) -> str:
    return _canonical_sha256(binding.model_dump(mode="json"))


def canonical_attribute_binding_sha256_v4(
    binding: PublicDeclaredTargetAttributeBindingV4,
) -> str:
    return _canonical_sha256(binding.model_dump(mode="json", exclude={"binding_sha256"}))


def canonical_checkpoint_deployment_sha256_v4(
    manifest: M2CQ012DeploymentManifestV4,
) -> str:
    return _canonical_sha256(
        manifest.model_dump(mode="json", exclude={"deployment_manifest_sha256"})
    )


def _read_regular_checkpoint_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("V4 checkpoint must be a single-link regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("V4 checkpoint changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def load_m2c_q012_checkpoint_v4(
    path: Path,
    *,
    expected_deployment: M2CQ012DeploymentManifestV4,
    expected_deployment_manifest_sha256: str,
) -> LoadedM2CQ012CheckpointV4:
    """Read once, then validate metadata before exposing any tensor."""

    expected_deployment = M2CQ012DeploymentManifestV4.model_validate(
        expected_deployment.model_dump(mode="json")
        if isinstance(expected_deployment, M2CQ012DeploymentManifestV4)
        else expected_deployment
    )
    if expected_deployment.deployment_manifest_sha256 != expected_deployment_manifest_sha256:
        raise ValueError("V4 checkpoint deployment differs from external expected digest")
    raw = _read_regular_checkpoint_once(path)
    actual_file_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_file_sha256 != expected_deployment.checkpoint_file_sha256:
        raise ValueError("V4 checkpoint file SHA-256 mismatch")
    with np.load(io.BytesIO(raw), allow_pickle=False) as payload:
        if "metadata_json" not in payload.files:
            raise ValueError("V4 checkpoint lacks metadata_json")
        metadata_raw = np.asarray(payload["metadata_json"])
        if metadata_raw.shape != ():
            raise ValueError("V4 checkpoint metadata_json must be scalar")
        binding = load_checkpoint_binding_v4(str(metadata_raw.item()))
        if (
            canonical_checkpoint_binding_sha256_v4(binding)
            != expected_deployment.checkpoint_binding_sha256
        ):
            raise ValueError("V4 checkpoint metadata differs from deployment manifest")
        expected_names = {item.name for item in binding.tensors}
        actual_names = set(payload.files) - {"metadata_json"}
        if actual_names != expected_names:
            raise ValueError("V4 checkpoint tensor inventory differs from metadata")
        arrays: dict[str, np.ndarray] = {}
        for tensor in binding.tensors:
            value = np.asarray(payload[tensor.name])
            if list(value.shape) != tensor.shape or str(value.dtype) != tensor.dtype:
                raise ValueError(f"V4 checkpoint tensor layout differs: {tensor.name}")
            if not np.issubdtype(value.dtype, np.number) or not np.isfinite(value).all():
                raise ValueError(f"V4 checkpoint tensor is invalid: {tensor.name}")
            if hashlib.sha256(value.tobytes(order="C")).hexdigest() != tensor.sha256:
                raise ValueError(f"V4 checkpoint tensor SHA-256 differs: {tensor.name}")
            immutable = value.copy()
            immutable.setflags(write=False)
            arrays[tensor.name] = immutable
    return LoadedM2CQ012CheckpointV4(
        file_sha256=actual_file_sha256,
        binding=binding,
        tensors=MappingProxyType(arrays),
    )
