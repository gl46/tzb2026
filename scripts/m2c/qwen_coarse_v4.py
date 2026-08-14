#!/usr/bin/env python3
"""Fail-closed offline Qwen preparation contracts for M2C V4.

This module does not train or execute a policy.  It accepts only packaged
``PathBlockedSupervisedDatasetV4`` evidence, independently replays the bound
physical chain and public observation history, and exposes the exact
``M2C_Q012_V4`` prompt/head shapes needed by a later real trainer.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Literal, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from xh_agent.policy.qrm_lite.contracts import FailureType
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    EXPECTED_PATH_BLOCKED_CHAIN,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2C_Q012_V4_SKILL_LABELS,
    S6_MANIFEST_SHA256,
    M2CPathBlockedPhysicalChainEvidenceV4,
    M2CPathBlockedSupervisedStepV4,
    PathBlockedSupervisedDatasetV4,
    V4TrainingKeyManifest,
    build_path_blocked_supervised_dataset_v4,
    canonical_sha256,
    host_replay_probe_chain_v4,
    load_v4_training_manifest,
    validate_path_blocked_physical_evidence_v4,
    v4_manifest_file_sha256,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
    POINTER_CLASS_LABELS,
    FrozenS6ExclusionManifestV2,
    PathBlockedPhysicalSkillReceiptV2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    M2CQ012CheckpointBindingV4,
    M2CQ012DeploymentManifestV4,
    M2CQ012TensorBindingV4,
    canonical_checkpoint_binding_sha256_v4,
    load_m2c_q012_checkpoint_v4,
    recompute_candidate_payload_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    PUBLIC_TRACK_CANDIDATE_COUNT_V4,
    PUBLIC_TRACK_POINTER_CLASS_COUNT_V4,
    encode_track_pointer_target_v4,
    public_track_candidate_slots_v4,
)
from xh_agent.policy.qrm_lite.qwen_prompt_v4 import render_qwen_public_prompt_v4
from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    M2CS4V4CollectionConsumptionReceiptV1,
    M2CS4V4PackagedClaimBindingV1,
    M2CS4V4RawClaimBindingV1,
    M2CS4V4SelectedKeyCollectionPreregV1,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SKILL_LABELS = tuple(M2C_Q012_V4_SKILL_LABELS)
POINTER_LABELS = tuple(POINTER_CLASS_LABELS)
DESTINATION_LABELS = tuple(DESTINATION_CLASS_LABELS)
CHAIN_SKILLS = tuple(EXPECTED_PATH_BLOCKED_CHAIN)
HEAD_TENSOR_NAMES = (
    "destination_b",
    "destination_w",
    "pointer_b",
    "pointer_w",
    "skill_b",
    "skill_w",
)
HEAD_CHECKPOINT_NAME = "qwen_coarse_v4_heads.npz"
HEAD_DEPLOYMENT_NAME = "qwen_coarse_v4_checkpoint_deployment.json"
TRAINING_DATASET_REPORT_NAME = "qwen_coarse_v4_training_dataset_report.json"
BUNDLE_MANIFEST_NAME = "qwen_coarse_v4_bundle.json"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)


class M2CQwenCoarseV4KeyManifestAuditV1(StrictModel):
    schema_version: Literal["M2CQwenCoarseV4KeyManifestAuditV1"] = (
        "M2CQwenCoarseV4KeyManifestAuditV1"
    )
    training_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    training_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    s6_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    s6_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    training_keys: list[str] = Field(min_length=36, max_length=36)
    evaluation_keys: list[str] = Field(min_length=30)
    overlap_keys: list[str] = Field(max_length=0)
    overlap_scene_seeds: list[int] = Field(max_length=0)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class M2CQwenCoarseV4PackageRefV1(StrictModel):
    schema_version: Literal["M2CQwenCoarseV4PackageRefV1"] = "M2CQwenCoarseV4PackageRefV1"
    package_root: str
    matched_key: str
    episode_id: str
    source_evidence_file_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_chain_file_sha256: str = Field(pattern=SHA256_PATTERN)
    supervised_dataset_file_sha256: str = Field(pattern=SHA256_PATTERN)
    collection_receipt_file_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    samples: Literal[8] = 8


class M2CQwenCoarseV4CopiedReceiptRefV1(StrictModel):
    path: str
    file_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_receipt_sha256: str = Field(pattern=SHA256_PATTERN)


class M2CQwenCoarseV4CollectionReceiptV1(StrictModel):
    schema_version: Literal["M2CPathBlockedCollectionReceiptV4"]
    status: Literal["PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"]
    matched_key: str
    scene_seed: int
    failure_seed: int
    split: Literal["train"]
    collection_role: Literal["TRAIN"]
    decision_source: Literal["SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"]
    model_owned: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]
    pure_model_success_evidence: Literal[False]
    physical_chain_steps: Literal[8]
    physical_receipts: Literal[8]
    fresh_public_rgbd_observations: Literal[8]
    copied_public_assets: dict[str, str]
    physical_receipt_files: dict[str, M2CQwenCoarseV4CopiedReceiptRefV1]
    raw_probe_sha256: str = Field(pattern=SHA256_PATTERN)
    console_file_sha256: str = Field(pattern=SHA256_PATTERN)
    packaged_physical_chain_sha256: str = Field(pattern=SHA256_PATTERN)
    supervised_dataset_file_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    collection_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    collection_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_contract_revision: Literal["PublicTrackCandidateV4"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V4"]
    s6_exclusion_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    frozen_training_key_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    frozen_s6_key_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_registry_sha256: str = Field(pattern=SHA256_PATTERN)
    executing_probe_source_sha256: str = Field(pattern=SHA256_PATTERN)
    derived_probe_file_sha256: str = Field(pattern=SHA256_PATTERN)
    frozen_upstream_v4_probe_sha256: str = Field(pattern=SHA256_PATTERN)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    checkpoint_path: None
    checkpoint_sha256: None
    training_executed: Literal[False]
    evaluation_executed: Literal[False]
    collection_authorization: M2CS4V4PackagedClaimBindingV1


class M2CQwenCoarseV4DatasetLoadReportV1(StrictModel):
    schema_version: Literal["M2CQwenCoarseV4DatasetLoadReportV1"] = (
        "M2CQwenCoarseV4DatasetLoadReportV1"
    )
    status: Literal["PASS_REPLAYED_V4_TRAIN_DATA"]
    combined_dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    rows_total: int = Field(gt=0)
    eligible_episodes: int = Field(gt=0)
    packages: list[M2CQwenCoarseV4PackageRefV1] = Field(min_length=1)
    key_manifest_audit: M2CQwenCoarseV4KeyManifestAuditV1
    training_executed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


def dataset_report_sha256_v4(report: M2CQwenCoarseV4DatasetLoadReportV1) -> str:
    return canonical_sha256(report.model_dump(mode="json"))


class M2CQwenCoarseV4OfflineSmokeV1(StrictModel):
    schema_version: Literal["M2CQwenCoarseV4OfflineSmokeV1"] = "M2CQwenCoarseV4OfflineSmokeV1"
    status: Literal["CONTRACT_SMOKE_PASS_NO_TRAINING"]
    samples_checked: int = Field(gt=0)
    prompts_sha256: str = Field(pattern=SHA256_PATTERN)
    head_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    skill_logits_shape: list[int]
    pointer_logits_shape: list[int]
    destination_logits_shape: list[int]
    optimizer_steps: Literal[0] = 0
    checkpoint_written: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class M2CQwenCoarseV4BundleManifestV1(StrictModel):
    schema_version: Literal["M2CQwenCoarseV4BundleManifestV1"] = "M2CQwenCoarseV4BundleManifestV1"
    status: Literal["TRAINED_QWEN_LORA_M2C_Q012_V4"]
    architecture_revision: Literal["M2C_Q012_V4"] = "M2C_Q012_V4"
    public_observation_revision: Literal["PathBlockedPublicObservationV4"] = (
        "PathBlockedPublicObservationV4"
    )
    public_track_associator_revision: Literal["PublicTrackAssociatorV2"] = "PublicTrackAssociatorV2"
    public_track_candidate_revision: Literal["PublicTrackCandidateV4"] = "PublicTrackCandidateV4"
    model_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    base_model_snapshot_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    failure_context: Literal["on", "off"]
    adapter_relative_path: Literal["adapter"] = "adapter"
    adapter_tree_sha256: str = Field(pattern=SHA256_PATTERN)
    head_checkpoint_relative_path: Literal["qwen_coarse_v4_heads.npz"] = HEAD_CHECKPOINT_NAME
    head_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    head_deployment_relative_path: Literal["qwen_coarse_v4_checkpoint_deployment.json"] = (
        HEAD_DEPLOYMENT_NAME
    )
    head_deployment: M2CQ012DeploymentManifestV4
    head_deployment_file_sha256: str = Field(pattern=SHA256_PATTERN)
    training_dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    training_dataset_report_relative_path: Literal[
        "qwen_coarse_v4_training_dataset_report.json"
    ] = TRAINING_DATASET_REPORT_NAME
    training_dataset_report_sha256: str = Field(pattern=SHA256_PATTERN)
    training_dataset_report_file_sha256: str = Field(pattern=SHA256_PATTERN)
    training_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    training_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    s6_manifest_file_sha256: str = Field(pattern=SHA256_PATTERN)
    s6_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    seed: int
    train_samples: int = Field(gt=0)
    train_episodes: int = Field(gt=0)
    optimizer_steps: int = Field(gt=0)
    training_complete: Literal[True]
    physical_evaluation_executed: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    bundle_sha256: str = Field(pattern=SHA256_PATTERN)

    @classmethod
    def _content_sha256(cls, payload: dict[str, object]) -> str:
        return canonical_sha256(
            {key: value for key, value in payload.items() if key != "bundle_sha256"}
        )

    @staticmethod
    def _deployment_file_bytes(deployment: M2CQ012DeploymentManifestV4) -> bytes:
        return (
            json.dumps(
                deployment.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def model_post_init(self, _context: object) -> None:
        if self.head_checkpoint_sha256 != self.head_deployment.checkpoint_file_sha256:
            raise ValueError("V4 bundle checkpoint differs from deployment binding")
        if self.head_deployment_file_sha256 != sha256_bytes(
            self._deployment_file_bytes(self.head_deployment)
        ):
            raise ValueError("V4 bundle deployment file SHA-256 mismatch")
        if self.bundle_sha256 != self._content_sha256(self.model_dump(mode="json")):
            raise ValueError("V4 bundle canonical SHA-256 mismatch")


M2CQwenCoarseV4TrainingSample = M2CPathBlockedSupervisedStepV4


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"V4 evidence must be a single-link regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after:
            raise ValueError(f"V4 evidence changed while being read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _load_frozen_s6_manifest(
    path: Path,
) -> tuple[dict[str, object], FrozenS6ExclusionManifestV2, bytes]:
    raw = _read_regular_file_once(path)
    if sha256_bytes(raw) != S6_MANIFEST_SHA256:
        raise ValueError("S6 evaluation manifest differs from the frozen checked-in bytes")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("S6 evaluation manifest is not an object")
    embedded = payload.get("manifest_sha256")
    without_digest = dict(payload)
    without_digest.pop("manifest_sha256", None)
    if embedded != canonical_sha256(without_digest):
        raise ValueError("S6 evaluation manifest embedded SHA-256 mismatch")
    if (
        payload.get("schema_version") != "M2CS6FrozenEvaluationKeyManifestV1"
        or payload.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION"
        or payload.get("excluded_from_all_training") is not True
        or payload.get("selection_uses_rollout_outcomes") is not False
        or payload.get("teacher_used") is not False
        or payload.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("S6 evaluation manifest is not a frozen public-only exclusion")
    records = payload.get("evaluation_keys")
    if not isinstance(records, list) or not records:
        raise ValueError("S6 evaluation manifest has no frozen keys")
    projection = FrozenS6ExclusionManifestV2.model_validate(
        {
            "schema_version": "FrozenS6ExclusionManifestV2",
            "manifest_key": "M2C_S6_FROZEN_EVALUATION_KEYS",
            "frozen_before_q_b_training": True,
            "keys": [
                {
                    "schema_version": "FrozenS6EvaluationKeyV2",
                    "matched_key": item["matched_key"],
                    "scene_seed": item["scene_seed"],
                    "failure_seed": item["failure_seed"],
                }
                for item in records
            ],
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
    )
    return payload, projection, raw


def validate_key_manifests_v4(
    training_manifest_path: Path,
    evaluation_manifest_path: Path,
) -> tuple[
    M2CQwenCoarseV4KeyManifestAuditV1,
    V4TrainingKeyManifest,
    FrozenS6ExclusionManifestV2,
]:
    training_raw = _read_regular_file_once(training_manifest_path)
    training = load_v4_training_manifest(training_manifest_path)
    s6_payload, s6, s6_raw = _load_frozen_s6_manifest(evaluation_manifest_path)
    if training.source_bindings.get("configs/m2c_s6_evaluation_keys.json") != sha256_bytes(s6_raw):
        raise ValueError("V4 training manifest does not bind the frozen S6 file")
    train_keys = [item.matched_key for item in training.training_keys]
    evaluation_records = s6_payload["evaluation_keys"]
    evaluation_keys = [str(item["matched_key"]) for item in evaluation_records]
    train_scenes = {item.scene_seed for item in training.training_keys}
    evaluation_scenes = {int(item["scene_seed"]) for item in evaluation_records}
    overlap_keys = sorted(set(train_keys) & set(evaluation_keys))
    overlap_scenes = sorted(train_scenes & evaluation_scenes)
    if overlap_keys or overlap_scenes:
        raise ValueError("V4 training identities overlap frozen S6 evaluation identities")
    return (
        M2CQwenCoarseV4KeyManifestAuditV1(
            training_manifest_file_sha256=sha256_bytes(training_raw),
            training_manifest_sha256=training.manifest_sha256,
            s6_manifest_file_sha256=sha256_bytes(s6_raw),
            s6_manifest_sha256=str(s6_payload["manifest_sha256"]),
            training_keys=train_keys,
            evaluation_keys=evaluation_keys,
            overlap_keys=[],
            overlap_scene_seeds=[],
        ),
        training,
        s6,
    )


def canonical_slots_for_sample_v4(sample: M2CQwenCoarseV4TrainingSample):  # noqa: ANN201
    observation = sample.observation
    expected_payload, expected_sha256 = recompute_candidate_payload_v4(observation)
    if observation.candidate_payload.model_dump(mode="json") != expected_payload:
        raise ValueError("V4 sample candidate payload is not public-track recomputable")
    if observation.candidate_payload_sha256 != expected_sha256:
        raise ValueError("V4 sample candidate payload SHA-256 mismatch")
    slots = public_track_candidate_slots_v4(
        observation.perception_tracks,
        declared_attribute_token=observation.declared_target_attribute,
    )
    if list(slots.valid_mask) != observation.candidate_payload.valid_mask:
        raise ValueError("V4 sample candidate mask differs from recomputed K=8 slots")
    return slots


def _target_public_color_v4(sample: M2CQwenCoarseV4TrainingSample) -> str | None:
    target = sample.model_label.target_track_id
    if target is None:
        return None
    candidates = {item.track_id: item for item in sample.observation.candidate_payload.candidates}
    candidate = candidates.get(target)
    if candidate is None:
        return None
    tokens = candidate.category.casefold().replace("/", ":").split(":")
    colors = [color for color in ("red", "yellow") if color in tokens]
    return colors[0] if len(colors) == 1 else None


def validate_training_sample_v4(sample: M2CQwenCoarseV4TrainingSample) -> None:
    if sample.teacher_used or sample.privileged_truth_policy_input:
        raise ValueError("V4 Qwen sample contains Teacher or privileged truth")
    if not sample.model_training_eligible:
        raise ValueError("V4 Qwen sample is not physically training-eligible")
    if sample.split != "train" or sample.label_source != "EXECUTED_PUBLIC_PHYSICAL_CHAIN":
        raise ValueError("V4 Qwen accepts only executed TRAIN supervision")
    if sample.skill_provenance != "MODEL":
        raise ValueError("V4 Qwen skill label is not model-owned")
    expected_skill = CHAIN_SKILLS[sample.decision_index]
    if sample.model_label.skill_type != expected_skill:
        raise ValueError(f"V4 decision {sample.decision_index} requires {expected_skill}")
    if SKILL_LABELS[sample.skill_label_index] != expected_skill:
        raise ValueError("V4 skill label index differs from CoarseIntentV2")
    slots = canonical_slots_for_sample_v4(sample)
    pointer = encode_track_pointer_target_v4(sample.model_label.target_track_id, slots)
    if pointer != sample.pointer_class_index:
        raise ValueError("V4 pointer label differs from fresh K=8 candidates")
    destination = sample.model_label.destination_cell or "NONE"
    if destination not in DESTINATION_LABELS:
        raise ValueError("V4 destination label is not registered")
    if DESTINATION_LABELS.index(destination) != sample.destination_class_index:
        raise ValueError("V4 destination label index differs from CoarseIntentV2")
    requires_pointer = sample.decision_index != 5
    if requires_pointer != (sample.model_label.target_track_id is not None):
        raise ValueError("V4 pointer presence differs from chain contract")
    requires_destination = sample.decision_index in {2, 3}
    if requires_destination != (sample.model_label.destination_cell is not None):
        raise ValueError("V4 destination presence differs from chain contract")
    if sample.target_provenance != ("NONE" if sample.decision_index == 5 else "MODEL"):
        raise ValueError("V4 target provenance differs from chain contract")
    if sample.destination_provenance != ("MODEL" if sample.decision_index in {2, 3} else "NONE"):
        raise ValueError("V4 destination provenance differs from chain contract")
    if sample.model_label.failure_type_aux != FailureType.PATH_BLOCKED:
        raise ValueError("V4 Qwen sample is not PATH_BLOCKED")
    expected_color = (
        "red" if sample.decision_index <= 4 else "yellow" if sample.decision_index >= 6 else None
    )
    if _target_public_color_v4(sample) != expected_color:
        raise ValueError("V4 target does not have the frozen public semantic role")


def _validate_complete_episodes_v4(samples: Sequence[M2CQwenCoarseV4TrainingSample]) -> None:
    by_episode: dict[str, list[M2CQwenCoarseV4TrainingSample]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    for episode_id, decisions in by_episode.items():
        ordered = sorted(decisions, key=lambda item: item.decision_index)
        if [item.decision_index for item in ordered] != list(range(8)):
            raise ValueError(f"V4 episode {episode_id} is not one complete eight-step chain")
        invariant = {(item.split_group, item.matched_key) for item in ordered}
        if len(invariant) != 1:
            raise ValueError(f"V4 episode {episode_id} changes group or matched key")
        timestamps = [item.observation.captured_at_ns for item in ordered]
        if any(after <= before for before, after in zip(timestamps, timestamps[1:])):
            raise ValueError(f"V4 episode {episode_id} observations are not strictly fresh")
        observations = [item.observation.observation_id for item in ordered]
        captures = [item.observation.capture_receipt_sha256 for item in ordered]
        receipts = [item.physical_receipt_sha256 for item in ordered]
        if len(observations) != len(set(observations)):
            raise ValueError(f"V4 episode {episode_id} reuses an observation")
        if len(captures) != len(set(captures)):
            raise ValueError(f"V4 episode {episode_id} reuses a public capture")
        if len(receipts) != len(set(receipts)):
            raise ValueError(f"V4 episode {episode_id} reuses a physical receipt")
        destinations = {item.model_label.destination_cell for item in ordered[2:4]}
        if len(destinations) != 1:
            raise ValueError(f"V4 episode {episode_id} changes destination cell")


def index_executed_histories_v4(
    samples: Sequence[M2CQwenCoarseV4TrainingSample],
) -> dict[str, list[PublicExecutedIntentHistoryItemV2]]:
    _validate_complete_episodes_v4(samples)
    histories: dict[str, list[PublicExecutedIntentHistoryItemV2]] = {}
    by_episode: dict[str, list[M2CQwenCoarseV4TrainingSample]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    for decisions in by_episode.values():
        prefix: list[PublicExecutedIntentHistoryItemV2] = []
        for sample in sorted(decisions, key=lambda item: item.decision_index):
            histories[sample.sample_id] = list(prefix)
            if sample.decision_index == 7:
                continue
            prefix.append(
                PublicExecutedIntentHistoryItemV2(
                    decision_index=sample.decision_index,
                    selected_skill=sample.model_label.skill_type,
                    target_track_id=sample.model_label.target_track_id,
                    destination_cell=sample.model_label.destination_cell,
                    physical_receipt_sha256=sample.physical_receipt_sha256,
                    execution_attribution="SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
                )
            )
    return histories


def _dataset_relative_path(uri: str) -> Path:
    if not uri.startswith("dataset://"):
        raise ValueError(f"unsupported V4 dataset URI: {uri}")
    relative = Path(uri.removeprefix("dataset://"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"V4 dataset URI escapes package root: {uri}")
    return relative


def read_dataset_asset_v4(
    package_root: Path,
    uri: str,
    expected_sha256: str,
) -> bytes:
    root = package_root.resolve(strict=True)
    path = (root / _dataset_relative_path(uri)).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("V4 public asset escapes package root")
    payload = _read_regular_file_once(path)
    if sha256_bytes(payload) != expected_sha256:
        raise ValueError(f"V4 public asset SHA-256 mismatch: {uri}")
    return payload


def _verify_packaged_assets_and_receipts(
    package_root: Path,
    evidence: M2CPathBlockedPhysicalChainEvidenceV4,
) -> None:
    root = package_root.resolve(strict=True)
    for step in evidence.steps:
        for uri, expected_sha256 in (
            (step.observation.rgb_uri, step.observation.rgb_sha256),
            (step.observation.depth_uri, step.observation.depth_sha256),
        ):
            read_dataset_asset_v4(root, uri, expected_sha256)
        receipt = step.physical_receipts[0]
        receipt_path = (root / _dataset_relative_path(receipt.receipt_uri)).resolve(strict=True)
        if not receipt_path.is_relative_to(root):
            raise ValueError("V4 physical receipt escapes package root")
        receipt_raw = json.loads(_read_regular_file_once(receipt_path))
        if not isinstance(receipt_raw, dict):
            raise ValueError("V4 copied physical receipt is not an object")
        if receipt_raw != receipt.model_dump(mode="json"):
            raise ValueError("V4 copied physical receipt differs from bound chain receipt")


def _verify_collection_receipt_v4(
    package_root: Path,
    *,
    evidence: M2CPathBlockedPhysicalChainEvidenceV4,
    dataset: PathBlockedSupervisedDatasetV4,
    training_manifest: V4TrainingKeyManifest,
    s6_manifest: FrozenS6ExclusionManifestV2,
    source_raw: bytes,
    chain_raw: bytes,
    dataset_raw: bytes,
) -> bytes:
    root = package_root.resolve(strict=True)
    receipt_raw = _read_regular_file_once(root / "collection-receipt-v4.json")
    receipt = M2CQwenCoarseV4CollectionReceiptV1.model_validate_json(receipt_raw)
    source = json.loads(source_raw)
    raw_authorization_payload = source.get("m2c_v4_collection_authorization")
    if not isinstance(raw_authorization_payload, dict):
        raise ValueError("V4 source evidence lacks the consumed collection claim projection")
    raw_authorization = M2CS4V4RawClaimBindingV1.model_validate(raw_authorization_payload)
    raw_authorization_sha256 = canonical_sha256(raw_authorization_payload)
    raw_chain = source.get("m2c_path_blocked_physical_chain")
    if not isinstance(raw_chain, dict) or (
        raw_chain.get("collection_authorization_sha256") != raw_authorization_sha256
    ):
        raise ValueError("V4 source chain is not bound to its collection claim projection")
    console_raw = _read_regular_file_once(root / "console.log")
    prereg_raw = _read_regular_file_once(root / "collection-prereg-v4.json")
    claim_raw = _read_regular_file_once(root / "collection-claim-v4.json")
    prereg = M2CS4V4SelectedKeyCollectionPreregV1.model_validate_json(prereg_raw)
    claim = M2CS4V4CollectionConsumptionReceiptV1.model_validate_json(claim_raw)
    authorization = receipt.collection_authorization
    if (
        authorization.raw_claim_binding_sha256 != raw_authorization_sha256
        or authorization.raw_probe_sha256 != sha256_bytes(source_raw)
        or authorization.console_sha256 != sha256_bytes(console_raw)
        or authorization.consumption_receipt_sha256 != raw_authorization.consumption_receipt_sha256
        or authorization.consumption_id != raw_authorization.consumption_id
        or authorization.matched_key != raw_authorization.matched_key
        or authorization.committed_source_snapshot != raw_authorization.committed_source_snapshot
        or authorization.container_image_id != raw_authorization.container_image_id
        or sha256_bytes(prereg_raw) != raw_authorization.prereg_file_sha256
        or prereg.prereg_sha256 != raw_authorization.prereg_sha256
        or prereg.repository_relative_path != raw_authorization.prereg_repository_path
        or prereg.committed_source_snapshot != raw_authorization.committed_source_snapshot
        or claim.receipt_sha256 != raw_authorization.consumption_receipt_sha256
        or claim.consumption_id != raw_authorization.consumption_id
        or claim.challenge_nonce != raw_authorization.challenge_nonce
        or claim.prereg_file_sha256 != raw_authorization.prereg_file_sha256
        or claim.prereg_sha256 != raw_authorization.prereg_sha256
        or claim.prereg_introduced_commit != raw_authorization.prereg_introduced_commit
        or claim.selected_key.matched_key != raw_authorization.matched_key
        or claim.selected_key.failure_seed != raw_authorization.failure_seed
        or claim.source_sdf_sha256 != raw_authorization.source_sdf_sha256
        or claim.source_supervision_sha256 != raw_authorization.source_supervision_sha256
        or claim.source_urdf_sha256 != raw_authorization.source_urdf_sha256
        or claim.derived_probe_sha256 != raw_authorization.derived_probe_sha256
        or claim.container_image_id != raw_authorization.container_image_id
        or claim.destination_cell != raw_authorization.destination_cell
        or claim.committed_source_snapshot != raw_authorization.committed_source_snapshot
    ):
        raise ValueError("V4 packaged collection authorization differs from raw consumed claim")
    expected_assets = {
        f"{step.decision_index}:{kind}": digest
        for step in evidence.steps
        for kind, digest in (
            ("rgb", step.observation.rgb_sha256),
            ("depth", step.observation.depth_sha256),
        )
    }
    expected_receipts = {}
    for step in evidence.steps:
        physical = step.physical_receipts[0]
        path = (root / _dataset_relative_path(physical.receipt_uri)).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("V4 collection receipt physical asset escapes package root")
        expected_receipts[str(step.decision_index)] = M2CQwenCoarseV4CopiedReceiptRefV1(
            path=str(_dataset_relative_path(physical.receipt_uri)),
            file_sha256=sha256_bytes(_read_regular_file_once(path)),
            canonical_receipt_sha256=physical.receipt_sha256,
        )
    if receipt.copied_public_assets != expected_assets or receipt.physical_receipt_files != (
        expected_receipts
    ):
        raise ValueError("V4 collection receipt inventory differs from copied physical evidence")
    expected_identity = (
        evidence.matched_key,
        evidence.scene_seed,
        evidence.failure_seed,
        evidence.split,
        evidence.sdf_sha256,
        evidence.supervision_sha256,
    )
    receipt_identity = (
        receipt.matched_key,
        receipt.scene_seed,
        receipt.failure_seed,
        receipt.split,
        receipt.sdf_sha256,
        receipt.supervision_sha256,
    )
    raw_identity = (
        raw_authorization.matched_key,
        evidence.scene_seed,
        raw_authorization.failure_seed,
        raw_authorization.split,
        raw_authorization.source_sdf_sha256,
        raw_authorization.source_supervision_sha256,
    )
    s6_sha256 = canonical_sha256(s6_manifest.model_dump(mode="json"))
    expected_training_file_sha256 = v4_manifest_file_sha256(training_manifest)
    if (
        receipt_identity != expected_identity
        or raw_identity != expected_identity
        or receipt.raw_probe_sha256 != sha256_bytes(source_raw)
        or receipt.console_file_sha256 != sha256_bytes(console_raw)
        or receipt.packaged_physical_chain_sha256 != sha256_bytes(chain_raw)
        or receipt.supervised_dataset_file_sha256 != sha256_bytes(dataset_raw)
        or receipt.dataset_sha256 != dataset.dataset_sha256
        or receipt.collection_manifest_file_sha256 != expected_training_file_sha256
        or receipt.frozen_training_key_manifest_file_sha256 != expected_training_file_sha256
        or receipt.collection_manifest_sha256 != training_manifest.manifest_sha256
        or receipt.frozen_s6_key_manifest_file_sha256 != S6_MANIFEST_SHA256
        or receipt.s6_exclusion_manifest_sha256 != s6_sha256
        or receipt.runtime_registry_sha256 != evidence.runtime_registry_sha256
        or receipt.executing_probe_source_sha256
        != evidence.expected_association_deployment.capture_source_implementation_sha256
        or receipt.derived_probe_file_sha256 != raw_authorization.derived_probe_sha256
        or receipt.frozen_upstream_v4_probe_sha256 != raw_authorization.upstream_v4_probe_sha256
    ):
        raise ValueError("V4 collection receipt differs from independently replayed package")
    copied_manifest_raw = _read_regular_file_once(root / "collection-manifest-v4.json")
    copied_s6_raw = _read_regular_file_once(root / "s6-exclusion-manifest-v2.json")
    copied_manifest = load_v4_training_manifest(root / "collection-manifest-v4.json")
    _copied_s6_payload, copied_s6, _copied_s6_bytes = _load_frozen_s6_manifest(
        root / "s6-exclusion-manifest-v2.json"
    )
    if (
        sha256_bytes(copied_manifest_raw) != expected_training_file_sha256
        or sha256_bytes(copied_s6_raw) != S6_MANIFEST_SHA256
        or copied_manifest != training_manifest
        or copied_s6 != s6_manifest
    ):
        raise ValueError("V4 package contains substituted frozen manifests")
    return receipt_raw


def _replay_packaged_source(
    package_root: Path,
    evidence: M2CPathBlockedPhysicalChainEvidenceV4,
    *,
    training_manifest: V4TrainingKeyManifest,
) -> bytes:
    raw_path = package_root / "actuation-probe.json"
    raw_bytes = _read_regular_file_once(raw_path)
    if sha256_bytes(raw_bytes) != evidence.source_evidence_sha256:
        raise ValueError("V4 source evidence SHA-256 differs from packaged chain binding")
    payload = json.loads(raw_bytes)
    if not isinstance(payload, dict):
        raise ValueError("V4 source evidence is not an object")
    if payload.get("status") != "PASS" or payload.get("not_policy_rollout") is not True:
        raise ValueError("V4 source evidence is not a passing non-policy collection")
    if (
        payload.get("actuation_probe_source_sha256")
        != evidence.expected_association_deployment.capture_source_implementation_sha256
    ):
        raise ValueError("V4 source evidence executing probe differs from replay deployment")
    raw_chain = payload.get("m2c_path_blocked_physical_chain")
    raw_captures = payload.get("m2c_v4_raw_association_captures")
    if not isinstance(raw_chain, dict) or not isinstance(raw_captures, list):
        raise ValueError("V4 source evidence lacks raw chain or association captures")
    raw_steps = raw_chain.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) != len(evidence.steps):
        raise ValueError("V4 source evidence does not contain the packaged step count")
    for index, (raw_step, packaged_step) in enumerate(zip(raw_steps, evidence.steps, strict=True)):
        if not isinstance(raw_step, dict):
            raise ValueError(f"V4 raw step {index} is not an object")
        raw_receipts = raw_step.get("physical_receipts")
        if not isinstance(raw_receipts, list) or len(raw_receipts) != 1:
            raise ValueError(f"V4 raw step {index} does not have one physical receipt")
        raw_receipt = raw_receipts[0]
        if not isinstance(raw_receipt, dict):
            raise ValueError(f"V4 raw step {index} physical receipt is not an object")
        core = dict(raw_receipt)
        reported = core.pop("receipt_sha256", None)
        if reported != canonical_sha256(core):
            raise ValueError(f"V4 raw step {index} physical receipt digest mismatch")
        parsed = PathBlockedPhysicalSkillReceiptV2.model_validate(raw_receipt)
        if parsed != packaged_step.physical_receipts[0]:
            raise ValueError(f"V4 raw step {index} receipt differs from packaged evidence")
    keys = [
        item for item in training_manifest.training_keys if item.matched_key == evidence.matched_key
    ]
    if len(keys) != 1:
        raise ValueError("V4 source replay cannot resolve one frozen TRAIN key")
    replayed = host_replay_probe_chain_v4(
        raw_chain,
        raw_captures,
        training_key=keys[0],
        training_manifest=training_manifest,
        capture_source_implementation_sha256=(
            evidence.expected_association_deployment.capture_source_implementation_sha256
        ),
    )
    replayed_payload = replayed.model_dump(mode="json", exclude={"schema_version"})
    evidence_payload = evidence.model_dump(
        mode="json",
        exclude={
            "schema_version",
            "v4_training_manifest_ref",
            "s6_exclusion_manifest_sha256",
            "runtime_registry_sha256",
            "source_evidence_uri",
            "source_evidence_sha256",
        },
    )
    if replayed_payload != evidence_payload:
        raise ValueError("V4 packaged chain differs from independent raw-source replay")
    return raw_bytes


def load_training_packages_v4(
    package_roots: Sequence[Path],
    *,
    training_manifest_path: Path,
    evaluation_manifest_path: Path,
) -> tuple[list[M2CQwenCoarseV4TrainingSample], M2CQwenCoarseV4DatasetLoadReportV1]:
    if not package_roots:
        raise ValueError("BLOCKED_ZERO_ELIGIBLE_V4_PACKAGES")
    audit, training_manifest, s6_manifest = validate_key_manifests_v4(
        training_manifest_path,
        evaluation_manifest_path,
    )
    key_order = {
        item.matched_key: index for index, item in enumerate(training_manifest.training_keys)
    }
    parsed: list[
        tuple[
            int,
            Path,
            M2CPathBlockedPhysicalChainEvidenceV4,
            PathBlockedSupervisedDatasetV4,
            bytes,
            bytes,
            bytes,
            bytes,
        ]
    ] = []
    for requested_root in package_roots:
        root = requested_root.resolve(strict=True)
        chain_path = root / "packaged-physical-chain-v4.json"
        dataset_path = root / "supervised-steps-v4.json"
        chain_raw = _read_regular_file_once(chain_path)
        dataset_raw = _read_regular_file_once(dataset_path)
        evidence = M2CPathBlockedPhysicalChainEvidenceV4.model_validate_json(chain_raw)
        dataset = PathBlockedSupervisedDatasetV4.model_validate_json(dataset_raw)
        if evidence.matched_key not in key_order:
            raise ValueError("V4 package key is absent from the frozen TRAIN manifest")
        validation = validate_path_blocked_physical_evidence_v4(
            evidence,
            training_manifest=training_manifest,
            s6_manifest=s6_manifest,
        )
        if validation.status != "PASS_TRAIN" or not validation.model_training_eligible:
            raise ValueError("V4 package is not independently physical-training eligible")
        rebuilt = build_path_blocked_supervised_dataset_v4(
            evidence,
            training_manifest=training_manifest,
            s6_manifest=s6_manifest,
        )
        if dataset != rebuilt:
            raise ValueError("V4 supervised dataset differs from independently rebuilt labels")
        expected_dataset_sha256 = sha256_bytes(
            "".join(
                item.model_dump_json(exclude_none=False) + "\n" for item in dataset.samples
            ).encode("utf-8")
        )
        if dataset.status != "PASS" or dataset.dataset_sha256 != expected_dataset_sha256:
            raise ValueError("V4 supervised dataset digest/status mismatch")
        if len(dataset.samples) != 8:
            raise ValueError("V4 package does not contain exactly eight training samples")
        for sample in dataset.samples:
            validate_training_sample_v4(sample)
        source_raw = _replay_packaged_source(
            root,
            evidence,
            training_manifest=training_manifest,
        )
        _verify_packaged_assets_and_receipts(root, evidence)
        collection_receipt_raw = _verify_collection_receipt_v4(
            root,
            evidence=evidence,
            dataset=dataset,
            training_manifest=training_manifest,
            s6_manifest=s6_manifest,
            source_raw=source_raw,
            chain_raw=chain_raw,
            dataset_raw=dataset_raw,
        )
        parsed.append(
            (
                key_order[evidence.matched_key],
                root,
                evidence,
                dataset,
                source_raw,
                chain_raw,
                dataset_raw,
                collection_receipt_raw,
            )
        )
    parsed.sort(key=lambda item: item[0])
    rows = [sample for _, _, _, dataset, _, _, _, _ in parsed for sample in dataset.samples]
    if len({item.matched_key for item in rows}) != len(parsed):
        raise ValueError("V4 training input repeats a frozen matched key")
    if len({item.episode_id for item in rows}) != len(parsed):
        raise ValueError("V4 training input repeats an episode identity")
    sample_ids = [item.sample_id for item in rows]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("V4 training input repeats a sample identity")
    all_receipts = [item.physical_receipt_sha256 for item in rows]
    if len(all_receipts) != len(set(all_receipts)):
        raise ValueError("V4 training input reuses a physical receipt across packages")
    _validate_complete_episodes_v4(rows)
    combined = "".join(item.model_dump_json(exclude_none=False) + "\n" for item in rows).encode()
    package_refs = [
        M2CQwenCoarseV4PackageRefV1(
            package_root=str(root),
            matched_key=evidence.matched_key,
            episode_id=evidence.episode_id,
            source_evidence_file_sha256=sha256_bytes(source_raw),
            physical_chain_file_sha256=sha256_bytes(chain_raw),
            supervised_dataset_file_sha256=sha256_bytes(dataset_raw),
            collection_receipt_file_sha256=sha256_bytes(collection_receipt_raw),
            dataset_sha256=dataset.dataset_sha256,
        )
        for (
            _,
            root,
            evidence,
            dataset,
            source_raw,
            chain_raw,
            dataset_raw,
            collection_receipt_raw,
        ) in parsed
    ]
    return rows, M2CQwenCoarseV4DatasetLoadReportV1(
        status="PASS_REPLAYED_V4_TRAIN_DATA",
        combined_dataset_sha256=sha256_bytes(combined),
        rows_total=len(rows),
        eligible_episodes=len(parsed),
        packages=package_refs,
        key_manifest_audit=audit,
    )


def qwen_coarse_v4_prompt(
    sample: M2CQwenCoarseV4TrainingSample,
    *,
    executed_intent_history: list[PublicExecutedIntentHistoryItemV2],
    use_failure_context: bool,
) -> str:
    validate_training_sample_v4(sample)
    return render_qwen_public_prompt_v4(
        candidate_payload=sample.observation.candidate_payload,
        decision_index=sample.decision_index,
        executed_intent_history=executed_intent_history,
        use_failure_context=use_failure_context,
    )


@dataclass(frozen=True)
class NumpyThreeHeadsV4:
    skill_w: np.ndarray
    skill_b: np.ndarray
    pointer_w: np.ndarray
    pointer_b: np.ndarray
    destination_w: np.ndarray
    destination_b: np.ndarray

    @property
    def hidden_size(self) -> int:
        return int(self.skill_w.shape[0])

    def tensors(self) -> dict[str, np.ndarray]:
        return {
            "skill_w": self.skill_w,
            "skill_b": self.skill_b,
            "pointer_w": self.pointer_w,
            "pointer_b": self.pointer_b,
            "destination_w": self.destination_w,
            "destination_b": self.destination_b,
        }

    def logits(
        self,
        features: np.ndarray,
        valid_mask: Sequence[bool],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        vector = np.asarray(features, dtype=np.float64).reshape(-1)
        if vector.shape != (self.hidden_size,) or not np.isfinite(vector).all():
            raise ValueError("V4 pooled feature vector has the wrong shape/value")
        mask = np.asarray(valid_mask, dtype=bool).reshape(-1)
        if mask.shape != (PUBLIC_TRACK_CANDIDATE_COUNT_V4,):
            raise ValueError("V4 public pointer valid mask must have shape (8,)")
        skill = vector @ self.skill_w + self.skill_b
        pointer = vector @ self.pointer_w + self.pointer_b
        destination = vector @ self.destination_w + self.destination_b
        pointer = pointer.copy()
        pointer[:PUBLIC_TRACK_CANDIDATE_COUNT_V4][~mask] = -np.inf
        if not np.isfinite(skill).all() or not np.isfinite(destination).all():
            raise ValueError("V4 head produced non-finite logits")
        if not np.isfinite(pointer[-1]):
            raise ValueError("V4 pointer NONE logit is non-finite")
        return skill, pointer, destination


@dataclass(frozen=True)
class LoadedM2CQwenCoarseV4Bundle:
    manifest: M2CQwenCoarseV4BundleManifestV1
    heads: NumpyThreeHeadsV4


def initialize_numpy_heads_v4(hidden_size: int, seed: int) -> NumpyThreeHeadsV4:
    if hidden_size <= 0:
        raise ValueError("V4 hidden size must be positive")
    rng = np.random.default_rng(seed)

    def weight(classes: int) -> np.ndarray:
        scale = np.sqrt(2.0 / (hidden_size + classes))
        return rng.normal(0.0, scale, size=(hidden_size, classes))

    return NumpyThreeHeadsV4(
        skill_w=weight(len(SKILL_LABELS)),
        skill_b=np.zeros(len(SKILL_LABELS)),
        pointer_w=weight(PUBLIC_TRACK_POINTER_CLASS_COUNT_V4),
        pointer_b=np.zeros(PUBLIC_TRACK_POINTER_CLASS_COUNT_V4),
        destination_w=weight(len(DESTINATION_LABELS)),
        destination_b=np.zeros(len(DESTINATION_LABELS)),
    )


def checkpoint_binding_for_numpy_heads_v4(
    heads: NumpyThreeHeadsV4,
) -> M2CQ012CheckpointBindingV4:
    tensors = [
        M2CQ012TensorBindingV4(
            name=name,
            shape=list(value.shape),
            dtype=str(value.dtype),
            sha256=sha256_bytes(value.tobytes(order="C")),
        )
        for name, value in sorted(heads.tensors().items())
    ]
    payload = {
        "checkpoint_schema_version": "QRMFormalCheckpointV4",
        "architecture_revision": "M2C_Q012_V4",
        "public_observation_revision": "PathBlockedPublicObservationV4",
        "public_track_associator_revision": "PublicTrackAssociatorV2",
        "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
        "max_raw_public_detections": 32,
        "public_track_candidate_revision": "PublicTrackCandidateV4",
        "public_track_candidate_count": 8,
        "pointer_class_count": 9,
        "recapture_policy": "NONE",
        "tensors": [item.model_dump(mode="json") for item in tensors],
    }
    payload["metadata_sha256"] = canonical_sha256(payload)
    binding = M2CQ012CheckpointBindingV4.model_validate(payload)
    validate_head_checkpoint_binding_v4(binding, hidden_size=heads.hidden_size)
    return binding


def validate_head_checkpoint_binding_v4(
    binding: M2CQ012CheckpointBindingV4,
    *,
    hidden_size: int,
) -> None:
    expected_shapes = {
        "skill_w": [hidden_size, len(SKILL_LABELS)],
        "skill_b": [len(SKILL_LABELS)],
        "pointer_w": [hidden_size, PUBLIC_TRACK_POINTER_CLASS_COUNT_V4],
        "pointer_b": [PUBLIC_TRACK_POINTER_CLASS_COUNT_V4],
        "destination_w": [hidden_size, len(DESTINATION_LABELS)],
        "destination_b": [len(DESTINATION_LABELS)],
    }
    tensors = {item.name: item for item in binding.tensors}
    if tuple(sorted(tensors)) != HEAD_TENSOR_NAMES:
        raise ValueError("V4 coarse-head checkpoint tensor inventory is not exact")
    for name, shape in expected_shapes.items():
        tensor = tensors[name]
        if tensor.shape != shape or tensor.dtype not in {"float32", "float64"}:
            raise ValueError(f"V4 coarse-head checkpoint tensor layout differs: {name}")


def _write_new_file(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write while publishing V4 bundle")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def sha256_tree_v4(path: Path) -> str:
    root = path.resolve(strict=True)
    if not root.is_dir() or path.is_symlink():
        raise ValueError("V4 adapter root is not a real directory")
    files = sorted(item for item in root.rglob("*") if item.is_file())
    if not files:
        raise ValueError("V4 adapter tree is empty")
    digest = hashlib.sha256()
    for item in files:
        if item.is_symlink():
            raise ValueError("V4 adapter tree contains a symlink")
        info = item.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("V4 adapter tree contains a non-regular or linked file")
        relative = item.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(_read_regular_file_once(item)).digest())
    return digest.hexdigest()


def save_numpy_head_checkpoint_v4(
    path: Path,
    heads: NumpyThreeHeadsV4,
) -> tuple[M2CQ012CheckpointBindingV4, M2CQ012DeploymentManifestV4, bytes]:
    binding = checkpoint_binding_for_numpy_heads_v4(heads)
    buffer = __import__("io").BytesIO()
    np.savez(
        buffer,
        metadata_json=np.asarray(
            json.dumps(binding.model_dump(mode="json"), separators=(",", ":"))
        ),
        **heads.tensors(),
    )
    checkpoint_bytes = buffer.getvalue()
    _write_new_file(path, checkpoint_bytes)
    deployment_payload: dict[str, object] = {
        "schema_version": "M2CQ012DeploymentManifestV4",
        "architecture_revision": "M2C_Q012_V4",
        "checkpoint_file_sha256": sha256_bytes(checkpoint_bytes),
        "checkpoint_binding_sha256": canonical_checkpoint_binding_sha256_v4(binding),
    }
    deployment_payload["deployment_manifest_sha256"] = canonical_sha256(deployment_payload)
    deployment = M2CQ012DeploymentManifestV4.model_validate(deployment_payload)
    return binding, deployment, checkpoint_bytes


def write_bundle_manifest_v4(
    output_root: Path,
    *,
    heads: NumpyThreeHeadsV4,
    model_id: str,
    model_revision: str,
    base_model_snapshot_tree_sha256: str,
    failure_context: Literal["on", "off"],
    dataset_report: M2CQwenCoarseV4DatasetLoadReportV1,
    seed: int,
    optimizer_steps: int,
) -> M2CQwenCoarseV4BundleManifestV1:
    if optimizer_steps <= 0:
        raise ValueError("V4 trained bundle requires at least one optimizer step")
    if not re.fullmatch(SHA256_PATTERN, base_model_snapshot_tree_sha256):
        raise ValueError("V4 base-model snapshot tree SHA-256 is malformed")
    if not output_root.is_dir():
        raise FileNotFoundError("V4 output staging root does not exist")
    adapter_sha256 = sha256_tree_v4(output_root / "adapter")
    _, deployment, checkpoint_bytes = save_numpy_head_checkpoint_v4(
        output_root / HEAD_CHECKPOINT_NAME,
        heads,
    )
    deployment_bytes = M2CQwenCoarseV4BundleManifestV1._deployment_file_bytes(deployment)
    _write_new_file(output_root / HEAD_DEPLOYMENT_NAME, deployment_bytes)
    dataset_report_bytes = (
        json.dumps(dataset_report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_new_file(output_root / TRAINING_DATASET_REPORT_NAME, dataset_report_bytes)
    payload: dict[str, object] = {
        "schema_version": "M2CQwenCoarseV4BundleManifestV1",
        "status": "TRAINED_QWEN_LORA_M2C_Q012_V4",
        "architecture_revision": "M2C_Q012_V4",
        "public_observation_revision": "PathBlockedPublicObservationV4",
        "public_track_associator_revision": "PublicTrackAssociatorV2",
        "public_track_candidate_revision": "PublicTrackCandidateV4",
        "model_id": model_id,
        "model_revision": model_revision,
        "base_model_snapshot_tree_sha256": base_model_snapshot_tree_sha256,
        "failure_context": failure_context,
        "adapter_relative_path": "adapter",
        "adapter_tree_sha256": adapter_sha256,
        "head_checkpoint_relative_path": HEAD_CHECKPOINT_NAME,
        "head_checkpoint_sha256": sha256_bytes(checkpoint_bytes),
        "head_deployment_relative_path": HEAD_DEPLOYMENT_NAME,
        "head_deployment": deployment.model_dump(mode="json"),
        "head_deployment_file_sha256": sha256_bytes(deployment_bytes),
        "training_dataset_sha256": dataset_report.combined_dataset_sha256,
        "training_dataset_report_relative_path": TRAINING_DATASET_REPORT_NAME,
        "training_dataset_report_sha256": dataset_report_sha256_v4(dataset_report),
        "training_dataset_report_file_sha256": sha256_bytes(dataset_report_bytes),
        "training_manifest_file_sha256": (
            dataset_report.key_manifest_audit.training_manifest_file_sha256
        ),
        "training_manifest_sha256": dataset_report.key_manifest_audit.training_manifest_sha256,
        "s6_manifest_file_sha256": dataset_report.key_manifest_audit.s6_manifest_file_sha256,
        "s6_manifest_sha256": dataset_report.key_manifest_audit.s6_manifest_sha256,
        "seed": seed,
        "train_samples": dataset_report.rows_total,
        "train_episodes": dataset_report.eligible_episodes,
        "optimizer_steps": optimizer_steps,
        "training_complete": True,
        "physical_evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["bundle_sha256"] = M2CQwenCoarseV4BundleManifestV1._content_sha256(payload)
    manifest = M2CQwenCoarseV4BundleManifestV1.model_validate(payload)
    manifest_bytes = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_new_file(output_root / BUNDLE_MANIFEST_NAME, manifest_bytes)
    return manifest


def load_bundle_v4(
    output_root: Path,
    *,
    expected_bundle_sha256: str,
) -> LoadedM2CQwenCoarseV4Bundle:
    manifest = M2CQwenCoarseV4BundleManifestV1.model_validate_json(
        _read_regular_file_once(output_root / BUNDLE_MANIFEST_NAME)
    )
    if manifest.bundle_sha256 != expected_bundle_sha256:
        raise ValueError("V4 bundle differs from external expected digest")
    if sha256_tree_v4(output_root / manifest.adapter_relative_path) != manifest.adapter_tree_sha256:
        raise ValueError("V4 adapter tree SHA-256 mismatch")
    deployment_raw = _read_regular_file_once(output_root / manifest.head_deployment_relative_path)
    if sha256_bytes(deployment_raw) != manifest.head_deployment_file_sha256:
        raise ValueError("V4 deployment file SHA-256 mismatch")
    if M2CQ012DeploymentManifestV4.model_validate_json(deployment_raw) != manifest.head_deployment:
        raise ValueError("V4 deployment file differs from bundle manifest")
    dataset_report_raw = _read_regular_file_once(
        output_root / manifest.training_dataset_report_relative_path
    )
    if sha256_bytes(dataset_report_raw) != manifest.training_dataset_report_file_sha256:
        raise ValueError("V4 training dataset report file SHA-256 mismatch")
    dataset_report = M2CQwenCoarseV4DatasetLoadReportV1.model_validate_json(dataset_report_raw)
    if (
        dataset_report_sha256_v4(dataset_report) != manifest.training_dataset_report_sha256
        or dataset_report.combined_dataset_sha256 != manifest.training_dataset_sha256
        or dataset_report.rows_total != manifest.train_samples
        or dataset_report.eligible_episodes != manifest.train_episodes
        or dataset_report.key_manifest_audit.training_manifest_file_sha256
        != manifest.training_manifest_file_sha256
        or dataset_report.key_manifest_audit.training_manifest_sha256
        != manifest.training_manifest_sha256
        or dataset_report.key_manifest_audit.s6_manifest_file_sha256
        != manifest.s6_manifest_file_sha256
        or dataset_report.key_manifest_audit.s6_manifest_sha256 != manifest.s6_manifest_sha256
    ):
        raise ValueError("V4 training dataset report differs from bundle manifest")
    loaded = load_m2c_q012_checkpoint_v4(
        output_root / manifest.head_checkpoint_relative_path,
        expected_deployment=manifest.head_deployment,
        expected_deployment_manifest_sha256=(manifest.head_deployment.deployment_manifest_sha256),
    )
    arrays = loaded.tensors
    hidden_size = int(arrays["skill_w"].shape[0])
    validate_head_checkpoint_binding_v4(loaded.binding, hidden_size=hidden_size)
    heads = NumpyThreeHeadsV4(
        skill_w=arrays["skill_w"],
        skill_b=arrays["skill_b"],
        pointer_w=arrays["pointer_w"],
        pointer_b=arrays["pointer_b"],
        destination_w=arrays["destination_w"],
        destination_b=arrays["destination_b"],
    )
    return LoadedM2CQwenCoarseV4Bundle(manifest=manifest, heads=heads)


def run_offline_contract_smoke_v4(
    samples: Sequence[M2CQwenCoarseV4TrainingSample],
    *,
    hidden_size: int = 16,
    seed: int = 20260814,
) -> M2CQwenCoarseV4OfflineSmokeV1:
    if not samples:
        raise ValueError("V4 offline contract smoke requires real validated sample contracts")
    histories = index_executed_histories_v4(samples)
    heads = initialize_numpy_heads_v4(hidden_size, seed)
    binding = checkpoint_binding_for_numpy_heads_v4(heads)
    prompt_bytes = bytearray()
    last_shapes: tuple[list[int], list[int], list[int]] | None = None
    for sample in samples:
        prompt = qwen_coarse_v4_prompt(
            sample,
            executed_intent_history=histories[sample.sample_id],
            use_failure_context=True,
        )
        prompt_bytes.extend(prompt.encode("utf-8"))
        prompt_bytes.extend(b"\n")
        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        tiled = np.resize(np.frombuffer(digest, dtype=np.uint8), hidden_size)
        features = tiled.astype(np.float64) / 255.0
        logits = heads.logits(features, sample.observation.candidate_payload.valid_mask)
        last_shapes = tuple(list(item.shape) for item in logits)  # type: ignore[assignment]
    assert last_shapes is not None
    return M2CQwenCoarseV4OfflineSmokeV1(
        status="CONTRACT_SMOKE_PASS_NO_TRAINING",
        samples_checked=len(samples),
        prompts_sha256=sha256_bytes(bytes(prompt_bytes)),
        head_binding_sha256=canonical_sha256(binding.model_dump(mode="json")),
        skill_logits_shape=last_shapes[0],
        pointer_logits_shape=last_shapes[1],
        destination_logits_shape=last_shapes[2],
    )
