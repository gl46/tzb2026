"""ADR-0021 TRAIN-only PATH_BLOCKED collection contracts.

V3 is deliberately a separate evidence family.  Nothing in this module
accepts, upgrades, or reinterprets a V2 observation, manifest, episode, or
supervised row.  Candidate slots are independently reconstructed from the
fresh public tracks and the TaskSpec-declared attribute token on the host.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV2,
    DestinationCellV2,
    FailureType,
    PerceptionTrackV1,
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
from xh_agent.policy.qrm_lite.public_tracks_v3 import (
    build_public_track_candidates_v3,
    canonical_candidate_payload_v3,
    canonical_candidate_sha256_v3,
)


M2C_Q012_V3_SKILL_LABELS = M2C_Q012_V2_SKILL_LABELS
V3_MANIFEST_SCHEMA = "M2CS4V3TrainingKeyManifestV1"
V3_MANIFEST_STATUS = "FROZEN_TRAIN_ONLY_BEFORE_ANY_V3_COLLECTION"
V3_MANIFEST_KEY = "M2C_S4_V3_FROZEN_TRAIN_KEYS"
V3_MANIFEST_FILE_SHA256 = "b5a2da566f4086724e99cea1664aeeac3b91344a68b72be84bcf6c5d0ddad65c"
V3_MANIFEST_CONTENT_SHA256 = "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
V2_TRAIN_SMOKE_MANIFEST_SHA256 = "ca2162a898853ee04600aaf9246c121ac0604754638e497d1824b159c161fd94"
V4_MANIFEST_SHA256 = "4e78c044b68b11c1d871ecb90e65c7e2dfc616c8971abb89cb9969d2d48f738b"
S6_MANIFEST_SHA256 = "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
V4_QA_SCENE_SEEDS = frozenset({9038, 9057, 9077})
V4_QA_MATCHED_KEYS = frozenset(
    {
        "m2c-headroom-v4-604aecfc01390011adfc3a39233fdd96cc318605ec3afd2873c73b4ad1f1d297",
        "m2c-headroom-v4-1cad17ac5f6796634510abb8250ff2e7a36c0f9e5735068fd089ea59e5c97258",
        "m2c-headroom-v4-361948b69e40fb892ad46d49ffa625574bc56a8772b4c04bff008ab6918e49f5",
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class M2CS4V3TrainingKeyV1(StrictModel):
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
    candidate_contract_revision: Literal["PublicTrackCandidateV3"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"]
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
    matched_key: str = Field(pattern=r"^m2c-s4-v3-train-[0-9a-f]{64}$")

    @model_validator(mode="after")
    def public_selector_and_contract_are_exact(self) -> "M2CS4V3TrainingKeyV1":
        if "visual_color=yellow" not in self.target_selector_policy_input:
            raise ValueError("V3 TaskSpec selector does not declare yellow")
        if "visual_color=red" not in self.blocker_selector_policy_input:
            raise ValueError("V3 blocker selector is not public red")
        return self


class M2CS4V3TrainingKeyManifestV1(StrictModel):
    schema_version: Literal["M2CS4V3TrainingKeyManifestV1"]
    status: Literal["FROZEN_TRAIN_ONLY_BEFORE_ANY_V3_COLLECTION"]
    written_date_asia_shanghai: str
    train_only: Literal[True]
    candidate_contract_revision: Literal["PublicTrackCandidateV3"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"]
    candidate_count_bound: Literal[8]
    pointer_class_count: Literal[9]
    recapture_policy: Literal["NONE"]
    declared_target_attribute: Literal["yellow"]
    selection_uses_rollout_outcomes: Literal[False]
    any_v3_collection_observed_before_freeze: Literal[False]
    collection_executed: Literal[False]
    training_executed: Literal[False]
    smoke_collection_authorized: Literal[False]
    evaluation_collection_authorized: Literal[False]
    candidate_implementation: dict[str, str]
    selection_implementation: dict[str, Any]
    selection_protocol: dict[str, Any]
    source_bindings: dict[str, str]
    exclusion_contract: dict[str, Any]
    exclusions: dict[str, Any]
    layout_contract: dict[str, Any]
    training_key_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_keys: list[M2CS4V3TrainingKeyV1] = Field(min_length=36, max_length=36)
    physical_prerequisite_smoke_keys: list[Any] = Field(max_length=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def frozen_identity_is_exact(self) -> "M2CS4V3TrainingKeyManifestV1":
        if self.manifest_sha256 != V3_MANIFEST_CONTENT_SHA256:
            raise ValueError("V3 embedded manifest identity is not frozen")
        payload = self.model_dump(mode="json")
        payload.pop("manifest_sha256")
        if canonical_sha256(payload) != self.manifest_sha256:
            raise ValueError("V3 embedded manifest SHA-256 mismatch")
        if (
            canonical_sha256([item.model_dump(mode="json") for item in self.training_keys])
            != self.training_key_digest
        ):
            raise ValueError("V3 training-key digest mismatch")
        keys = [item.matched_key for item in self.training_keys]
        scenes = [item.scene_seed for item in self.training_keys]
        failures = [item.failure_seed for item in self.training_keys]
        if any(len(values) != len(set(values)) for values in (keys, scenes, failures)):
            raise ValueError("V3 TRAIN manifest repeats an identity")
        if (
            self.source_bindings.get("configs/m2c_s4_training_keys.json")
            != V2_TRAIN_SMOKE_MANIFEST_SHA256
        ):
            raise ValueError("V3 manifest does not bind the excluded V2 keys")
        if self.source_bindings.get("configs/m2c_headroom_domain_v4.json") != V4_MANIFEST_SHA256:
            raise ValueError("V3 manifest does not bind the excluded V4 keys")
        if self.source_bindings.get("configs/m2c_s6_evaluation_keys.json") != S6_MANIFEST_SHA256:
            raise ValueError("V3 manifest does not bind the excluded S6 keys")
        required = {
            "old_v2_train_and_smoke": True,
            "v4_q_a": True,
            "all_s6_evaluation": True,
        }
        if any(self.exclusion_contract.get(key) is not value for key, value in required.items()):
            raise ValueError("V3 exclusion contract is incomplete")
        return self


class FrozenManifestRefV3(StrictModel):
    schema_version: Literal["FrozenManifestRefV3"] = "FrozenManifestRefV3"
    manifest_key: Literal["M2C_S4_V3_FROZEN_TRAIN_KEYS"] = V3_MANIFEST_KEY
    manifest_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicTrackCandidateEntryV3(StrictModel):
    track_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    pose_present: Literal[True]
    role: Literal["ROLE_TARGET_ATTRIBUTE_MATCH", "ROLE_MANIPULABLE_OTHER"]


class PublicTrackCandidatePayloadV3(StrictModel):
    schema_version: Literal["PublicTrackCandidateV3"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"]
    candidate_count_bound: Literal[8]
    recapture_policy: Literal["NONE"]
    candidates: list[PublicTrackCandidateEntryV3] = Field(max_length=8)
    valid_mask: list[bool] = Field(min_length=8, max_length=8)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    task_target_track_id_used: Literal[False]

    @model_validator(mode="after")
    def mask_is_prefix_and_ids_unique(self) -> "PublicTrackCandidatePayloadV3":
        if self.valid_mask != [True] * len(self.candidates) + [False] * (8 - len(self.candidates)):
            raise ValueError("V3 candidate mask does not match candidates")
        ids = [item.track_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("V3 candidate payload repeats a track")
        return self


class PathBlockedPublicObservationV3(StrictModel):
    schema_version: Literal["PathBlockedPublicObservationV3"]
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    source: Literal["PUBLIC_RGBD"]
    fresh: Literal[True]
    rgb_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    depth_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    perception_tracks: list[PerceptionTrackV1] = Field(min_length=1)
    declared_target_attribute: Literal["yellow"]
    candidate_payload: PublicTrackCandidatePayloadV3
    candidate_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    task_target_track_id_used_for_candidates: Literal[False]

    @model_validator(mode="after")
    def asset_uris_do_not_escape(self) -> "PathBlockedPublicObservationV3":
        for uri in (self.rgb_uri, self.depth_uri):
            relative = uri.removeprefix("dataset://")
            if relative.startswith("/") or ".." in relative.split("/"):
                raise ValueError("public asset URI escapes evidence root")
        return self


class PathBlockedPhysicalStepEvidenceV3(StrictModel):
    schema_version: Literal["PathBlockedPhysicalStepEvidenceV3"]
    decision_index: int = Field(ge=0, le=7)
    observation: PathBlockedPublicObservationV3
    public_blocker_track_id: str | None = None
    public_task_target_track_id: str | None = None
    destination_cell_label: DestinationCellV2 | None = None
    physical_receipts: list[PathBlockedPhysicalSkillReceiptV2]
    label_source: Literal["PUBLIC_RGBD_PHYSICAL_SUPERVISION"]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class M2CPathBlockedProbeChainV3(StrictModel):
    schema_version: Literal["M2CPathBlockedProbeChainV3"]
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
    candidate_contract_revision: Literal["PublicTrackCandidateV3"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"]
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_observed_at_ns: int = Field(gt=0)
    final_task_success: bool
    steps: list[PathBlockedPhysicalStepEvidenceV3]
    model_rollout: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class M2CPathBlockedPhysicalChainEvidenceV3(M2CPathBlockedProbeChainV3):
    schema_version: Literal["M2CPathBlockedPhysicalChainEvidenceV3"]
    v3_training_manifest_ref: FrozenManifestRefV3
    s6_exclusion_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_uri: str
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def package_probe_chain_v3(
    raw_chain: Mapping[str, Any],
    *,
    training_manifest: M2CS4V3TrainingKeyManifestV1,
    s6_manifest: FrozenS6ExclusionManifestV2,
    runtime_registry_sha256: str,
    source_evidence_uri: str,
    source_evidence_sha256: str,
) -> M2CPathBlockedPhysicalChainEvidenceV3:
    """Bind an already file/hash-verified untrusted probe to frozen V3 refs."""

    probe = M2CPathBlockedProbeChainV3.model_validate(raw_chain)
    probe_payload = probe.model_dump(mode="json")
    probe_payload.pop("schema_version")
    return M2CPathBlockedPhysicalChainEvidenceV3(
        **probe_payload,
        schema_version="M2CPathBlockedPhysicalChainEvidenceV3",
        v3_training_manifest_ref=FrozenManifestRefV3(
            manifest_file_sha256=V3_MANIFEST_FILE_SHA256,
            manifest_sha256=training_manifest.manifest_sha256,
        ),
        s6_exclusion_manifest_sha256=canonical_sha256(s6_manifest.model_dump(mode="json")),
        runtime_registry_sha256=runtime_registry_sha256,
        source_evidence_uri=source_evidence_uri,
        source_evidence_sha256=source_evidence_sha256,
    )


class PathBlockedEvidenceValidationV3(StrictModel):
    schema_version: Literal["PathBlockedEvidenceValidationV3"] = "PathBlockedEvidenceValidationV3"
    status: Literal["PASS_TRAIN", "EXCLUDED", "INVALID_SCHEMA"]
    episode_id: str
    physical_evidence_valid: bool
    model_training_eligible: bool
    steps_validated: int = Field(ge=0)
    exclusion_reasons: list[str] = Field(default_factory=list)


class M2CPathBlockedSupervisedStepV3(StrictModel):
    schema_version: Literal["M2CPathBlockedSupervisedStepV3"] = "M2CPathBlockedSupervisedStepV3"
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"] = "M2C_Q012_V3"
    candidate_contract_revision: Literal["PublicTrackCandidateV3"] = "PublicTrackCandidateV3"
    sample_id: str
    episode_id: str
    decision_index: int = Field(ge=0, le=7)
    split: Literal["train"]
    split_group: str
    matched_key: str
    observation: PathBlockedPublicObservationV3
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
    exclusion_reasons: list[Any] = Field(default_factory=list, max_length=0)


class PathBlockedSupervisedDatasetV3(StrictModel):
    schema_version: Literal["PathBlockedSupervisedDatasetV3"] = "PathBlockedSupervisedDatasetV3"
    status: Literal["PASS", "EMPTY"]
    samples: list[M2CPathBlockedSupervisedStepV3]
    validation: PathBlockedEvidenceValidationV3
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    checkpoint_path: None = None
    checkpoint_sha256: None = None


def load_v3_training_manifest(path: Path) -> M2CS4V3TrainingKeyManifestV1:
    if sha256_file(path) != V3_MANIFEST_FILE_SHA256:
        raise ValueError("V3 collection requires the exact frozen TRAIN manifest file")
    return M2CS4V3TrainingKeyManifestV1.model_validate_json(path.read_text(encoding="utf-8"))


def recompute_candidate_payload_v3(
    observation: PathBlockedPublicObservationV3,
) -> tuple[dict[str, object], str]:
    candidates = build_public_track_candidates_v3(
        observation.perception_tracks,
        declared_target_attribute=observation.declared_target_attribute,
    )
    return canonical_candidate_payload_v3(candidates), canonical_candidate_sha256_v3(candidates)


def _candidate_slots(observation: PathBlockedPublicObservationV3) -> list[str | None]:
    return [
        *[candidate.track_id for candidate in observation.candidate_payload.candidates],
        *([None] * (8 - len(observation.candidate_payload.candidates))),
    ]


def _pointer(track_id: str | None, observation: PathBlockedPublicObservationV3) -> int | None:
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


def validate_path_blocked_physical_evidence_v3(
    raw: M2CPathBlockedPhysicalChainEvidenceV3 | Mapping[str, Any],
    *,
    training_manifest: M2CS4V3TrainingKeyManifestV1 | Mapping[str, Any],
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
) -> PathBlockedEvidenceValidationV3:
    try:
        evidence = (
            raw
            if isinstance(raw, M2CPathBlockedPhysicalChainEvidenceV3)
            else M2CPathBlockedPhysicalChainEvidenceV3.model_validate(raw)
        )
        manifest = (
            training_manifest
            if isinstance(training_manifest, M2CS4V3TrainingKeyManifestV1)
            else M2CS4V3TrainingKeyManifestV1.model_validate(training_manifest)
        )
        s6 = (
            s6_manifest
            if isinstance(s6_manifest, FrozenS6ExclusionManifestV2)
            else FrozenS6ExclusionManifestV2.model_validate(s6_manifest)
        )
    except ValidationError as error:
        episode = str(raw.get("episode_id", "UNKNOWN")) if isinstance(raw, Mapping) else "UNKNOWN"
        return PathBlockedEvidenceValidationV3(
            status="INVALID_SCHEMA",
            episode_id=episode,
            physical_evidence_valid=False,
            model_training_eligible=False,
            steps_validated=0,
            exclusion_reasons=[
                f"SCHEMA_INVALID:{item['type']}" for item in error.errors(include_url=False)
            ],
        )
    reasons: list[str] = []

    def reject(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if (
        evidence.v3_training_manifest_ref.manifest_file_sha256 != V3_MANIFEST_FILE_SHA256
        or evidence.v3_training_manifest_ref.manifest_sha256 != manifest.manifest_sha256
    ):
        reject("V3_TRAIN_MANIFEST_BINDING_MISMATCH")
    if evidence.s6_exclusion_manifest_sha256 != canonical_sha256(s6.model_dump(mode="json")):
        reject("S6_EXCLUSION_MANIFEST_BINDING_MISMATCH")
    keys = [item for item in manifest.training_keys if item.matched_key == evidence.matched_key]
    if len(keys) != 1:
        reject("V3_TRAIN_KEY_NOT_EXACTLY_ONCE")
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
            reject("V3_TRAIN_KEY_IDENTITY_MISMATCH")
    if evidence.collection_role != "TRAIN" or evidence.split != "train":
        reject("NON_TRAIN_COLLECTION_FORBIDDEN")
    if evidence.scene_seed in V4_QA_SCENE_SEEDS or evidence.matched_key in V4_QA_MATCHED_KEYS:
        reject("V4_QA_IDENTITY_EXCLUDED")
    if any(
        item.scene_seed == evidence.scene_seed or item.matched_key == evidence.matched_key
        for item in s6.keys
    ):
        reject("S6_IDENTITY_EXCLUDED")
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
        if observation.declared_target_attribute != evidence.declared_target_attribute:
            reject(prefix + "DECLARED_ATTRIBUTE_MISMATCH")
        expected_payload, expected_sha = recompute_candidate_payload_v3(observation)
        if observation.candidate_payload.model_dump(mode="json") != expected_payload:
            reject(prefix + "V3_CANDIDATES_NOT_HOST_RECOMPUTABLE")
        if observation.candidate_payload_sha256 != expected_sha:
            reject(prefix + "V3_CANDIDATE_SHA256_MISMATCH")
        if not observation.candidate_payload.candidates:
            reject(prefix + "EMPTY_V3_CANDIDATE_LIST")
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
        if position <= 4 and target is None:
            reject(prefix + "PUBLIC_BLOCKER_TRACK_MISSING")
        if position >= 6 and target is None:
            reject(prefix + "PUBLIC_TASK_TARGET_TRACK_MISSING")
        if _pointer(target, observation) is None:
            reject(prefix + "PUBLIC_TARGET_OUTSIDE_V3_K8")
        destination_required = position in {2, 3}
        if destination_required:
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
            if (
                receipt.collision_or_safety_violation
                or receipt.teacher_used
                or receipt.privileged_truth_policy_input
            ):
                reject(prefix + "SAFETY_TEACHER_OR_TRUTH_KILL_RULE")
            freshness_floor = max(freshness_floor, receipt.completed_at_ns)
    valid = not reasons
    return PathBlockedEvidenceValidationV3(
        status="PASS_TRAIN" if valid else "EXCLUDED",
        episode_id=evidence.episode_id,
        physical_evidence_valid=valid,
        model_training_eligible=valid,
        steps_validated=len(evidence.steps),
        exclusion_reasons=reasons,
    )


def build_path_blocked_supervised_dataset_v3(
    evidence: M2CPathBlockedPhysicalChainEvidenceV3,
    *,
    training_manifest: M2CS4V3TrainingKeyManifestV1,
    s6_manifest: FrozenS6ExclusionManifestV2,
) -> PathBlockedSupervisedDatasetV3:
    validation = validate_path_blocked_physical_evidence_v3(
        evidence, training_manifest=training_manifest, s6_manifest=s6_manifest
    )
    if not validation.model_training_eligible:
        return PathBlockedSupervisedDatasetV3(
            status="EMPTY",
            samples=[],
            validation=validation,
            dataset_sha256=hashlib.sha256(b"").hexdigest(),
        )
    samples: list[M2CPathBlockedSupervisedStepV3] = []
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
            raise AssertionError("validated V3 label became unencodable")
        samples.append(
            M2CPathBlockedSupervisedStepV3(
                sample_id=f"{evidence.episode_id}:path-blocked-v3:{step.decision_index}",
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
                skill_label_index=M2C_Q012_V3_SKILL_LABELS.index(skill),
                pointer_class_index=pointer,
                destination_class_index=destination,
                source_evidence_sha256=evidence.source_evidence_sha256,
                physical_receipt_sha256=step.physical_receipts[0].receipt_sha256,
                target_provenance="NONE" if step.decision_index == 5 else "MODEL",
                destination_provenance="MODEL" if step.decision_index in {2, 3} else "NONE",
            )
        )
    encoded = "".join(item.model_dump_json(exclude_none=False) + "\n" for item in samples).encode()
    return PathBlockedSupervisedDatasetV3(
        status="PASS",
        samples=samples,
        validation=validation,
        dataset_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def raw_evidence_json_schema_v3() -> dict[str, Any]:
    return M2CPathBlockedPhysicalChainEvidenceV3.model_json_schema()


def supervised_step_json_schema_v3() -> dict[str, Any]:
    return M2CPathBlockedSupervisedStepV3.model_json_schema()
