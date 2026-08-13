"""ADR-0024 V4 public observation and exact revision guards.

This module intentionally defines only the new public observation boundary.
It does not reinterpret V1/V2/V3 evidence, build a training dataset, or
authorize collection.  Candidate payloads are recomputed from fresh public
tracks and the ADR-0021 declared-attribute token.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


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
    candidates: list[PublicTrackCandidateEntryV4] = Field(max_length=8)
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


class PathBlockedPublicObservationV4(_StrictModel):
    """One fresh public V2-associated observation with V4 K=8 candidates."""

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
    perception_tracks: list[PerceptionTrackV1] = Field(min_length=1)
    declared_target_attribute: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9_-]+$",
    )
    candidate_payload: PublicTrackCandidatePayloadV4
    candidate_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    task_target_track_id_used_for_candidates: Literal[False]

    @model_validator(mode="after")
    def public_observation_is_exact(self) -> "PathBlockedPublicObservationV4":
        for uri in (self.rgb_uri, self.depth_uri):
            relative = uri.removeprefix("dataset://")
            if relative.startswith("/") or ".." in relative.split("/"):
                raise ValueError("public asset URI escapes evidence root")
        expected_payload, expected_sha = recompute_candidate_payload_v4(self)
        if self.candidate_payload.model_dump(mode="json") != expected_payload:
            raise ValueError("V4 candidates are not recomputable from fresh public tracks")
        if self.candidate_payload_sha256 != expected_sha:
            raise ValueError("V4 candidate payload SHA-256 mismatch")
        return self


class M2CQ012CheckpointBindingV4(_StrictModel):
    """Minimal exact-load metadata guard for every future V4 checkpoint."""

    checkpoint_schema_version: Literal["QRMFormalCheckpointV4"]
    architecture_revision: Literal["M2C_Q012_V4"]
    public_observation_revision: Literal["PathBlockedPublicObservationV4"]
    public_track_associator_revision: Literal["PublicTrackAssociatorV2"]
    public_track_candidate_revision: Literal["PublicTrackCandidateV4"]
    public_track_candidate_count: Literal[8]
    pointer_class_count: Literal[9]
    recapture_policy: Literal["NONE"]


def recompute_candidate_payload_v4(
    observation: PathBlockedPublicObservationV4,
) -> tuple[dict[str, object], str]:
    candidates = build_public_track_candidates_v4(
        observation.perception_tracks,
        declared_target_attribute=observation.declared_target_attribute,
    )
    return (
        canonical_candidate_payload_v4(candidates),
        canonical_candidate_sha256_v4(candidates),
    )


def load_public_observation_v4(
    raw: str | bytes | Mapping[str, object],
) -> PathBlockedPublicObservationV4:
    """Load only an exact V4 observation; no cross-revision coercion exists."""

    if isinstance(raw, bytes):
        return PathBlockedPublicObservationV4.model_validate_json(raw)
    if isinstance(raw, str):
        return PathBlockedPublicObservationV4.model_validate_json(raw)
    return PathBlockedPublicObservationV4.model_validate(raw)


def load_checkpoint_binding_v4(
    raw: str | bytes | Mapping[str, object],
) -> M2CQ012CheckpointBindingV4:
    """Validate exact V4 metadata before a checkpoint tensor loader runs."""

    if isinstance(raw, bytes):
        return M2CQ012CheckpointBindingV4.model_validate_json(raw)
    if isinstance(raw, str):
        return M2CQ012CheckpointBindingV4.model_validate_json(raw)
    return M2CQ012CheckpointBindingV4.model_validate(raw)


def canonical_checkpoint_binding_sha256_v4(
    binding: M2CQ012CheckpointBindingV4,
) -> str:
    payload = binding.model_dump(mode="json")
    wire = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(wire).hexdigest()
