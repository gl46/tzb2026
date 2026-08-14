"""Strict ADR-0024 V4 TRAIN collection and host-replay contracts.

This module is intentionally disjoint from the historical V2/V3 evidence
families.  It does not authorize a physical attempt; it validates the frozen
V4 manifest and packages only observations whose complete unassociated public
capture history is independently replayable by ``PublicTrackAssociatorV2``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PUBLIC_TRACK_ASSIGNMENT_OBJECTIVE,
    PUBLIC_TRACK_ASSOCIATION_GATE_M,
    PUBLIC_TRACK_AMBIGUITY_MARGIN_M,
    PUBLIC_TRACK_COST_QUANTUM_M,
    PUBLIC_RAW_DETECTION_CAPACITY_REVISION,
    PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES,
    PUBLIC_TRACK_MAX_CURRENT_DETECTIONS,
    LastPhysicallyExecutedPublicSkillV2,
    PublicAssociatedTrackV2,
    PublicAssociationCaptureV2,
    PublicAssociationDeploymentBindingV2,
    PublicAssociationProtocolV2,
    PublicAssociationSessionReceiptV2,
    PublicProprioceptionCaptureBindingV2,
    PublicProprioceptionJournalBindingV2,
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
    PublicTrackAssociatorV2,
    public_track_associator_implementation_sha256_v2,
)
from xh_agent.data_engine.isaac.public_failure_predicates import (
    PublicTrackSnapshotV2,
    select_task_target_track,
)
from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV2,
    DestinationCellV2,
    FailureType,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    EXPECTED_PATH_BLOCKED_CHAIN,
    NONE_DESTINATION_CLASS,
    NONE_POINTER_CLASS,
    REGISTERED_DESTINATION_CELLS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    M2C_Q012_V2_SKILL_LABELS,
    FrozenS6ExclusionManifestV2,
    PathBlockedPhysicalSkillReceiptV2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
    PublicAssociationReplayFrameV4,
    PublicDeclaredTargetAttributeBindingV4,
    associated_tracks_to_perception_tracks_v4,
    canonical_attribute_binding_sha256_v4,
    load_public_observation_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)


M2C_Q012_V4_SKILL_LABELS = M2C_Q012_V2_SKILL_LABELS
V4_MANIFEST_SCHEMA = "M2CS4V4TrainingKeyManifestV1"
V4_MANIFEST_STATUS = "FROZEN_TRAIN_ONLY_BEFORE_ANY_V4_COLLECTION"
V4_MANIFEST_KEY = "M2C_S4_V4_FROZEN_TRAIN_KEYS"
# Filled only after the create-only builder output is frozen.
V4_MANIFEST_FILE_SHA256 = "83a672f439521dc2c6263225851ec54cbd80de052af835a6590a7e02443b79c4"
V4_MANIFEST_CONTENT_SHA256 = "525cd393fd4264ef7d47691d142616d4fc59c068c25336f43fe3b54f8753a034"
V4_EXTENSION1_MANIFEST_FILE_SHA256 = (
    "9fcc971f5bdf0787692b6d2de9be81885fe164e4b78b34fac214d6467c64e164"
)
V4_EXTENSION1_MANIFEST_CONTENT_SHA256 = (
    "efb69cfc509abca6ed98b7ab476b8d4f3f154aa1d2f2c417fa8f439a5422f34f"
)
V4_EXTENSION1_MANIFEST_KEY = "M2C_S4_V4_FROZEN_TRAIN_KEYS_EXTENSION1"
V2_TRAIN_SMOKE_MANIFEST_SHA256 = "ca2162a898853ee04600aaf9246c121ac0604754638e497d1824b159c161fd94"
V3_TRAIN_MANIFEST_SHA256 = "b5a2da566f4086724e99cea1664aeeac3b91344a68b72be84bcf6c5d0ddad65c"
V4_QA_MANIFEST_SHA256 = "4e78c044b68b11c1d871ecb90e65c7e2dfc616c8971abb89cb9969d2d48f738b"
S6_MANIFEST_SHA256 = "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
V4_QA_SCENE_SEEDS = frozenset({9038, 9057, 9077})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class M2CS4V4TrainingKeyV1(StrictModel):
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    split: Literal["train"] = "train"
    role: Literal["TRAIN"] = "TRAIN"
    failure_type: Literal["PATH_BLOCKED"] = "PATH_BLOCKED"
    layout_family: Literal["M2C_V4_ACCEPTED_BLOCKER_GEOMETRY"]
    anchor_xy_m: list[float] = Field(min_length=2, max_length=2)
    blocker_distance_m: float
    retained_blocker_distance_m: float
    blocker_selector_policy_input: str
    target_selector_policy_input: str
    declared_target_attribute: Literal["yellow"] = "yellow"
    candidate_contract_revision: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    candidate_count_bound: Literal[8]
    recapture_policy: Literal["NONE"]
    destination_cell: DestinationCellV2
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offline_geometry_admission: dict[str, Any]
    offline_scene_materialized_during_selection: Literal[True]
    outcome_observed_during_selection: Literal[False]
    previously_executed: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    matched_key: str = Field(pattern=r"^m2c-s4-v4-train-[0-9a-f]{64}$")

    @model_validator(mode="after")
    def public_selector_is_exact(self) -> "M2CS4V4TrainingKeyV1":
        if "visual_color=yellow" not in self.target_selector_policy_input:
            raise ValueError("V4 TaskSpec selector does not declare yellow")
        if "visual_color=red" not in self.blocker_selector_policy_input:
            raise ValueError("V4 blocker selector is not public red")
        return self


class M2CS4V4TrainingKeyManifestV1(StrictModel):
    schema_version: Literal["M2CS4V4TrainingKeyManifestV1"]
    status: Literal["FROZEN_TRAIN_ONLY_BEFORE_ANY_V4_COLLECTION"]
    written_date_asia_shanghai: str
    train_only: Literal[True]
    candidate_contract_revision: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    candidate_count_bound: Literal[8]
    pointer_class_count: Literal[9]
    recapture_policy: Literal["NONE"]
    declared_target_attribute: Literal["yellow"]
    selection_uses_rollout_outcomes: Literal[False]
    any_v4_collection_observed_before_freeze: Literal[False]
    collection_executed: Literal[False]
    training_executed: Literal[False]
    smoke_collection_authorized: Literal[False]
    evaluation_collection_authorized: Literal[False]
    candidate_implementation: dict[str, str]
    accepted_implementation_commit: Literal["abc08e63de85263f781b458ac50b3644f806ec6c"]
    v4_implementation_bindings: dict[str, str]
    selection_implementation: dict[str, Any]
    selection_protocol: dict[str, Any]
    source_bindings: dict[str, str]
    exclusion_contract: dict[str, Any]
    exclusions: dict[str, Any]
    layout_contract: dict[str, Any]
    training_key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_keys: list[M2CS4V4TrainingKeyV1] = Field(min_length=36, max_length=36)
    physical_prerequisite_smoke_keys: list[Any] = Field(max_length=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def frozen_identity_is_exact(self) -> "M2CS4V4TrainingKeyManifestV1":
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != V4_MANIFEST_CONTENT_SHA256:
            raise ValueError("V4 embedded manifest identity is not frozen")
        if canonical_sha256(payload) != self.manifest_sha256:
            raise ValueError("V4 embedded manifest SHA-256 mismatch")
        records = [item.model_dump(mode="json") for item in self.training_keys]
        if canonical_sha256(records) != self.training_key_digest:
            raise ValueError("V4 training-key digest mismatch")
        for field in ("matched_key", "scene_seed", "failure_seed"):
            values = [getattr(item, field) for item in self.training_keys]
            if len(values) != len(set(values)):
                raise ValueError(f"V4 TRAIN manifest repeats {field}")
        expected_sources = {
            "configs/m2c_s4_training_keys.json": V2_TRAIN_SMOKE_MANIFEST_SHA256,
            "configs/m2c_s4_v3_training_keys.json": V3_TRAIN_MANIFEST_SHA256,
            "configs/m2c_headroom_domain_v4.json": V4_QA_MANIFEST_SHA256,
            "configs/m2c_s6_evaluation_keys.json": S6_MANIFEST_SHA256,
        }
        if any(
            self.source_bindings.get(path) != digest for path, digest in expected_sources.items()
        ):
            raise ValueError("V4 manifest does not bind every excluded identity source")
        required = {
            "old_v2_train_and_smoke": True,
            "complete_v3_train": True,
            "v4_q_a": True,
            "all_s6_evaluation": True,
        }
        if any(self.exclusion_contract.get(key) is not value for key, value in required.items()):
            raise ValueError("V4 exclusion contract is incomplete")
        return self


class M2CS4V4TrainingKeyExtensionManifestV1(StrictModel):
    """First outcome-blind extension of the exhausted immutable V4 TRAIN manifest."""

    schema_version: Literal["M2CS4V4TrainingKeyExtensionManifestV1"]
    status: Literal["FROZEN_TRAIN_ONLY_BEFORE_ANY_SELECTED_KEY_COLLECTION"]
    written_date_asia_shanghai: str
    train_only: Literal[True]
    candidate_contract_revision: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    candidate_count_bound: Literal[8]
    pointer_class_count: Literal[9]
    recapture_policy: Literal["NONE"]
    declared_target_attribute: Literal["yellow"]
    selection_uses_rollout_outcomes: Literal[False]
    any_selected_key_collection_observed_before_freeze: Literal[False]
    collection_executed: Literal[False]
    training_executed: Literal[False]
    smoke_collection_authorized: Literal[False]
    evaluation_collection_authorized: Literal[False]
    candidate_implementation: dict[str, str]
    accepted_contract_commits: dict[str, str]
    v4_implementation_bindings: dict[str, str]
    selection_implementation: dict[str, Any]
    selection_protocol: dict[str, Any]
    source_bindings: dict[str, str]
    exclusion_contract: dict[str, Any]
    exclusions: dict[str, Any]
    layout_contract: dict[str, Any]
    training_key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_keys: list[M2CS4V4TrainingKeyV1] = Field(min_length=36, max_length=36)
    physical_prerequisite_smoke_keys: list[Any] = Field(max_length=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def frozen_extension_identity_is_exact(self) -> "M2CS4V4TrainingKeyExtensionManifestV1":
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != V4_EXTENSION1_MANIFEST_CONTENT_SHA256:
            raise ValueError("V4 extension embedded manifest identity is not frozen")
        if canonical_sha256(payload) != self.manifest_sha256:
            raise ValueError("V4 extension embedded manifest SHA-256 mismatch")
        records = [item.model_dump(mode="json") for item in self.training_keys]
        if canonical_sha256(records) != self.training_key_digest:
            raise ValueError("V4 extension training-key digest mismatch")
        for field in ("matched_key", "scene_seed", "failure_seed"):
            values = [getattr(item, field) for item in self.training_keys]
            if len(values) != len(set(values)):
                raise ValueError(f"V4 extension TRAIN manifest repeats {field}")
        expected_sources = {
            "configs/m2c_s4_training_keys.json": V2_TRAIN_SMOKE_MANIFEST_SHA256,
            "configs/m2c_s4_v3_training_keys.json": V3_TRAIN_MANIFEST_SHA256,
            "configs/m2c_s4_v4_training_keys.json": V4_MANIFEST_FILE_SHA256,
            "configs/m2c_headroom_domain_v4.json": V4_QA_MANIFEST_SHA256,
            "configs/m2c_s6_evaluation_keys.json": S6_MANIFEST_SHA256,
        }
        if any(
            self.source_bindings.get(path) != digest for path, digest in expected_sources.items()
        ):
            raise ValueError("V4 extension does not bind every excluded identity source")
        required = {
            "old_v2_train_and_smoke": True,
            "complete_v3_train": True,
            "original_v4_train": True,
            "v4_q_a": True,
            "all_s6_evaluation": True,
        }
        if any(self.exclusion_contract.get(key) is not value for key, value in required.items()):
            raise ValueError("V4 extension exclusion contract is incomplete")
        return self


V4TrainingKeyManifest = M2CS4V4TrainingKeyManifestV1 | M2CS4V4TrainingKeyExtensionManifestV1


def _manifest_profile_for_content(content_sha256: str) -> tuple[str, str, str]:
    profiles = {
        V4_MANIFEST_CONTENT_SHA256: (
            V4_MANIFEST_KEY,
            V4_MANIFEST_FILE_SHA256,
            "M2CS4V4TrainingKeyManifestV1",
        ),
        V4_EXTENSION1_MANIFEST_CONTENT_SHA256: (
            V4_EXTENSION1_MANIFEST_KEY,
            V4_EXTENSION1_MANIFEST_FILE_SHA256,
            "M2CS4V4TrainingKeyExtensionManifestV1",
        ),
    }
    try:
        return profiles[content_sha256]
    except KeyError as error:
        raise ValueError("V4 TRAIN manifest content identity is not frozen") from error


def v4_manifest_file_sha256(manifest: V4TrainingKeyManifest) -> str:
    return _manifest_profile_for_content(manifest.manifest_sha256)[1]


def v4_manifest_key(manifest: V4TrainingKeyManifest) -> str:
    return _manifest_profile_for_content(manifest.manifest_sha256)[0]


def validate_v4_training_manifest_payload(
    payload: Mapping[str, Any],
) -> V4TrainingKeyManifest:
    schema = payload.get("schema_version")
    if schema == "M2CS4V4TrainingKeyManifestV1":
        return M2CS4V4TrainingKeyManifestV1.model_validate(payload)
    if schema == "M2CS4V4TrainingKeyExtensionManifestV1":
        return M2CS4V4TrainingKeyExtensionManifestV1.model_validate(payload)
    raise ValueError("V4 TRAIN manifest schema is not frozen")


def load_v4_training_manifest(path: Path) -> V4TrainingKeyManifest:
    raw = path.read_bytes()
    file_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("V4 TRAIN manifest is not JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("V4 TRAIN manifest is not an object")
    schema = payload.get("schema_version")
    manifest = validate_v4_training_manifest_payload(payload)
    _key, expected_file_sha256, expected_schema = _manifest_profile_for_content(
        manifest.manifest_sha256
    )
    if file_sha256 != expected_file_sha256 or schema != expected_schema:
        raise ValueError("V4 collection requires an exact frozen TRAIN manifest file")
    return manifest


class FrozenManifestRefV4(StrictModel):
    schema_version: Literal["FrozenManifestRefV4"] = "FrozenManifestRefV4"
    manifest_key: Literal[
        "M2C_S4_V4_FROZEN_TRAIN_KEYS",
        "M2C_S4_V4_FROZEN_TRAIN_KEYS_EXTENSION1",
    ] = V4_MANIFEST_KEY
    manifest_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def manifest_profile_is_frozen(self) -> "FrozenManifestRefV4":
        expected_key, expected_file_sha256, _schema = _manifest_profile_for_content(
            self.manifest_sha256
        )
        if (self.manifest_key, self.manifest_file_sha256) != (
            expected_key,
            expected_file_sha256,
        ):
            raise ValueError("V4 evidence manifest reference is not a frozen profile")
        return self


class PathBlockedRawPublicObservationV4(StrictModel):
    schema_version: Literal["PathBlockedRawPublicObservationV4"]
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    source: Literal["PUBLIC_RGBD"]
    fresh: Literal[True]
    rgb_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    depth_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    association_capture_index: int = Field(ge=0, le=7)
    declared_target_attribute: Literal["yellow"]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    task_target_track_id_used_for_candidates: Literal[False]


class M2CV4RawPublicAssociationCaptureV1(StrictModel):
    """Historical ADR-0024 evidence schema; never upgraded in place."""

    schema_version: Literal["M2CV4RawPublicAssociationCaptureV1"]
    timestamp_ns: int = Field(gt=0)
    camera_frame: str = Field(min_length=1)
    world_frame: str = Field(min_length=1)
    position_units: Literal["m"]
    camera_to_world_row_major: list[float] = Field(min_length=16, max_length=16)
    detections: list[PublicRGBDDetectionV2] = Field(max_length=8)
    proprioception_interval: list[PublicRobotProprioceptionV2] = Field(min_length=1)
    last_physically_executed_public_skill: LastPhysicallyExecutedPublicSkillV2 | None
    rgb_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    depth_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def raw_public_fields_are_aligned(self) -> "M2CV4RawPublicAssociationCaptureV1":
        if any(item.timestamp_ns != self.timestamp_ns for item in self.detections):
            raise ValueError("V4 raw detections differ from capture timestamp")
        if any(item.frame_id != self.camera_frame for item in self.detections):
            raise ValueError("V4 raw detections differ from capture frame")
        timestamps = [item.timestamp_ns for item in self.proprioception_interval]
        if timestamps[-1] != self.timestamp_ns or any(
            after <= before for before, after in zip(timestamps, timestamps[1:])
        ):
            raise ValueError("V4 raw proprioception interval is not ordered to capture")
        if any(item.world_frame != self.world_frame for item in self.proprioception_interval):
            raise ValueError("V4 raw proprioception frame differs")
        return self


class M2CV4RawPublicAssociationCaptureV2(StrictModel):
    """ADR-0025 raw public capture; final candidate K remains eight."""

    schema_version: Literal["M2CV4RawPublicAssociationCaptureV2"]
    raw_detection_capacity_revision: Literal["M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1"]
    max_raw_public_detections: Literal[32]
    timestamp_ns: int = Field(gt=0)
    camera_frame: str = Field(min_length=1)
    world_frame: str = Field(min_length=1)
    position_units: Literal["m"]
    camera_to_world_row_major: list[float] = Field(min_length=16, max_length=16)
    detections: list[PublicRGBDDetectionV2] = Field(max_length=PUBLIC_TRACK_MAX_CURRENT_DETECTIONS)
    proprioception_interval: list[PublicRobotProprioceptionV2] = Field(min_length=1)
    last_physically_executed_public_skill: LastPhysicallyExecutedPublicSkillV2 | None
    rgb_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    depth_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def raw_public_fields_are_aligned(self) -> "M2CV4RawPublicAssociationCaptureV2":
        if any(item.timestamp_ns != self.timestamp_ns for item in self.detections):
            raise ValueError("V4 raw detections differ from capture timestamp")
        if any(item.frame_id != self.camera_frame for item in self.detections):
            raise ValueError("V4 raw detections differ from capture frame")
        timestamps = [item.timestamp_ns for item in self.proprioception_interval]
        if timestamps[-1] != self.timestamp_ns or any(
            after <= before for before, after in zip(timestamps, timestamps[1:])
        ):
            raise ValueError("V4 raw proprioception interval is not ordered to capture")
        if any(item.world_frame != self.world_frame for item in self.proprioception_interval):
            raise ValueError("V4 raw proprioception frame differs")
        return self


class PathBlockedRawPhysicalStepEvidenceV4(StrictModel):
    schema_version: Literal["PathBlockedRawPhysicalStepEvidenceV4"]
    decision_index: int = Field(ge=0, le=7)
    observation: PathBlockedRawPublicObservationV4
    scripted_public_selector_color: Literal["red", "yellow"] | None
    destination_cell_label: DestinationCellV2 | None = None
    physical_receipts: list[PathBlockedPhysicalSkillReceiptV2]
    label_source: Literal["PUBLIC_RGBD_PHYSICAL_SUPERVISION"]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class M2CPathBlockedRawProbeChainV4(StrictModel):
    schema_version: Literal["M2CPathBlockedRawProbeChainV4"]
    evidence_origin: Literal["ISAAC_PHYSICAL_INTEGRATION"]
    episode_id: str
    failure_type: Literal["PATH_BLOCKED"]
    scene_seed: int
    failure_seed: int
    split: Literal["train"]
    split_group: str
    matched_key: str
    collection_role: Literal["TRAIN"]
    collection_key: str
    declared_target_attribute: Literal["yellow"]
    candidate_contract_revision: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    collection_authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_observed_at_ns: int = Field(gt=0)
    final_task_success: bool
    steps: list[PathBlockedRawPhysicalStepEvidenceV4]
    model_rollout: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class PathBlockedPhysicalStepEvidenceV4(StrictModel):
    schema_version: Literal["PathBlockedPhysicalStepEvidenceV4"]
    decision_index: int = Field(ge=0, le=7)
    observation: PathBlockedPublicObservationV4
    expected_proprioception_journal: PublicProprioceptionJournalBindingV2
    expected_association_session_receipt: PublicAssociationSessionReceiptV2
    expected_association_session_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_blocker_track_id: str | None = None
    public_task_target_track_id: str | None = None
    destination_cell_label: DestinationCellV2 | None = None
    physical_receipts: list[PathBlockedPhysicalSkillReceiptV2]
    label_source: Literal["PUBLIC_RGBD_PHYSICAL_SUPERVISION"]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class M2CPathBlockedProbeChainV4(StrictModel):
    schema_version: Literal["M2CPathBlockedProbeChainV4"]
    evidence_origin: Literal["ISAAC_PHYSICAL_INTEGRATION"]
    episode_id: str
    failure_type: Literal["PATH_BLOCKED"]
    scene_seed: int
    failure_seed: int
    split: Literal["train"]
    split_group: str
    matched_key: str
    collection_role: Literal["TRAIN"]
    collection_key: str
    declared_target_attribute: Literal["yellow"]
    candidate_contract_revision: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    expected_association_deployment: PublicAssociationDeploymentBindingV2
    expected_association_deployment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4
    expected_declared_attribute_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    collection_authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_observed_at_ns: int = Field(gt=0)
    final_task_success: bool
    steps: list[PathBlockedPhysicalStepEvidenceV4]
    model_rollout: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


def _self_hashed(model: type[BaseModel], payload: dict[str, Any], field: str) -> Any:
    payload[field] = canonical_sha256(payload)
    return model.model_validate(payload)


def _selector_color(selector: str, *, expected: str) -> str:
    tokens = selector.split(",")
    colors = [item.split("=", 1)[1] for item in tokens if item.startswith("visual_color=")]
    if colors != [expected]:
        raise ValueError("V4 public selector does not contain one exact visual_color token")
    return colors[0]


def _journal_for(
    captures: list[PublicAssociationCaptureV2],
    *,
    protocol_sha256: str,
    capture_source_sha256: str,
) -> PublicProprioceptionJournalBindingV2:
    payload: dict[str, Any] = {
        "schema_version": "PublicProprioceptionJournalBindingV2",
        "protocol_sha256": protocol_sha256,
        "source_implementation_sha256": capture_source_sha256,
        "captures": [
            PublicProprioceptionCaptureBindingV2(
                capture_timestamp_ns=item.timestamp_ns,
                previous_capture_receipt_sha256=item.previous_capture_receipt_sha256,
                capture_receipt_sha256=item.capture_receipt_sha256,
                expected_sample_timestamps_ns=(
                    item.proprioception_interval.expected_sample_timestamps_ns
                ),
                samples_sha256=item.proprioception_interval.samples_sha256,
            ).model_dump(mode="json")
            for item in captures
        ],
    }
    return _self_hashed(PublicProprioceptionJournalBindingV2, payload, "journal_sha256")


def _session_for(
    journal: PublicProprioceptionJournalBindingV2,
    deployment: PublicAssociationDeploymentBindingV2,
) -> PublicAssociationSessionReceiptV2:
    payload: dict[str, Any] = {
        "schema_version": "PublicAssociationSessionReceiptV2",
        "deployment_binding_sha256": deployment.deployment_binding_sha256,
        "capture_source_implementation_sha256": deployment.capture_source_implementation_sha256,
        "proprioception_journal_sha256": journal.journal_sha256,
        "capture_count": len(journal.captures),
        "first_capture_receipt_sha256": journal.captures[0].capture_receipt_sha256,
        "final_capture_receipt_sha256": journal.captures[-1].capture_receipt_sha256,
    }
    return _self_hashed(PublicAssociationSessionReceiptV2, payload, "session_receipt_sha256")


def _public_selector_track_id(
    tracks: list[PublicAssociatedTrackV2],
    *,
    color: str,
) -> str:
    selected = select_task_target_track(
        [
            PublicTrackSnapshotV2(
                track_id=item.track_id,
                category=item.category,
                visual_color=item.attributes.visual_color,
                position_world_m=item.position_world_m,
                confidence=item.confidence,
            )
            for item in tracks
        ],
        visual_color=color,
        world_axis="x",
        extremum="max",
        maximum_height_below_tallest_m=0.02,
    )
    return selected.track_id


def host_replay_probe_chain_v4(
    raw_chain: Mapping[str, Any],
    raw_captures: list[Mapping[str, Any]],
    *,
    training_key: M2CS4V4TrainingKeyV1,
    training_manifest: V4TrainingKeyManifest,
    capture_source_implementation_sha256: str,
) -> M2CPathBlockedProbeChainV4:
    """Independently turn raw public detections into exact V4 observations."""

    chain = M2CPathBlockedRawProbeChainV4.model_validate(raw_chain)
    captures = [M2CV4RawPublicAssociationCaptureV2.model_validate(item) for item in raw_captures]
    if len(chain.steps) != 8 or len(captures) != 8:
        raise ValueError("V4 host replay requires exactly eight steps and captures")
    if [step.decision_index for step in chain.steps] != list(range(8)):
        raise ValueError("V4 raw chain decision indices are not canonical")
    if [step.observation.association_capture_index for step in chain.steps] != list(range(8)):
        raise ValueError("V4 raw observations do not bind the ordered capture history")
    first = captures[0]
    protocol = PublicAssociationProtocolV2(
        declared_camera_frame=first.camera_frame,
        declared_world_frame=first.world_frame,
        metric_units=first.position_units,
        camera_to_world_row_major=first.camera_to_world_row_major,
        calibration_sha256=canonical_sha256(first.camera_to_world_row_major),
    )
    protocol_sha256 = canonical_sha256(protocol.model_dump(mode="json"))
    deployment_payload: dict[str, Any] = {
        "schema_version": "PublicAssociationDeploymentBindingV2",
        "associator_revision": "PublicTrackAssociatorV2",
        "associator_implementation_sha256": (public_track_associator_implementation_sha256_v2()),
        "capture_source_implementation_sha256": capture_source_implementation_sha256,
        "protocol": protocol.model_dump(mode="json"),
        "protocol_sha256": protocol_sha256,
        "assignment_objective": PUBLIC_TRACK_ASSIGNMENT_OBJECTIVE,
        "association_gate_m": PUBLIC_TRACK_ASSOCIATION_GATE_M,
        "ambiguity_margin_m": PUBLIC_TRACK_AMBIGUITY_MARGIN_M,
        "cost_quantum_m": PUBLIC_TRACK_COST_QUANTUM_M,
        "max_consecutive_unmatched_captures": (PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES),
        "raw_detection_capacity_revision": PUBLIC_RAW_DETECTION_CAPACITY_REVISION,
        "max_current_detections": PUBLIC_TRACK_MAX_CURRENT_DETECTIONS,
    }
    deployment = _self_hashed(
        PublicAssociationDeploymentBindingV2,
        deployment_payload,
        "deployment_binding_sha256",
    )
    target_color = _selector_color(
        training_key.target_selector_policy_input,
        expected=training_key.declared_target_attribute,
    )
    blocker_color = _selector_color(training_key.blocker_selector_policy_input, expected="red")
    task_spec_receipt = canonical_sha256(
        {
            "matched_key": training_key.matched_key,
            "target_selector_policy_input": training_key.target_selector_policy_input,
            "declared_target_attribute": training_key.declared_target_attribute,
            "training_manifest_sha256": training_manifest.manifest_sha256,
        }
    )
    attribute_payload: dict[str, Any] = {
        "schema_version": "PublicDeclaredTargetAttributeBindingV4",
        "declared_target_attribute": target_color,
        "public_target_selector": f"visual_color={target_color}",
        "selector_source_implementation_sha256": training_manifest.selection_implementation[
            "sha256"
        ],
        "task_spec_public_receipt_sha256": task_spec_receipt,
    }
    attribute_binding = _self_hashed(
        PublicDeclaredTargetAttributeBindingV4,
        attribute_payload,
        "binding_sha256",
    )

    public_captures: list[PublicAssociationCaptureV2] = []
    previous_receipt: str | None = None
    for index, raw_capture in enumerate(captures):
        raw_step = chain.steps[index]
        raw_observation = raw_step.observation
        if raw_observation.capture_receipt_sha256 != canonical_sha256(
            raw_capture.model_dump(mode="json")
        ):
            raise ValueError("V4 raw observation capture receipt differs")
        if (
            raw_observation.captured_at_ns != raw_capture.timestamp_ns
            or raw_observation.rgb_uri != raw_capture.rgb_uri
            or raw_observation.depth_uri != raw_capture.depth_uri
            or raw_observation.rgb_sha256 != raw_capture.rgb_sha256
            or raw_observation.depth_sha256 != raw_capture.depth_sha256
        ):
            raise ValueError("V4 raw observation assets differ from capture")
        if (
            raw_capture.camera_frame != protocol.declared_camera_frame
            or raw_capture.world_frame != protocol.declared_world_frame
            or raw_capture.position_units != protocol.metric_units
            or raw_capture.camera_to_world_row_major != protocol.camera_to_world_row_major
        ):
            raise ValueError("V4 raw capture protocol changed within the chain")
        if index:
            prior_receipts = chain.steps[index - 1].physical_receipts
            if len(prior_receipts) != 1:
                raise ValueError("V4 prior step does not contain one physical receipt")
            prior = prior_receipts[0]
            expected_skill = LastPhysicallyExecutedPublicSkillV2(
                skill_name=prior.executed_skill,
                started_at_ns=prior.started_at_ns,
                completed_at_ns=prior.completed_at_ns,
            )
            if raw_capture.last_physically_executed_public_skill != expected_skill:
                raise ValueError("V4 raw last skill differs from prior physical receipt")
        elif raw_capture.last_physically_executed_public_skill is not None:
            raise ValueError("V4 first raw capture unexpectedly names a prior skill")
        samples = raw_capture.proprioception_interval
        timestamps = [item.timestamp_ns for item in samples]
        expected_start = (
            raw_capture.timestamp_ns if index == 0 else captures[index - 1].timestamp_ns
        )
        interval_payload = {
            "schema_version": "PublicProprioceptionIntervalV2",
            "start_capture_timestamp_ns": expected_start,
            "end_capture_timestamp_ns": raw_capture.timestamp_ns,
            "expected_sample_timestamps_ns": timestamps,
            "samples": [item.model_dump(mode="json") for item in samples],
            "samples_sha256": canonical_sha256([item.model_dump(mode="json") for item in samples]),
        }
        capture_payload: dict[str, Any] = {
            "schema_version": "PublicAssociationCaptureV2",
            "timestamp_ns": raw_capture.timestamp_ns,
            "protocol": protocol.model_dump(mode="json"),
            "previous_capture_receipt_sha256": previous_receipt,
            "detections": [item.model_dump(mode="json") for item in raw_capture.detections],
            "proprioception_interval": interval_payload,
            "last_physically_executed_public_skill": (
                raw_capture.last_physically_executed_public_skill.model_dump(mode="json")
                if raw_capture.last_physically_executed_public_skill is not None
                else None
            ),
        }
        capture = _self_hashed(
            PublicAssociationCaptureV2,
            capture_payload,
            "capture_receipt_sha256",
        )
        public_captures.append(capture)
        previous_receipt = capture.capture_receipt_sha256

    full_journal = _journal_for(
        public_captures,
        protocol_sha256=protocol_sha256,
        capture_source_sha256=capture_source_implementation_sha256,
    )
    full_session = _session_for(full_journal, deployment)
    associator = PublicTrackAssociatorV2(
        expected_deployment=deployment,
        expected_deployment_binding_sha256=deployment.deployment_binding_sha256,
        expected_journal=full_journal,
        expected_session_receipt=full_session,
        expected_session_receipt_sha256=full_session.session_receipt_sha256,
    )
    frames: list[PublicAssociationReplayFrameV4] = []
    steps: list[PathBlockedPhysicalStepEvidenceV4] = []
    for index, capture in enumerate(public_captures):
        associated = associator.associate(capture)
        frame = PublicAssociationReplayFrameV4(
            capture=capture,
            associated_tracks=associated,
            associated_tracks_sha256=canonical_sha256(
                [item.model_dump(mode="json") for item in associated]
            ),
        )
        frames.append(frame)
        tracks = associated_tracks_to_perception_tracks_v4(associated)
        candidates = build_public_track_candidates_v4(
            tracks,
            declared_target_attribute=chain.declared_target_attribute,
        )
        raw_step = chain.steps[index]
        raw_observation = raw_step.observation
        observation_payload = {
            "schema_version": "PathBlockedPublicObservationV4",
            "observation_id": raw_observation.observation_id,
            "captured_at_ns": capture.timestamp_ns,
            "source": "PUBLIC_RGBD",
            "fresh": True,
            "rgb_uri": raw_observation.rgb_uri,
            "depth_uri": raw_observation.depth_uri,
            "rgb_sha256": raw_observation.rgb_sha256,
            "depth_sha256": raw_observation.depth_sha256,
            "capture_receipt_sha256": capture.capture_receipt_sha256,
            "public_track_associator_revision": "PublicTrackAssociatorV2",
            "camera_frame": protocol.declared_camera_frame,
            "position_units": protocol.metric_units,
            "calibration_sha256": protocol.calibration_sha256,
            "association_history": [item.model_dump(mode="json") for item in frames],
            "perception_tracks": [item.model_dump(mode="json") for item in tracks],
            "declared_target_attribute": chain.declared_target_attribute,
            "candidate_payload": canonical_candidate_payload_v4(candidates),
            "candidate_payload_sha256": canonical_candidate_sha256_v4(candidates),
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "task_target_track_id_used_for_candidates": False,
        }
        prefix_journal = _journal_for(
            public_captures[: index + 1],
            protocol_sha256=protocol_sha256,
            capture_source_sha256=capture_source_implementation_sha256,
        )
        prefix_session = _session_for(prefix_journal, deployment)
        observation = load_public_observation_v4(
            observation_payload,
            expected_deployment=deployment,
            expected_deployment_binding_sha256=deployment.deployment_binding_sha256,
            expected_journal=prefix_journal,
            expected_session_receipt=prefix_session,
            expected_session_receipt_sha256=prefix_session.session_receipt_sha256,
            expected_attribute_binding=attribute_binding,
            expected_attribute_binding_sha256=attribute_binding.binding_sha256,
        )
        expected_color = blocker_color if index <= 4 else target_color if index >= 6 else None
        if raw_step.scripted_public_selector_color != expected_color:
            raise ValueError("V4 raw step public selector differs from frozen key")
        selected = (
            _public_selector_track_id(associated, color=expected_color)
            if expected_color is not None
            else None
        )
        steps.append(
            PathBlockedPhysicalStepEvidenceV4(
                schema_version="PathBlockedPhysicalStepEvidenceV4",
                decision_index=index,
                observation=observation,
                expected_proprioception_journal=prefix_journal,
                expected_association_session_receipt=prefix_session,
                expected_association_session_receipt_sha256=(prefix_session.session_receipt_sha256),
                public_blocker_track_id=selected if index <= 4 else None,
                public_task_target_track_id=selected if index >= 6 else None,
                destination_cell_label=raw_step.destination_cell_label,
                physical_receipts=raw_step.physical_receipts,
                label_source="PUBLIC_RGBD_PHYSICAL_SUPERVISION",
                teacher_used=False,
                privileged_truth_policy_input=False,
            )
        )
    if not associator.journal_complete:
        raise ValueError("V4 host replay did not consume the complete capture journal")
    payload = chain.model_dump(mode="json", exclude={"schema_version", "steps"})
    return M2CPathBlockedProbeChainV4(
        **payload,
        schema_version="M2CPathBlockedProbeChainV4",
        expected_association_deployment=deployment,
        expected_association_deployment_sha256=deployment.deployment_binding_sha256,
        expected_declared_attribute_binding=attribute_binding,
        expected_declared_attribute_binding_sha256=canonical_attribute_binding_sha256_v4(
            attribute_binding
        ),
        steps=steps,
    )


class M2CPathBlockedPhysicalChainEvidenceV4(M2CPathBlockedProbeChainV4):
    schema_version: Literal["M2CPathBlockedPhysicalChainEvidenceV4"]
    v4_training_manifest_ref: FrozenManifestRefV4
    s6_exclusion_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_uri: str
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def package_probe_chain_v4(
    raw_chain: Mapping[str, Any],
    *,
    training_manifest: V4TrainingKeyManifest,
    s6_manifest: FrozenS6ExclusionManifestV2,
    runtime_registry_sha256: str,
    source_evidence_uri: str,
    source_evidence_sha256: str,
) -> M2CPathBlockedPhysicalChainEvidenceV4:
    probe = M2CPathBlockedProbeChainV4.model_validate(raw_chain)
    payload = probe.model_dump(mode="json", exclude={"schema_version"})
    return M2CPathBlockedPhysicalChainEvidenceV4(
        **payload,
        schema_version="M2CPathBlockedPhysicalChainEvidenceV4",
        v4_training_manifest_ref=FrozenManifestRefV4(
            manifest_key=v4_manifest_key(training_manifest),
            manifest_file_sha256=v4_manifest_file_sha256(training_manifest),
            manifest_sha256=training_manifest.manifest_sha256,
        ),
        s6_exclusion_manifest_sha256=canonical_sha256(s6_manifest.model_dump(mode="json")),
        runtime_registry_sha256=runtime_registry_sha256,
        source_evidence_uri=source_evidence_uri,
        source_evidence_sha256=source_evidence_sha256,
    )


class PathBlockedEvidenceValidationV4(StrictModel):
    schema_version: Literal["PathBlockedEvidenceValidationV4"] = "PathBlockedEvidenceValidationV4"
    status: Literal["PASS_TRAIN", "EXCLUDED", "INVALID_SCHEMA"]
    episode_id: str
    physical_evidence_valid: bool
    model_training_eligible: bool
    steps_validated: int = Field(ge=0)
    exclusion_reasons: list[str] = Field(default_factory=list)


class M2CPathBlockedSupervisedStepV4(StrictModel):
    schema_version: Literal["M2CPathBlockedSupervisedStepV4"] = "M2CPathBlockedSupervisedStepV4"
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"] = "M2C_Q012_V4"
    candidate_contract_revision: Literal["PublicTrackCandidateV4"] = "PublicTrackCandidateV4"
    sample_id: str
    episode_id: str
    decision_index: int = Field(ge=0, le=7)
    split: Literal["train"]
    split_group: str
    matched_key: str
    observation: PathBlockedPublicObservationV4
    model_label: CoarseIntentV2
    skill_label_index: int = Field(ge=0)
    pointer_class_index: int = Field(ge=0, le=NONE_POINTER_CLASS)
    destination_class_index: int = Field(ge=0, le=NONE_DESTINATION_CLASS)
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_source: Literal["EXECUTED_PUBLIC_PHYSICAL_CHAIN"] = "EXECUTED_PUBLIC_PHYSICAL_CHAIN"
    skill_provenance: Literal["MODEL"] = "MODEL"
    target_provenance: Literal["MODEL", "NONE"]
    destination_provenance: Literal["MODEL", "NONE"]
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    model_training_eligible: Literal[True] = True


class PathBlockedSupervisedDatasetV4(StrictModel):
    schema_version: Literal["PathBlockedSupervisedDatasetV4"] = "PathBlockedSupervisedDatasetV4"
    status: Literal["PASS", "EMPTY"]
    samples: list[M2CPathBlockedSupervisedStepV4]
    validation: PathBlockedEvidenceValidationV4
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    checkpoint_path: None = None
    checkpoint_sha256: None = None


def _candidate_slots(observation: PathBlockedPublicObservationV4) -> list[str | None]:
    return [
        *[candidate.track_id for candidate in observation.candidate_payload.candidates],
        *([None] * (8 - len(observation.candidate_payload.candidates))),
    ]


def _pointer(track_id: str | None, observation: PathBlockedPublicObservationV4) -> int | None:
    if track_id is None:
        return NONE_POINTER_CLASS
    try:
        return _candidate_slots(observation).index(track_id)
    except ValueError:
        return None


def _destination(value: str | None) -> int | None:
    if value is None:
        return NONE_DESTINATION_CLASS
    try:
        return REGISTERED_DESTINATION_CELLS.index(value)
    except ValueError:
        return None


def validate_path_blocked_physical_evidence_v4(
    raw: M2CPathBlockedPhysicalChainEvidenceV4 | Mapping[str, Any],
    *,
    training_manifest: V4TrainingKeyManifest | Mapping[str, Any],
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
) -> PathBlockedEvidenceValidationV4:
    try:
        evidence = (
            raw
            if isinstance(raw, M2CPathBlockedPhysicalChainEvidenceV4)
            else M2CPathBlockedPhysicalChainEvidenceV4.model_validate(raw)
        )
        manifest = (
            training_manifest
            if isinstance(
                training_manifest,
                (M2CS4V4TrainingKeyManifestV1, M2CS4V4TrainingKeyExtensionManifestV1),
            )
            else validate_v4_training_manifest_payload(training_manifest)
        )
        s6 = (
            s6_manifest
            if isinstance(s6_manifest, FrozenS6ExclusionManifestV2)
            else FrozenS6ExclusionManifestV2.model_validate(s6_manifest)
        )
    except (ValidationError, ValueError) as error:
        episode = str(raw.get("episode_id", "UNKNOWN")) if isinstance(raw, Mapping) else "UNKNOWN"
        error_types = (
            [f"SCHEMA_INVALID:{item['type']}" for item in error.errors(include_url=False)]
            if isinstance(error, ValidationError)
            else ["SCHEMA_INVALID:VALUE_ERROR"]
        )
        return PathBlockedEvidenceValidationV4(
            status="INVALID_SCHEMA",
            episode_id=episode,
            physical_evidence_valid=False,
            model_training_eligible=False,
            steps_validated=0,
            exclusion_reasons=error_types,
        )
    reasons: list[str] = []

    def reject(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    keys = [item for item in manifest.training_keys if item.matched_key == evidence.matched_key]
    if (
        evidence.v4_training_manifest_ref.manifest_file_sha256 != v4_manifest_file_sha256(manifest)
        or evidence.v4_training_manifest_ref.manifest_key != v4_manifest_key(manifest)
        or evidence.v4_training_manifest_ref.manifest_sha256 != manifest.manifest_sha256
    ):
        reject("V4_TRAIN_MANIFEST_BINDING_MISMATCH")
    if evidence.s6_exclusion_manifest_sha256 != canonical_sha256(s6.model_dump(mode="json")):
        reject("S6_EXCLUSION_MANIFEST_BINDING_MISMATCH")
    if len(keys) != 1:
        reject("V4_TRAIN_KEY_NOT_EXACTLY_ONCE")
    else:
        key = keys[0]
        if (
            evidence.scene_seed,
            evidence.failure_seed,
            evidence.split,
            evidence.declared_target_attribute,
            evidence.sdf_sha256,
            evidence.supervision_sha256,
        ) != (
            key.scene_seed,
            key.failure_seed,
            key.split,
            key.declared_target_attribute,
            key.sdf_sha256,
            key.supervision_sha256,
        ):
            reject("V4_TRAIN_KEY_IDENTITY_MISMATCH")
    if evidence.scene_seed in V4_QA_SCENE_SEEDS or any(
        item.scene_seed == evidence.scene_seed or item.matched_key == evidence.matched_key
        for item in s6.keys
    ):
        reject("HELD_OUT_IDENTITY_EXCLUDED")
    if not evidence.final_task_success:
        reject("FINAL_TASK_NOT_SUCCESSFUL")
    if len(evidence.steps) != 8:
        reject("PHYSICAL_CHAIN_LENGTH_NOT_EIGHT")
    seen_observations: set[str] = set()
    seen_captures: set[str] = set()
    seen_receipts: set[str] = set()
    freshness_floor = evidence.failure_observed_at_ns
    chosen_destination: str | None = None
    for position, step in enumerate(evidence.steps):
        prefix = f"STEP_{position}:"
        if step.decision_index != position:
            reject(prefix + "NON_CANONICAL_DECISION_INDEX")
        observation = step.observation
        try:
            load_public_observation_v4(
                observation.model_dump(mode="json"),
                expected_deployment=evidence.expected_association_deployment,
                expected_deployment_binding_sha256=(
                    evidence.expected_association_deployment_sha256
                ),
                expected_journal=step.expected_proprioception_journal,
                expected_session_receipt=step.expected_association_session_receipt,
                expected_session_receipt_sha256=(step.expected_association_session_receipt_sha256),
                expected_attribute_binding=evidence.expected_declared_attribute_binding,
                expected_attribute_binding_sha256=(
                    evidence.expected_declared_attribute_binding_sha256
                ),
            )
        except (ValidationError, ValueError):
            reject(prefix + "PUBLIC_ASSOCIATION_REPLAY_INVALID")
        if observation.declared_target_attribute != evidence.declared_target_attribute:
            reject(prefix + "DECLARED_ATTRIBUTE_MISMATCH")
        if observation.observation_id in seen_observations:
            reject(prefix + "PUBLIC_OBSERVATION_REUSED")
        seen_observations.add(observation.observation_id)
        if observation.capture_receipt_sha256 in seen_captures:
            reject(prefix + "PUBLIC_CAPTURE_REUSED")
        seen_captures.add(observation.capture_receipt_sha256)
        if observation.captured_at_ns <= freshness_floor:
            reject(prefix + "PUBLIC_OBSERVATION_NOT_FRESH")
        target = (
            step.public_blocker_track_id
            if position <= 4
            else step.public_task_target_track_id
            if position >= 6
            else None
        )
        if (position <= 4 or position >= 6) and target is None:
            reject(prefix + "PUBLIC_TARGET_TRACK_MISSING")
        if _pointer(target, observation) is None:
            reject(prefix + "PUBLIC_TARGET_OUTSIDE_V4_K8")
        if position in {2, 3}:
            if step.destination_cell_label not in REGISTERED_DESTINATION_CELLS:
                reject(prefix + "DESTINATION_CELL_NOT_REGISTERED")
            elif chosen_destination is None:
                chosen_destination = step.destination_cell_label
            elif chosen_destination != step.destination_cell_label:
                reject(prefix + "MOVE_PLACE_DESTINATION_DISAGREE")
        elif step.destination_cell_label is not None:
            reject(prefix + "DESTINATION_CELL_NOT_APPLICABLE")
        if len(step.physical_receipts) != 1:
            reject(prefix + "PHYSICAL_RECEIPT_COUNT_NOT_ONE")
        for receipt in step.physical_receipts:
            if receipt.receipt_sha256 in seen_receipts:
                reject(prefix + "PHYSICAL_RECEIPT_REUSED")
            seen_receipts.add(receipt.receipt_sha256)
            if receipt.executed_skill != EXPECTED_PATH_BLOCKED_CHAIN[position]:
                reject(prefix + "PHYSICAL_SKILL_MISMATCH")
            if (
                not receipt.physically_executed
                or receipt.started_at_ns <= observation.captured_at_ns
                or receipt.completed_at_ns <= receipt.started_at_ns
            ):
                reject(prefix + "PHYSICAL_EXECUTION_INVALID")
            for gate in (
                "schema_gate",
                "stale_track_gate",
                "frame_unit_gate",
                "ik_gate",
                "collision_gate",
                "controller_gate",
                "safety_gate",
            ):
                if getattr(receipt, gate) != "PASS":
                    reject(prefix + gate.upper() + "_NOT_PASSING")
            if receipt.collision_or_safety_violation:
                reject(prefix + "SAFETY_KILL_RULE")
            freshness_floor = max(freshness_floor, receipt.completed_at_ns)
    valid = not reasons
    return PathBlockedEvidenceValidationV4(
        status="PASS_TRAIN" if valid else "EXCLUDED",
        episode_id=evidence.episode_id,
        physical_evidence_valid=valid,
        model_training_eligible=valid,
        steps_validated=len(evidence.steps),
        exclusion_reasons=reasons,
    )


def build_path_blocked_supervised_dataset_v4(
    evidence: M2CPathBlockedPhysicalChainEvidenceV4,
    *,
    training_manifest: V4TrainingKeyManifest,
    s6_manifest: FrozenS6ExclusionManifestV2,
) -> PathBlockedSupervisedDatasetV4:
    validation = validate_path_blocked_physical_evidence_v4(
        evidence,
        training_manifest=training_manifest,
        s6_manifest=s6_manifest,
    )
    if not validation.model_training_eligible:
        return PathBlockedSupervisedDatasetV4(
            status="EMPTY",
            samples=[],
            validation=validation,
            dataset_sha256=hashlib.sha256(b"").hexdigest(),
        )
    samples: list[M2CPathBlockedSupervisedStepV4] = []
    for step in evidence.steps:
        skill = EXPECTED_PATH_BLOCKED_CHAIN[step.decision_index]
        target = (
            step.public_blocker_track_id
            if step.decision_index <= 4
            else step.public_task_target_track_id
            if step.decision_index >= 6
            else None
        )
        pointer = _pointer(target, step.observation)
        destination = _destination(step.destination_cell_label)
        if pointer is None or destination is None:
            raise AssertionError("validated V4 label became unencodable")
        samples.append(
            M2CPathBlockedSupervisedStepV4(
                sample_id=f"{evidence.episode_id}:path-blocked-v4:{step.decision_index}",
                episode_id=evidence.episode_id,
                decision_index=step.decision_index,
                split="train",
                split_group=evidence.split_group,
                matched_key=evidence.matched_key,
                observation=step.observation,
                model_label=CoarseIntentV2(
                    skill_type=skill,
                    target_track_id=target,
                    grasp_family="top_down" if skill in {"GRASP", "REGRASP"} else "unknown",
                    recovery_mode="path_blocked",
                    reobserve_flag=skill == "REOBSERVE",
                    destination_cell=step.destination_cell_label,
                    failure_type_aux=FailureType.PATH_BLOCKED,
                ),
                skill_label_index=M2C_Q012_V4_SKILL_LABELS.index(skill),
                pointer_class_index=pointer,
                destination_class_index=destination,
                source_evidence_sha256=evidence.source_evidence_sha256,
                physical_receipt_sha256=step.physical_receipts[0].receipt_sha256,
                target_provenance="NONE" if step.decision_index == 5 else "MODEL",
                destination_provenance="MODEL" if step.decision_index in {2, 3} else "NONE",
            )
        )
    encoded = "".join(item.model_dump_json(exclude_none=False) + "\n" for item in samples).encode()
    return PathBlockedSupervisedDatasetV4(
        status="PASS",
        samples=samples,
        validation=validation,
        dataset_sha256=hashlib.sha256(encoded).hexdigest(),
    )
