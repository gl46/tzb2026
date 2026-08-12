"""Strict PATH_BLOCKED physical evidence and supervised-step contracts.

The builder in this module does not execute a policy, train a model, or infer
labels from simulator identity.  It accepts only a frozen, public-observation
physical chain collected for an explicitly allowed TRAIN or SMOKE key.  Each
accepted step is converted into one ``CoarseIntentV2`` supervised sample.

The older ``M2CPathBlockedRawEvidenceV1`` index is intentionally incompatible:
it contains Q-A keys and does not contain eight fresh observations and eight
independent physical receipts, so it cannot be upgraded by this builder.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xh_agent.policy.qrm_lite.coarse_policy import DEFAULT_SKILLS
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
    POINTER_SLOT_COUNT,
    REGISTERED_DESTINATION_CELLS,
)
from xh_agent.policy.qrm_lite.models_q012 import RECOVERY_SKILLS


M2C_Q012_V2_SKILL_LABELS: tuple[str, ...] = tuple(
    dict.fromkeys([*DEFAULT_SKILLS, *RECOVERY_SKILLS])
)
POINTER_CLASS_LABELS: tuple[str, ...] = tuple(
    [f"SLOT_{index}" for index in range(POINTER_SLOT_COUNT)] + ["NONE"]
)
DESTINATION_CLASS_LABELS: tuple[str, ...] = tuple([*REGISTERED_DESTINATION_CELLS, "NONE"])

V4_QA_SCENE_SEEDS: frozenset[int] = frozenset({9038, 9057, 9077})
V4_QA_MATCHED_KEYS: frozenset[str] = frozenset(
    {
        "m2c-headroom-v4-604aecfc01390011adfc3a39233fdd96cc318605ec3afd2873c73b4ad1f1d297",
        "m2c-headroom-v4-1cad17ac5f6796634510abb8250ff2e7a36c0f9e5735068fd089ea59e5c97258",
        "m2c-headroom-v4-361948b69e40fb892ad46d49ffa625574bc56a8772b4c04bff008ab6918e49f5",
    }
)

CollectionRole = Literal["TRAIN", "SMOKE"]
DatasetSplit = Literal["train", "val", "test"]
GateStatus = Literal["PASS", "REJECTED", "NOT_RUN"]
RuntimeParameterProvenance = Literal["MODEL", "NONE"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FrozenManifestRefV2(StrictModel):
    schema_version: Literal["FrozenManifestRefV2"] = "FrozenManifestRefV2"
    manifest_key: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PathBlockedCollectionKeyV2(StrictModel):
    schema_version: Literal["PathBlockedCollectionKeyV2"] = "PathBlockedCollectionKeyV2"
    collection_key: str = Field(min_length=1)
    collection_role: CollectionRole
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    split: DatasetSplit
    split_group: str = Field(min_length=1)


class FrozenPathBlockedCollectionManifestV2(StrictModel):
    """Allow-list frozen before physical TRAIN/SMOKE evidence collection."""

    schema_version: Literal["FrozenPathBlockedCollectionManifestV2"] = (
        "FrozenPathBlockedCollectionManifestV2"
    )
    manifest_key: str = Field(min_length=1)
    frozen_before_collection: Literal[True] = True
    runtime_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_labels: list[str]
    pointer_class_labels: list[str]
    destination_class_labels: list[str]
    keys: list[PathBlockedCollectionKeyV2] = Field(min_length=1)
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False

    @model_validator(mode="after")
    def frozen_layout_is_exact(self) -> "FrozenPathBlockedCollectionManifestV2":
        if self.skill_labels != list(M2C_Q012_V2_SKILL_LABELS):
            raise ValueError("collection manifest skill label order is not M2C_Q012_V2")
        if self.pointer_class_labels != list(POINTER_CLASS_LABELS):
            raise ValueError("collection manifest pointer label order is not frozen")
        if self.destination_class_labels != list(DESTINATION_CLASS_LABELS):
            raise ValueError("collection manifest destination label order is not frozen")
        identities = [item.collection_key for item in self.keys]
        if len(identities) != len(set(identities)):
            raise ValueError("collection manifest contains duplicate collection keys")
        matched_keys = [item.matched_key for item in self.keys]
        if len(matched_keys) != len(set(matched_keys)):
            raise ValueError("collection manifest contains duplicate matched keys")
        split_by_group: dict[str, set[str]] = {}
        for item in self.keys:
            split_by_group.setdefault(item.split_group, set()).add(item.split)
            if item.split_group != f"scene-{item.scene_seed}":
                raise ValueError("collection manifest split_group must group by scene")
        leaked = sorted(group for group, splits in split_by_group.items() if len(splits) != 1)
        if leaked:
            raise ValueError(f"collection manifest split-group leakage: {leaked}")
        if self.teacher_used:
            raise ValueError("collection manifest is not Teacher-free")
        if self.privileged_truth_policy_input:
            raise ValueError("collection manifest permits privileged policy input")
        return self


class FrozenS6EvaluationKeyV2(StrictModel):
    schema_version: Literal["FrozenS6EvaluationKeyV2"] = "FrozenS6EvaluationKeyV2"
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)


class FrozenS6ExclusionManifestV2(StrictModel):
    """Every pre-frozen S6 key and its grouped scene/failure identity."""

    schema_version: Literal["FrozenS6ExclusionManifestV2"] = "FrozenS6ExclusionManifestV2"
    manifest_key: str = Field(min_length=1)
    frozen_before_q_b_training: Literal[True] = True
    keys: list[FrozenS6EvaluationKeyV2] = Field(min_length=1)
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False

    @model_validator(mode="after")
    def keys_are_unique_and_public_only(self) -> "FrozenS6ExclusionManifestV2":
        identities = [item.matched_key for item in self.keys]
        if len(identities) != len(set(identities)):
            raise ValueError("S6 exclusion manifest contains duplicate matched keys")
        if self.teacher_used:
            raise ValueError("S6 exclusion manifest is not Teacher-free")
        if self.privileged_truth_policy_input:
            raise ValueError("S6 exclusion manifest permits privileged policy input")
        return self


class PathBlockedPublicObservationV2(StrictModel):
    """One fresh public RGB-D capture and its canonical K=8 track slots."""

    schema_version: Literal["PathBlockedPublicObservationV2"] = "PathBlockedPublicObservationV2"
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    source: Literal["PUBLIC_RGBD"] = "PUBLIC_RGBD"
    fresh: bool
    rgb_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    depth_uri: str = Field(pattern=r"^dataset://[^\s]+$")
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    perception_tracks: list[PerceptionTrackV1] = Field(min_length=1)
    canonical_slots: list[str | None] = Field(
        min_length=POINTER_SLOT_COUNT,
        max_length=POINTER_SLOT_COUNT,
    )
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False

    @model_validator(mode="after")
    def public_asset_uris_do_not_escape(self) -> "PathBlockedPublicObservationV2":
        for uri in (self.rgb_uri, self.depth_uri):
            relative = uri.removeprefix("dataset://")
            if relative.startswith("/") or ".." in relative.split("/"):
                raise ValueError("public asset URI escapes the evidence root")
        return self


class PhysicalActionProtocolV2(StrictModel):
    """Explicit protocol copied from the frozen runtime registry receipt."""

    schema_version: Literal["PhysicalActionProtocolV2"] = "PhysicalActionProtocolV2"
    coordinate_frame: str = Field(min_length=1)
    units: str = Field(min_length=1)
    dimensions: int = Field(ge=0)
    frequency_hz: float = Field(gt=0.0)
    normalization: str = Field(min_length=1)


class PathBlockedPhysicalSkillReceiptV2(StrictModel):
    schema_version: Literal["PathBlockedPhysicalSkillReceiptV2"] = (
        "PathBlockedPhysicalSkillReceiptV2"
    )
    receipt_id: str = Field(min_length=1)
    receipt_uri: str = Field(min_length=1)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_source: Literal["SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"] = (
        "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    )
    executed_skill: str = Field(min_length=1)
    physically_executed: bool
    started_at_ns: int = Field(gt=0)
    completed_at_ns: int = Field(gt=0)
    action_protocol: PhysicalActionProtocolV2
    execution_measurements: dict[str, Any] = Field(min_length=1)
    schema_gate: GateStatus
    stale_track_gate: GateStatus
    frame_unit_gate: GateStatus
    ik_gate: GateStatus
    collision_gate: GateStatus
    controller_gate: GateStatus
    safety_gate: GateStatus
    collision_or_safety_violation: bool = False
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False

    @model_validator(mode="after")
    def execution_measurements_are_finite_public_evidence(
        self,
    ) -> "PathBlockedPhysicalSkillReceiptV2":
        """Bind concrete execution evidence without accepting oracle identity."""

        forbidden_tokens = ("prim", "entity", "ground_truth", "sim_truth", "oracle")

        def validate(value: Any, *, path: str) -> None:
            if isinstance(value, bool) or value is None:
                return
            if isinstance(value, str):
                normalized_value = value.lower()
                if (
                    "/world/" in normalized_value
                    or any(token in normalized_value for token in forbidden_tokens)
                    or __import__("re").search(r"(?:^|[^a-z0-9])cylinder_[0-9]+", normalized_value)
                ):
                    raise ValueError(
                        f"oracle identity is forbidden in execution measurement value: {path}"
                    )
                if path.endswith("public_track_id") and not value.startswith("track-"):
                    raise ValueError(f"public track measurement is not a track-* ID: {path}")
                return
            if isinstance(value, (int, float)):
                if not __import__("math").isfinite(value):
                    raise ValueError(f"non-finite execution measurement: {path}")
                return
            if isinstance(value, Mapping):
                if not value:
                    raise ValueError(f"empty execution measurement object: {path}")
                for key, nested in value.items():
                    normalized = str(key).lower()
                    if any(token in normalized for token in forbidden_tokens):
                        raise ValueError(
                            f"oracle identity is forbidden in execution measurements: {path}.{key}"
                        )
                    validate(nested, path=f"{path}.{key}")
                return
            if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
                if not value:
                    raise ValueError(f"empty execution measurement sequence: {path}")
                for index, nested in enumerate(value):
                    validate(nested, path=f"{path}[{index}]")
                return
            raise ValueError(f"unsupported execution measurement type: {path}")

        validate(self.execution_measurements, path="execution_measurements")
        return self


class PathBlockedPhysicalStepEvidenceV2(StrictModel):
    schema_version: Literal["PathBlockedPhysicalStepEvidenceV2"] = (
        "PathBlockedPhysicalStepEvidenceV2"
    )
    decision_index: int = Field(ge=0, le=7)
    observation: PathBlockedPublicObservationV2
    public_blocker_track_id: str | None = None
    public_task_target_track_id: str | None = None
    destination_cell_label: DestinationCellV2 | None = None
    physical_receipts: list[PathBlockedPhysicalSkillReceiptV2]
    label_source: Literal["PUBLIC_RGBD_PHYSICAL_SUPERVISION"] = "PUBLIC_RGBD_PHYSICAL_SUPERVISION"
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False

    @model_validator(mode="after")
    def step_must_be_teacher_and_truth_free(self) -> "PathBlockedPhysicalStepEvidenceV2":
        if self.teacher_used or self.observation.teacher_used:
            raise ValueError("physical supervision step used a Teacher")
        if self.privileged_truth_policy_input or self.observation.privileged_truth_policy_input:
            raise ValueError("physical supervision step used privileged policy input")
        if any(receipt.teacher_used for receipt in self.physical_receipts):
            raise ValueError("physical receipt used a Teacher")
        if any(receipt.privileged_truth_policy_input for receipt in self.physical_receipts):
            raise ValueError("physical receipt used privileged policy input")
        return self


class M2CPathBlockedProbeChainV2(StrictModel):
    """Untrusted Isaac probe projection before host-owned hash binding.

    The temporary full-evidence schema literal and host-owned placeholder
    fields are accepted so already-derived probes can be packaged.  Their
    values are never trusted: :func:`package_probe_payload` overwrites every
    host-owned reference and digest from local files and frozen manifests.
    """

    schema_version: Literal[
        "M2CPathBlockedProbeChainV2",
        "M2CPathBlockedPhysicalChainEvidenceV2",
    ] = "M2CPathBlockedProbeChainV2"
    evidence_origin: Literal["ISAAC_PHYSICAL_INTEGRATION"] = "ISAAC_PHYSICAL_INTEGRATION"
    episode_id: str = Field(min_length=1)
    failure_type: Literal["PATH_BLOCKED"] = "PATH_BLOCKED"
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    split: DatasetSplit
    split_group: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    collection_role: CollectionRole
    collection_key: str = Field(min_length=1)
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_observed_at_ns: int = Field(gt=0)
    final_task_success: bool
    steps: list[PathBlockedPhysicalStepEvidenceV2]
    model_rollout: Literal[False] = False
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False

    # Transitional placeholders emitted by the derived probe.  The host
    # wrapper discards them and binds the checked local values instead.
    collection_manifest_ref: FrozenManifestRefV2 | None = None
    s6_exclusion_manifest_ref: FrozenManifestRefV2 | None = None
    runtime_registry_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    source_evidence_uri: str | None = None
    source_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def probe_must_be_teacher_and_truth_free(self) -> "M2CPathBlockedProbeChainV2":
        if self.teacher_used:
            raise ValueError("probe chain used a Teacher")
        if self.privileged_truth_policy_input:
            raise ValueError("probe chain used privileged policy input")
        return self


class M2CPathBlockedPhysicalChainEvidenceV2(StrictModel):
    """Raw episode contract the physical collection probe must emit."""

    schema_version: Literal["M2CPathBlockedPhysicalChainEvidenceV2"] = (
        "M2CPathBlockedPhysicalChainEvidenceV2"
    )
    evidence_origin: Literal["ISAAC_PHYSICAL_INTEGRATION"] = "ISAAC_PHYSICAL_INTEGRATION"
    episode_id: str = Field(min_length=1)
    failure_type: Literal["PATH_BLOCKED"] = "PATH_BLOCKED"
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    split: DatasetSplit
    split_group: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    collection_role: CollectionRole
    collection_key: str = Field(min_length=1)
    collection_manifest_ref: FrozenManifestRefV2
    s6_exclusion_manifest_ref: FrozenManifestRefV2
    runtime_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_uri: str = Field(min_length=1)
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_observed_at_ns: int = Field(gt=0)
    final_task_success: bool
    steps: list[PathBlockedPhysicalStepEvidenceV2]
    model_rollout: Literal[False] = False
    teacher_used: bool = False
    privileged_truth_policy_input: bool = False


class PathBlockedEvidenceValidationV2(StrictModel):
    schema_version: Literal["PathBlockedEvidenceValidationV2"] = "PathBlockedEvidenceValidationV2"
    status: Literal["PASS_TRAIN", "PASS_SMOKE", "EXCLUDED", "INVALID_SCHEMA"]
    episode_id: str
    physical_evidence_valid: bool
    model_training_eligible: bool
    steps_validated: int = Field(ge=0)
    exclusion_reasons: list[str] = Field(default_factory=list)


class M2CPathBlockedSupervisedStepV2(StrictModel):
    """One Qwen/Q0/Q1/Q2-compatible coarse supervision record."""

    schema_version: Literal["M2CPathBlockedSupervisedStepV2"] = "M2CPathBlockedSupervisedStepV2"
    sample_id: str
    episode_id: str
    decision_index: int = Field(ge=0, le=7)
    split: DatasetSplit
    split_group: str
    matched_key: str
    observation: PathBlockedPublicObservationV2
    model_label: CoarseIntentV2
    skill_label_index: int = Field(ge=0)
    pointer_class_index: int = Field(ge=0, le=NONE_POINTER_CLASS)
    destination_class_index: int = Field(ge=0, le=NONE_DESTINATION_CLASS)
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_source: Literal["EXECUTED_PUBLIC_PHYSICAL_CHAIN"] = "EXECUTED_PUBLIC_PHYSICAL_CHAIN"
    skill_provenance: RuntimeParameterProvenance
    target_provenance: RuntimeParameterProvenance
    destination_provenance: RuntimeParameterProvenance
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    model_training_eligible: bool
    exclusion_reasons: list[str] = Field(default_factory=list)


class PathBlockedSupervisionBuildResultV2(StrictModel):
    schema_version: Literal["PathBlockedSupervisionBuildResultV2"] = (
        "PathBlockedSupervisionBuildResultV2"
    )
    validation: PathBlockedEvidenceValidationV2
    samples: list[M2CPathBlockedSupervisedStepV2] = Field(default_factory=list)


class PathBlockedSupervisedDatasetV2(StrictModel):
    """Deterministic multi-episode output and its pre-training audit summary."""

    schema_version: Literal["PathBlockedSupervisedDatasetV2"] = "PathBlockedSupervisedDatasetV2"
    status: Literal["PASS", "PARTIAL", "EMPTY"]
    samples: list[M2CPathBlockedSupervisedStepV2] = Field(default_factory=list)
    episode_validations: list[PathBlockedEvidenceValidationV2] = Field(default_factory=list)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    episodes_received: int = Field(ge=0)
    episodes_physical_valid: int = Field(ge=0)
    episodes_training_eligible: int = Field(ge=0)
    samples_training_eligible: int = Field(ge=0)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    checkpoint_path: None = None
    checkpoint_sha256: None = None
    exclusion_reasons: list[str] = Field(default_factory=list)


ManifestModel = TypeVar(
    "ManifestModel",
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
)


class ProbePackagingError(ValueError):
    """The untrusted physical probe cannot be bound to frozen host evidence."""


def canonical_manifest_sha256(manifest: BaseModel) -> str:
    """Hash the canonical manifest content; references bind this exact value."""

    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_dataset_asset_uri(uri: str, evidence_root: Path) -> Path:
    relative = uri.removeprefix("dataset://")
    if relative.startswith("/") or ".." in relative.split("/"):
        raise ProbePackagingError(f"dataset URI escapes evidence root: {uri}")
    root = evidence_root.resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ProbePackagingError(f"dataset URI is not a regular local file: {uri}")
    return path


def _checked_file_sha256(path: Path, expected: str, *, label: str) -> str:
    try:
        actual = _sha256_file(path.resolve(strict=True))
    except (FileNotFoundError, OSError) as error:
        raise ProbePackagingError(f"{label} cannot be read: {path}") from error
    if actual != expected:
        raise ProbePackagingError(f"{label} SHA-256 mismatch")
    return actual


def package_probe_payload(
    payload: Mapping[str, Any],
    *,
    probe_evidence_path: str | Path,
    evidence_root: str | Path,
    source_evidence_uri: str,
    collection_manifest: FrozenPathBlockedCollectionManifestV2 | Mapping[str, Any],
    collection_manifest_path: str | Path | None,
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
    s6_manifest_path: str | Path | None,
    runtime_registry_path: str | Path,
    expected_sdf_sha256: str | None = None,
    expected_supervision_sha256: str | None = None,
) -> M2CPathBlockedPhysicalChainEvidenceV2:
    """Bind an untrusted Isaac chain to checked local files and frozen refs.

    The caller must pass the exact bytes written by the probe as
    ``probe_evidence_path``.  This function projects only
    ``payload['m2c_path_blocked_physical_chain']``; it never accepts class
    indices or model labels from the probe.  RGB, depth, capture-receipt and
    physical-receipt hashes are recomputed before the strict evidence model is
    returned.
    """

    try:
        raw_chain = payload["m2c_path_blocked_physical_chain"]
    except KeyError as error:
        raise ProbePackagingError(
            "probe payload is missing m2c_path_blocked_physical_chain"
        ) from error
    if not isinstance(raw_chain, Mapping):
        raise ProbePackagingError("probe chain must be an object")
    forbidden_probe_fields = {
        "model_label",
        "skill_label_index",
        "pointer_class_index",
        "destination_class_index",
    }
    for index, raw_step in enumerate(raw_chain.get("steps", [])):
        if isinstance(raw_step, Mapping):
            forbidden = sorted(forbidden_probe_fields & raw_step.keys())
            if forbidden:
                raise ProbePackagingError(
                    f"step {index} probe may not self-assert training labels: {forbidden}"
                )
    try:
        source_path = Path(probe_evidence_path).resolve(strict=True)
        source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProbePackagingError("probe evidence file cannot be read as JSON") from error
    if _canonical_payload_sha256(source_payload) != _canonical_payload_sha256(payload):
        raise ProbePackagingError("in-memory payload differs from probe evidence file")
    try:
        probe = M2CPathBlockedProbeChainV2.model_validate(raw_chain)
    except ValidationError as error:
        raise ProbePackagingError("; ".join(_schema_reasons("PROBE_CHAIN", error))) from error

    parsed_collection, collection_reasons = _parse_manifest(
        FrozenPathBlockedCollectionManifestV2,
        collection_manifest,
        "COLLECTION_MANIFEST",
    )
    parsed_s6, s6_reasons = _parse_manifest(
        FrozenS6ExclusionManifestV2,
        s6_manifest,
        "S6_EXCLUSION_MANIFEST",
    )
    manifest_reasons = [*collection_reasons, *s6_reasons]
    if manifest_reasons or parsed_collection is None or parsed_s6 is None:
        raise ProbePackagingError("; ".join(manifest_reasons))

    runtime_path = Path(runtime_registry_path)
    if collection_manifest_path is not None:
        collection_path = Path(collection_manifest_path)
        try:
            collection_bytes = json.loads(collection_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProbePackagingError(
                "checked-in collection manifest file cannot be parsed"
            ) from error
        if collection_bytes != parsed_collection.model_dump(mode="json"):
            raise ProbePackagingError("collection manifest object differs from checked-in file")
    if s6_manifest_path is not None:
        s6_path = Path(s6_manifest_path)
        try:
            s6_bytes = json.loads(s6_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ProbePackagingError("checked-in S6 manifest file cannot be parsed") from error
        if s6_bytes != parsed_s6.model_dump(mode="json"):
            raise ProbePackagingError("S6 manifest object differs from checked-in file")
    try:
        runtime_registry_sha256 = _sha256_file(runtime_path.resolve(strict=True))
    except (FileNotFoundError, OSError) as error:
        raise ProbePackagingError("runtime registry cannot be read") from error
    if runtime_registry_sha256 != parsed_collection.runtime_registry_sha256:
        raise ProbePackagingError("runtime registry differs from collection manifest binding")

    frozen_keys = [
        key for key in parsed_collection.keys if key.collection_key == probe.collection_key
    ]
    if len(frozen_keys) != 1:
        raise ProbePackagingError("probe collection key is not exactly once in frozen manifest")
    key = frozen_keys[0]
    expected_identity = (
        key.scene_seed,
        key.failure_seed,
        key.matched_key,
        key.collection_role,
        key.split,
        key.split_group,
    )
    probe_identity = (
        probe.scene_seed,
        probe.failure_seed,
        probe.matched_key,
        probe.collection_role,
        probe.split,
        probe.split_group,
    )
    if probe_identity != expected_identity:
        raise ProbePackagingError("probe scene/key/role/split identity is not frozen")
    if expected_sdf_sha256 is not None and probe.sdf_sha256 != expected_sdf_sha256:
        raise ProbePackagingError("probe SDF SHA-256 differs from frozen key binding")
    if (
        expected_supervision_sha256 is not None
        and probe.supervision_sha256 != expected_supervision_sha256
    ):
        raise ProbePackagingError("probe supervision SHA-256 differs from frozen key binding")

    raw_steps = raw_chain.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) != len(probe.steps):
        raise ProbePackagingError("probe raw steps cannot be paired with parsed steps")
    public_rgbd = payload.get("m2b_public_rgbd")
    raw_captures: list[Mapping[str, Any]] | None = None
    if isinstance(public_rgbd, Mapping):
        candidate_captures = public_rgbd.get("captures")
        if isinstance(candidate_captures, list) and all(
            isinstance(item, Mapping) for item in candidate_captures
        ):
            raw_captures = candidate_captures

    evidence_root_path = Path(evidence_root)
    packaged_steps: list[dict[str, Any]] = []
    for step, raw_step in zip(probe.steps, raw_steps, strict=True):
        if not isinstance(raw_step, Mapping):
            raise ProbePackagingError(f"step {step.decision_index} raw evidence is not an object")
        raw_observation = raw_step.get("observation")
        raw_receipts = raw_step.get("physical_receipts")
        if not isinstance(raw_observation, Mapping) or not isinstance(raw_receipts, list):
            raise ProbePackagingError(
                f"step {step.decision_index} raw observation/receipts cannot be verified"
            )
        observation = step.observation.model_dump(mode="json", exclude_none=True)
        rgb_sha256 = _checked_file_sha256(
            _resolve_dataset_asset_uri(observation["rgb_uri"], evidence_root_path),
            observation["rgb_sha256"],
            label=f"step {step.decision_index} RGB",
        )
        depth_sha256 = _checked_file_sha256(
            _resolve_dataset_asset_uri(observation["depth_uri"], evidence_root_path),
            observation["depth_sha256"],
            label=f"step {step.decision_index} depth",
        )
        if raw_captures is None:
            capture_core = {
                key: raw_observation[key]
                for key in (
                    "observation_id",
                    "captured_at_ns",
                    "source",
                    "rgb_uri",
                    "depth_uri",
                    "rgb_sha256",
                    "depth_sha256",
                    "perception_tracks",
                    "canonical_slots",
                )
            }
        else:
            matches = [
                capture
                for capture in raw_captures
                if capture.get("timestamp_ns") == observation["captured_at_ns"]
                and capture.get("rgb_uri") == observation["rgb_uri"]
                and capture.get("depth_uri") == observation["depth_uri"]
                and capture.get("rgb_sha256") == rgb_sha256
                and capture.get("depth_sha256") == depth_sha256
            ]
            if len(matches) != 1:
                raise ProbePackagingError(
                    f"step {step.decision_index} does not bind exactly one public RGB-D capture"
                )
            capture_core = matches[0]
        recomputed_capture_sha256 = _canonical_payload_sha256(capture_core)
        if observation["capture_receipt_sha256"] != recomputed_capture_sha256:
            raise ProbePackagingError(
                f"step {step.decision_index} capture receipt SHA-256 mismatch"
            )
        observation["capture_receipt_sha256"] = recomputed_capture_sha256

        receipts: list[dict[str, Any]] = []
        if len(raw_receipts) != len(step.physical_receipts):
            raise ProbePackagingError(
                f"step {step.decision_index} raw receipt count changed during parsing"
            )
        for receipt, raw_receipt in zip(
            step.physical_receipts,
            raw_receipts,
            strict=True,
        ):
            if not isinstance(raw_receipt, Mapping):
                raise ProbePackagingError(
                    f"step {step.decision_index} raw physical receipt is not an object"
                )
            receipt_payload = receipt.model_dump(mode="json", exclude_none=True)
            reported = receipt_payload.pop("receipt_sha256")
            raw_receipt_core = {
                key: value for key, value in raw_receipt.items() if key != "receipt_sha256"
            }
            recomputed = _canonical_payload_sha256(raw_receipt_core)
            if reported != recomputed:
                raise ProbePackagingError(
                    f"step {step.decision_index} physical receipt SHA-256 mismatch"
                )
            receipts.append({**receipt_payload, "receipt_sha256": recomputed})
        packaged_steps.append(
            {
                **step.model_dump(mode="json"),
                "observation": observation,
                "physical_receipts": receipts,
            }
        )

    source_evidence_sha256 = _sha256_file(source_path)
    return M2CPathBlockedPhysicalChainEvidenceV2(
        **probe.model_dump(
            mode="json",
            exclude={
                "schema_version",
                "collection_manifest_ref",
                "s6_exclusion_manifest_ref",
                "runtime_registry_sha256",
                "source_evidence_uri",
                "source_evidence_sha256",
                "steps",
            },
        ),
        collection_manifest_ref=FrozenManifestRefV2(
            manifest_key=parsed_collection.manifest_key,
            manifest_sha256=canonical_manifest_sha256(parsed_collection),
        ),
        s6_exclusion_manifest_ref=FrozenManifestRefV2(
            manifest_key=parsed_s6.manifest_key,
            manifest_sha256=canonical_manifest_sha256(parsed_s6),
        ),
        runtime_registry_sha256=runtime_registry_sha256,
        source_evidence_uri=source_evidence_uri,
        source_evidence_sha256=source_evidence_sha256,
        steps=packaged_steps,
    )


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _schema_reasons(label: str, error: ValidationError) -> list[str]:
    reasons: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"]) or "ROOT"
        _append_reason(
            reasons,
            f"{label}_SCHEMA_INVALID:{location}:{item['type']}",
        )
    return reasons or [f"{label}_SCHEMA_INVALID"]


def _parse_manifest(
    model: type[ManifestModel],
    value: ManifestModel | Mapping[str, Any],
    label: str,
) -> tuple[ManifestModel | None, list[str]]:
    try:
        return (
            value if isinstance(value, model) else model.model_validate(value),
            [],
        )
    except ValidationError as error:
        return None, _schema_reasons(label, error)


def _expected_canonical_slots(
    tracks: Sequence[PerceptionTrackV1],
) -> list[str | None]:
    track_ids = [track.track_id for track in tracks]
    ordered = sorted(track_ids)[:POINTER_SLOT_COUNT]
    return [*ordered, *([None] * (POINTER_SLOT_COUNT - len(ordered)))]


def _pointer_class(track_id: str | None, slots: list[str | None]) -> int | None:
    if track_id is None:
        return NONE_POINTER_CLASS
    try:
        return slots.index(track_id)
    except ValueError:
        return None


def _destination_class(destination_cell: str | None) -> int | None:
    if destination_cell is None:
        return NONE_DESTINATION_CLASS
    try:
        return REGISTERED_DESTINATION_CELLS.index(destination_cell)
    except ValueError:
        return None


def _episode_id_from_untrusted(value: Mapping[str, Any] | object) -> str:
    if isinstance(value, Mapping):
        candidate = value.get("episode_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return "UNKNOWN"


def _validate_parsed_evidence(
    evidence: M2CPathBlockedPhysicalChainEvidenceV2,
    collection_manifest: FrozenPathBlockedCollectionManifestV2,
    s6_manifest: FrozenS6ExclusionManifestV2,
) -> PathBlockedEvidenceValidationV2:
    reasons: list[str] = []
    if evidence.collection_manifest_ref.manifest_key != collection_manifest.manifest_key:
        _append_reason(reasons, "COLLECTION_MANIFEST_KEY_MISMATCH")
    if evidence.collection_manifest_ref.manifest_sha256 != canonical_manifest_sha256(
        collection_manifest
    ):
        _append_reason(reasons, "COLLECTION_MANIFEST_SHA256_MISMATCH")
    if evidence.s6_exclusion_manifest_ref.manifest_key != s6_manifest.manifest_key:
        _append_reason(reasons, "S6_EXCLUSION_MANIFEST_KEY_MISMATCH")
    if evidence.s6_exclusion_manifest_ref.manifest_sha256 != canonical_manifest_sha256(s6_manifest):
        _append_reason(reasons, "S6_EXCLUSION_MANIFEST_SHA256_MISMATCH")
    if evidence.runtime_registry_sha256 != collection_manifest.runtime_registry_sha256:
        _append_reason(reasons, "RUNTIME_REGISTRY_SHA256_MISMATCH")

    allowed = [
        item for item in collection_manifest.keys if item.collection_key == evidence.collection_key
    ]
    if len(allowed) != 1:
        _append_reason(reasons, "COLLECTION_KEY_NOT_EXACTLY_ONCE_IN_FROZEN_MANIFEST")
    else:
        entry = allowed[0]
        comparisons = {
            "COLLECTION_ROLE_MISMATCH": (
                evidence.collection_role,
                entry.collection_role,
            ),
            "MATCHED_KEY_NOT_FROZEN_FOR_COLLECTION": (
                evidence.matched_key,
                entry.matched_key,
            ),
            "SCENE_SEED_NOT_FROZEN_FOR_COLLECTION": (
                evidence.scene_seed,
                entry.scene_seed,
            ),
            "FAILURE_SEED_NOT_FROZEN_FOR_COLLECTION": (
                evidence.failure_seed,
                entry.failure_seed,
            ),
            "SPLIT_NOT_FROZEN_FOR_COLLECTION": (evidence.split, entry.split),
            "SPLIT_GROUP_NOT_FROZEN_FOR_COLLECTION": (
                evidence.split_group,
                entry.split_group,
            ),
        }
        for reason, (actual, expected) in comparisons.items():
            if actual != expected:
                _append_reason(reasons, reason)
    if evidence.split_group != f"scene-{evidence.scene_seed}":
        _append_reason(reasons, "SPLIT_GROUP_IS_NOT_SCENE_GROUPED")

    if evidence.scene_seed in V4_QA_SCENE_SEEDS:
        _append_reason(reasons, "V4_QA_SCENE_SEED_EXCLUDED")
    if evidence.matched_key in V4_QA_MATCHED_KEYS:
        _append_reason(reasons, "V4_QA_MATCHED_KEY_EXCLUDED")
    s6_matched_keys = {item.matched_key for item in s6_manifest.keys}
    s6_scene_seeds = {item.scene_seed for item in s6_manifest.keys}
    s6_groups = {(item.scene_seed, item.failure_seed) for item in s6_manifest.keys}
    if any(item.scene_seed in V4_QA_SCENE_SEEDS for item in collection_manifest.keys):
        _append_reason(reasons, "COLLECTION_MANIFEST_CONTAINS_V4_QA_SCENE")
    if any(item.matched_key in V4_QA_MATCHED_KEYS for item in collection_manifest.keys):
        _append_reason(reasons, "COLLECTION_MANIFEST_CONTAINS_V4_QA_MATCHED_KEY")
    if any(item.matched_key in s6_matched_keys for item in collection_manifest.keys):
        _append_reason(reasons, "COLLECTION_MANIFEST_CONTAINS_S6_MATCHED_KEY")
    if any(item.scene_seed in s6_scene_seeds for item in collection_manifest.keys):
        _append_reason(reasons, "COLLECTION_MANIFEST_CONTAINS_S6_SCENE_GROUP")
    if any((item.scene_seed, item.failure_seed) in s6_groups for item in collection_manifest.keys):
        _append_reason(
            reasons,
            "COLLECTION_MANIFEST_CONTAINS_S6_SCENE_FAILURE_GROUP",
        )
    if evidence.matched_key in s6_matched_keys:
        _append_reason(reasons, "S6_MATCHED_KEY_EXCLUDED")
    if evidence.scene_seed in s6_scene_seeds:
        _append_reason(reasons, "S6_SCENE_GROUP_EXCLUDED")
    if (evidence.scene_seed, evidence.failure_seed) in s6_groups:
        _append_reason(reasons, "S6_SCENE_FAILURE_GROUP_EXCLUDED")

    if evidence.teacher_used:
        _append_reason(reasons, "TEACHER_USED_KILL_RULE")
    if evidence.privileged_truth_policy_input:
        _append_reason(reasons, "PRIVILEGED_TRUTH_POLICY_INPUT")
    if not evidence.final_task_success:
        _append_reason(reasons, "FINAL_TASK_NOT_SUCCESSFUL")
    if len(evidence.steps) != len(EXPECTED_PATH_BLOCKED_CHAIN):
        _append_reason(reasons, "PHYSICAL_CHAIN_LENGTH_NOT_EIGHT")

    seen_observation_ids: set[str] = set()
    seen_capture_receipts: set[str] = set()
    seen_receipt_ids: set[str] = set()
    seen_receipt_sha256: set[str] = set()
    freshness_floor_ns = evidence.failure_observed_at_ns
    chosen_destination: str | None = None
    for position, step in enumerate(evidence.steps):
        prefix = f"STEP_{position}:"
        expected_skill = (
            EXPECTED_PATH_BLOCKED_CHAIN[position]
            if position < len(EXPECTED_PATH_BLOCKED_CHAIN)
            else None
        )
        if step.decision_index != position:
            _append_reason(reasons, prefix + "NON_CANONICAL_DECISION_INDEX")
        if step.teacher_used or step.observation.teacher_used:
            _append_reason(reasons, prefix + "TEACHER_USED_KILL_RULE")
        if step.privileged_truth_policy_input or step.observation.privileged_truth_policy_input:
            _append_reason(reasons, prefix + "PRIVILEGED_TRUTH_POLICY_INPUT")

        observation = step.observation
        if not observation.fresh:
            _append_reason(reasons, prefix + "PUBLIC_OBSERVATION_NOT_FRESH")
        if observation.captured_at_ns <= freshness_floor_ns:
            _append_reason(
                reasons,
                prefix + "PUBLIC_OBSERVATION_NOT_AFTER_PREVIOUS_PHYSICAL_EVENT",
            )
        if observation.observation_id in seen_observation_ids:
            _append_reason(reasons, prefix + "PUBLIC_OBSERVATION_ID_REUSED")
        seen_observation_ids.add(observation.observation_id)
        if observation.capture_receipt_sha256 in seen_capture_receipts:
            _append_reason(reasons, prefix + "PUBLIC_CAPTURE_RECEIPT_REUSED")
        seen_capture_receipts.add(observation.capture_receipt_sha256)
        track_ids = [track.track_id for track in observation.perception_tracks]
        if len(track_ids) != len(set(track_ids)):
            _append_reason(reasons, prefix + "DUPLICATE_PUBLIC_TRACK_ID")
        if any(not track_id.startswith("track-") or "/" in track_id for track_id in track_ids):
            _append_reason(reasons, prefix + "NON_PUBLIC_TRACK_IDENTIFIER")
        expected_slots = _expected_canonical_slots(observation.perception_tracks)
        if observation.canonical_slots != expected_slots:
            _append_reason(reasons, prefix + "NON_CANONICAL_K8_TRACK_SLOTS")

        if position <= 4:
            expected_target = step.public_blocker_track_id
            if expected_target is None:
                _append_reason(reasons, prefix + "PUBLIC_BLOCKER_TRACK_MISSING")
        elif position >= 6:
            expected_target = step.public_task_target_track_id
            if expected_target is None:
                _append_reason(reasons, prefix + "PUBLIC_TASK_TARGET_TRACK_MISSING")
        else:
            expected_target = None
        if (
            step.public_blocker_track_id is not None
            and step.public_blocker_track_id == step.public_task_target_track_id
        ):
            _append_reason(reasons, prefix + "BLOCKER_AND_TASK_TARGET_IDENTICAL")
        expected_pointer_class = _pointer_class(expected_target, expected_slots)
        if expected_pointer_class is None:
            _append_reason(reasons, prefix + "PUBLIC_TARGET_OUTSIDE_CANONICAL_K8")

        destination_required = position in {2, 3}
        destination = step.destination_cell_label
        if destination_required:
            if destination not in REGISTERED_DESTINATION_CELLS:
                _append_reason(reasons, prefix + "DESTINATION_CELL_NOT_REGISTERED")
            elif chosen_destination is None:
                chosen_destination = destination
            elif destination != chosen_destination:
                _append_reason(reasons, prefix + "MOVE_PLACE_DESTINATION_DISAGREE")
        elif destination is not None:
            _append_reason(reasons, prefix + "DESTINATION_CELL_NOT_APPLICABLE")
        expected_destination_class = _destination_class(destination)
        if expected_destination_class is None:
            _append_reason(reasons, prefix + "DESTINATION_CELL_NOT_REGISTERED")

        if len(step.physical_receipts) != 1:
            _append_reason(reasons, prefix + "PHYSICAL_RECEIPT_COUNT_NOT_ONE")
        completed_times: list[int] = []
        for receipt in step.physical_receipts:
            if receipt.receipt_id in seen_receipt_ids:
                _append_reason(reasons, prefix + "PHYSICAL_RECEIPT_REUSED")
            seen_receipt_ids.add(receipt.receipt_id)
            if receipt.receipt_sha256 in seen_receipt_sha256:
                _append_reason(reasons, prefix + "PHYSICAL_RECEIPT_REUSED")
            seen_receipt_sha256.add(receipt.receipt_sha256)
            if receipt.executed_skill != expected_skill:
                _append_reason(reasons, prefix + "PHYSICAL_SKILL_MISMATCH")
            if not receipt.physically_executed:
                _append_reason(reasons, prefix + "SKILL_NOT_PHYSICALLY_EXECUTED")
            if receipt.started_at_ns <= observation.captured_at_ns:
                _append_reason(reasons, prefix + "PHYSICAL_EXECUTION_PRECEDES_CAPTURE")
            if receipt.completed_at_ns <= receipt.started_at_ns:
                _append_reason(reasons, prefix + "PHYSICAL_RECEIPT_TIME_INVALID")
            completed_times.append(receipt.completed_at_ns)
            for gate_name in (
                "schema_gate",
                "stale_track_gate",
                "frame_unit_gate",
                "ik_gate",
                "collision_gate",
                "controller_gate",
                "safety_gate",
            ):
                if getattr(receipt, gate_name) != "PASS":
                    _append_reason(
                        reasons,
                        prefix + gate_name.upper() + "_NOT_PASSING",
                    )
            if receipt.collision_or_safety_violation:
                _append_reason(reasons, prefix + "COLLISION_OR_SAFETY_VIOLATION")
            if receipt.teacher_used:
                _append_reason(reasons, prefix + "TEACHER_USED_KILL_RULE")
            if receipt.privileged_truth_policy_input:
                _append_reason(reasons, prefix + "PRIVILEGED_TRUTH_POLICY_INPUT")
        if completed_times:
            freshness_floor_ns = max(completed_times)
        else:
            freshness_floor_ns = max(freshness_floor_ns, observation.captured_at_ns)

    physical_valid = not reasons
    if physical_valid and evidence.collection_role == "SMOKE":
        reasons.append("COLLECTION_ROLE_SMOKE_NOT_TRAINING")
    eligible = physical_valid and evidence.collection_role == "TRAIN"
    status: Literal["PASS_TRAIN", "PASS_SMOKE", "EXCLUDED", "INVALID_SCHEMA"]
    if eligible:
        status = "PASS_TRAIN"
    elif physical_valid:
        status = "PASS_SMOKE"
    else:
        status = "EXCLUDED"
    return PathBlockedEvidenceValidationV2(
        status=status,
        episode_id=evidence.episode_id,
        physical_evidence_valid=physical_valid,
        model_training_eligible=eligible,
        steps_validated=len(evidence.steps),
        exclusion_reasons=reasons,
    )


def _parse_all(
    raw_evidence: M2CPathBlockedPhysicalChainEvidenceV2 | Mapping[str, Any],
    collection_manifest: FrozenPathBlockedCollectionManifestV2 | Mapping[str, Any],
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
) -> tuple[
    M2CPathBlockedPhysicalChainEvidenceV2 | None,
    FrozenPathBlockedCollectionManifestV2 | None,
    FrozenS6ExclusionManifestV2 | None,
    list[str],
]:
    reasons: list[str] = []
    parsed_collection, collection_reasons = _parse_manifest(
        FrozenPathBlockedCollectionManifestV2,
        collection_manifest,
        "COLLECTION_MANIFEST",
    )
    reasons.extend(collection_reasons)
    parsed_s6, s6_reasons = _parse_manifest(
        FrozenS6ExclusionManifestV2,
        s6_manifest,
        "S6_EXCLUSION_MANIFEST",
    )
    reasons.extend(s6_reasons)
    try:
        parsed_evidence = (
            raw_evidence
            if isinstance(raw_evidence, M2CPathBlockedPhysicalChainEvidenceV2)
            else M2CPathBlockedPhysicalChainEvidenceV2.model_validate(raw_evidence)
        )
    except ValidationError as error:
        parsed_evidence = None
        reasons.extend(_schema_reasons("RAW_EVIDENCE", error))
    return parsed_evidence, parsed_collection, parsed_s6, reasons


def validate_path_blocked_physical_evidence(
    raw_evidence: M2CPathBlockedPhysicalChainEvidenceV2 | Mapping[str, Any],
    *,
    collection_manifest: FrozenPathBlockedCollectionManifestV2 | Mapping[str, Any],
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
) -> PathBlockedEvidenceValidationV2:
    """Validate raw evidence without emitting or executing any policy action."""

    evidence, collection, s6, schema_reasons = _parse_all(
        raw_evidence,
        collection_manifest,
        s6_manifest,
    )
    if schema_reasons or evidence is None or collection is None or s6 is None:
        return PathBlockedEvidenceValidationV2(
            status="INVALID_SCHEMA",
            episode_id=_episode_id_from_untrusted(raw_evidence),
            physical_evidence_valid=False,
            model_training_eligible=False,
            steps_validated=0,
            exclusion_reasons=schema_reasons,
        )
    return _validate_parsed_evidence(evidence, collection, s6)


def build_path_blocked_supervised_steps(
    raw_evidence: M2CPathBlockedPhysicalChainEvidenceV2 | Mapping[str, Any],
    *,
    collection_manifest: FrozenPathBlockedCollectionManifestV2 | Mapping[str, Any],
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
) -> PathBlockedSupervisionBuildResultV2:
    """Build eight safe coarse-label samples, or fail closed with reasons."""

    evidence, collection, s6, schema_reasons = _parse_all(
        raw_evidence,
        collection_manifest,
        s6_manifest,
    )
    if schema_reasons or evidence is None or collection is None or s6 is None:
        validation = PathBlockedEvidenceValidationV2(
            status="INVALID_SCHEMA",
            episode_id=_episode_id_from_untrusted(raw_evidence),
            physical_evidence_valid=False,
            model_training_eligible=False,
            steps_validated=0,
            exclusion_reasons=schema_reasons,
        )
        return PathBlockedSupervisionBuildResultV2(validation=validation)

    validation = _validate_parsed_evidence(evidence, collection, s6)
    if not validation.physical_evidence_valid:
        return PathBlockedSupervisionBuildResultV2(validation=validation)

    sample_exclusions = (
        [] if validation.model_training_eligible else ["COLLECTION_ROLE_SMOKE_NOT_TRAINING"]
    )
    samples: list[M2CPathBlockedSupervisedStepV2] = []
    for step in evidence.steps:
        receipt = step.physical_receipts[0]
        skill = EXPECTED_PATH_BLOCKED_CHAIN[step.decision_index]
        target_track_id = (
            step.public_blocker_track_id
            if step.decision_index <= 4
            else (step.public_task_target_track_id if step.decision_index >= 6 else None)
        )
        pointer_class_index = _pointer_class(
            target_track_id,
            step.observation.canonical_slots,
        )
        destination_class_index = _destination_class(step.destination_cell_label)
        if pointer_class_index is None or destination_class_index is None:
            raise AssertionError("validated PATH_BLOCKED label became unencodable")
        model_label = CoarseIntentV2(
            skill_type=skill,
            target_track_id=target_track_id,
            grasp_family=("top_down" if skill in {"GRASP", "REGRASP"} else "unknown"),
            recovery_mode="path_blocked",
            reobserve_flag=skill == "REOBSERVE",
            destination_cell=step.destination_cell_label,
            failure_type_aux=FailureType.PATH_BLOCKED,
        )
        target_provenance: RuntimeParameterProvenance = (
            "NONE" if step.decision_index == 5 else "MODEL"
        )
        destination_provenance: RuntimeParameterProvenance = (
            "MODEL" if step.decision_index in {2, 3} else "NONE"
        )
        samples.append(
            M2CPathBlockedSupervisedStepV2(
                sample_id=(f"{evidence.episode_id}:path-blocked-v2:{step.decision_index}"),
                episode_id=evidence.episode_id,
                decision_index=step.decision_index,
                split=evidence.split,
                split_group=evidence.split_group,
                matched_key=evidence.matched_key,
                observation=step.observation,
                model_label=model_label,
                skill_label_index=M2C_Q012_V2_SKILL_LABELS.index(skill),
                pointer_class_index=pointer_class_index,
                destination_class_index=destination_class_index,
                source_evidence_sha256=evidence.source_evidence_sha256,
                physical_receipt_sha256=receipt.receipt_sha256,
                skill_provenance="MODEL",
                target_provenance=target_provenance,
                destination_provenance=destination_provenance,
                model_training_eligible=validation.model_training_eligible,
                exclusion_reasons=sample_exclusions,
            )
        )
    return PathBlockedSupervisionBuildResultV2(
        validation=validation,
        samples=samples,
    )


def _dataset_sha256(samples: Sequence[M2CPathBlockedSupervisedStepV2]) -> str:
    payload = "".join(
        sample.model_dump_json(by_alias=False, exclude_none=False) + "\n" for sample in samples
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_path_blocked_supervised_dataset(
    raw_episodes: Sequence[M2CPathBlockedPhysicalChainEvidenceV2 | Mapping[str, Any]],
    *,
    collection_manifest: FrozenPathBlockedCollectionManifestV2 | Mapping[str, Any],
    s6_manifest: FrozenS6ExclusionManifestV2 | Mapping[str, Any],
) -> PathBlockedSupervisedDatasetV2:
    """Build a deterministic dataset and reject cross-episode leakage/reuse."""

    results = [
        build_path_blocked_supervised_steps(
            episode,
            collection_manifest=collection_manifest,
            s6_manifest=s6_manifest,
        )
        for episode in raw_episodes
    ]
    validations = [result.validation for result in results]
    samples = sorted(
        [sample for result in results for sample in result.samples],
        key=lambda sample: (sample.episode_id, sample.decision_index),
    )
    global_reasons: list[str] = []

    sample_ids = [sample.sample_id for sample in samples]
    if len(sample_ids) != len(set(sample_ids)):
        _append_reason(global_reasons, "DUPLICATE_SAMPLE_ID")
    evidence_episode_pairs = [
        (sample.episode_id, sample.source_evidence_sha256)
        for sample in samples
        if sample.decision_index == 0
    ]
    evidence_hashes = [digest for _, digest in evidence_episode_pairs]
    if len(evidence_hashes) != len(set(evidence_hashes)):
        _append_reason(global_reasons, "SOURCE_EVIDENCE_SHA256_REUSED_ACROSS_EPISODES")
    matched_keys = [sample.matched_key for sample in samples if sample.decision_index == 0]
    if len(matched_keys) != len(set(matched_keys)):
        _append_reason(global_reasons, "MATCHED_KEY_REUSED_ACROSS_EPISODES")

    split_by_group: dict[str, set[str]] = {}
    for sample in samples:
        split_by_group.setdefault(sample.split_group, set()).add(sample.split)
    leaked = sorted(group for group, splits in split_by_group.items() if len(splits) != 1)
    for group in leaked:
        _append_reason(global_reasons, f"SPLIT_GROUP_LEAKAGE:{group}")

    if global_reasons:
        samples = [
            sample.model_copy(
                update={
                    "model_training_eligible": False,
                    "exclusion_reasons": [
                        *sample.exclusion_reasons,
                        *global_reasons,
                    ],
                }
            )
            for sample in samples
        ]
    eligible_samples = [sample for sample in samples if sample.model_training_eligible]
    eligible_episodes = {
        sample.episode_id for sample in eligible_samples if sample.decision_index == 0
    }
    if not samples:
        status: Literal["PASS", "PARTIAL", "EMPTY"] = "EMPTY"
    elif global_reasons or any(
        validation.status in {"EXCLUDED", "INVALID_SCHEMA"} for validation in validations
    ):
        status = "PARTIAL"
    else:
        status = "PASS"
    return PathBlockedSupervisedDatasetV2(
        status=status,
        samples=samples,
        episode_validations=validations,
        dataset_sha256=_dataset_sha256(samples),
        episodes_received=len(raw_episodes),
        episodes_physical_valid=sum(
            validation.physical_evidence_valid for validation in validations
        ),
        episodes_training_eligible=len(eligible_episodes),
        samples_training_eligible=len(eligible_samples),
        exclusion_reasons=global_reasons,
    )


def raw_evidence_json_schema() -> dict[str, Any]:
    """Return the exact JSON schema for the physical probe implementation."""

    return M2CPathBlockedPhysicalChainEvidenceV2.model_json_schema()


def supervised_step_json_schema() -> dict[str, Any]:
    """Return the exact JSON schema for S4 training/Qwen ingestion."""

    return M2CPathBlockedSupervisedStepV2.model_json_schema()
