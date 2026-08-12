#!/usr/bin/env python3
"""Strict public-only contracts and three-head checkpointing for M2C Qwen V2.

This module is intentionally usable without torch, transformers, a GPU, or a
Qwen checkpoint.  Real LoRA training lives in ``train_qwen_coarse_v2.py`` and
imports heavy dependencies only after all dataset/governance gates pass.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.contracts import (
    FailureType,
    FailureContextV1,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.models_q012_v2 import (
    DESTINATION_LABELS,
    POINTER_LABELS,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
    prompt_executed_intent_history_v2,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import (
    PUBLIC_TRACK_ENCODING_REVISION,
    PUBLIC_TRACK_NORMALIZATION,
    PUBLIC_TRACK_POSE_FRAME,
    PUBLIC_TRACK_SLOT_COUNT,
    PUBLIC_TRACK_SLOT_FEATURE_NAMES,
    canonical_track_slots,
    encode_track_pointer_target,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
    M2C_Q012_V2_SKILL_LABELS,
    POINTER_CLASS_LABELS,
    M2CPathBlockedSupervisedStepV2,
    PathBlockedSupervisedDatasetV2,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SKILL_LABELS = M2C_Q012_V2_SKILL_LABELS
CHAIN_SKILLS = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)
HEAD_CHECKPOINT_NAME = "qwen_coarse_v2_heads.npz"
BUNDLE_MANIFEST_NAME = "qwen_coarse_v2_bundle.json"
MAX_TRAINING_WALL_SECONDS = 6 * 60 * 60


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


M2CQwenCoarseV2TrainingSample = M2CPathBlockedSupervisedStepV2


def canonical_slots_for_sample(
    sample: M2CQwenCoarseV2TrainingSample,
):
    observation = sample.observation
    if not observation.fresh or observation.source != "PUBLIC_RGBD":
        raise ValueError("Qwen training requires a fresh PUBLIC_RGBD observation")
    if observation.teacher_used or observation.privileged_truth_policy_input:
        raise ValueError("Qwen public observation contains forbidden inputs")
    slots = canonical_track_slots(
        observation.perception_tracks,
        k=PUBLIC_TRACK_SLOT_COUNT,
    )
    if list(slots.track_ids) != observation.canonical_slots:
        raise ValueError("canonical_slots differ from fresh public tracks")
    return slots


def runtime_observation_for_sample(
    sample: M2CQwenCoarseV2TrainingSample,
) -> QRMObservationV1:
    """Project the strict public receipt into the existing V2 runtime wire type."""

    canonical_slots_for_sample(sample)
    return QRMObservationV1(
        episode_id=sample.episode_id,
        step_id=sample.decision_index,
        timestamp_ns=sample.observation.captured_at_ns,
        instruction="recover from a public PATH_BLOCKED manipulation failure",
        rgb_uri=sample.observation.rgb_uri,
        depth_uri=sample.observation.depth_uri,
        current_skill_stage="RECOVERY",
        perception_tracks=sample.observation.perception_tracks,
        failure_context=FailureContextV1(failure_type=FailureType.PATH_BLOCKED),
    )


def validate_training_sample(
    sample: M2CQwenCoarseV2TrainingSample,
) -> None:
    if sample.teacher_used or sample.privileged_truth_policy_input:
        raise ValueError("Qwen sample contains Teacher or privileged truth")
    if SKILL_LABELS != tuple(M2C_Q012_V2_SKILL_LABELS):
        raise RuntimeError("Qwen skill label order differs from M2C_Q012_V2")
    if POINTER_LABELS != tuple(POINTER_CLASS_LABELS):
        raise RuntimeError("Qwen pointer label order differs from builder")
    if DESTINATION_LABELS != tuple(DESTINATION_CLASS_LABELS):
        raise RuntimeError("Qwen destination label order differs from builder")
    expected_skill = CHAIN_SKILLS[sample.decision_index]
    if sample.model_label.skill_type != expected_skill:
        raise ValueError(f"decision {sample.decision_index} requires {expected_skill}")
    if SKILL_LABELS[sample.skill_label_index] != sample.model_label.skill_type:
        raise ValueError("skill_label_index differs from CoarseIntentV2")
    slots = canonical_slots_for_sample(sample)
    pointer = encode_track_pointer_target(
        sample.model_label.target_track_id,
        slots,
    )
    if pointer != sample.pointer_class_index:
        raise ValueError("pointer_class_index differs from fresh K=8 slots")
    destination = sample.model_label.destination_cell or "NONE"
    if DESTINATION_LABELS.index(destination) != sample.destination_class_index:
        raise ValueError("destination_class_index differs from CoarseIntentV2")
    requires_pointer = sample.decision_index != 5
    if requires_pointer != (sample.model_label.target_track_id is not None):
        raise ValueError("chain pointer presence differs from decision contract")
    requires_destination = sample.decision_index in {2, 3}
    if requires_destination != (sample.model_label.destination_cell is not None):
        raise ValueError("chain destination presence differs from decision contract")
    if sample.model_label.failure_type_aux != FailureType.PATH_BLOCKED:
        raise ValueError("Qwen chain label is not PATH_BLOCKED")
    if sample.model_training_eligible and sample.exclusion_reasons:
        raise ValueError("eligible sample may not carry exclusion reasons")
    if not sample.model_training_eligible and not sample.exclusion_reasons:
        raise ValueError("ineligible sample requires exclusion reasons")


class KeyManifestAudit(StrictModel):
    schema_version: Literal["M2CQwenV2KeyManifestAuditV1"] = "M2CQwenV2KeyManifestAuditV1"
    training_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    evaluation_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    training_keys: list[str]
    smoke_keys: list[str]
    evaluation_keys: list[str]
    v4_excluded_keys: list[str]
    overlaps: list[str] = Field(default_factory=list)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class DatasetLoadReport(StrictModel):
    schema_version: Literal["M2CQwenV2DatasetLoadReportV1"] = "M2CQwenV2DatasetLoadReportV1"
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    rows_total: int = Field(ge=0)
    rows_eligible: int = Field(ge=0)
    rows_excluded: int = Field(ge=0)
    eligible_episodes: int = Field(ge=0)
    split_counts: dict[str, int]
    exclusion_reason_histogram: dict[str, int]
    dataset_manifest_path: str
    dataset_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_manifest_status: Literal["PASS", "PARTIAL"]
    key_manifest_audit: KeyManifestAudit
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def canonical_sha256(payload: object) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def sha256_tree(path: Path) -> str:
    if not path.is_dir():
        raise ValueError(f"adapter path is not a directory: {path}")
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise ValueError(f"adapter directory is empty: {path}")
    digest = hashlib.sha256()
    for item in files:
        if item.is_symlink():
            raise ValueError(f"adapter tree contains symlink: {item}")
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def _verified_manifest(path: Path, schema: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != schema:
        raise ValueError(f"unexpected frozen key manifest schema: {path}")
    embedded = payload.get("manifest_sha256")
    without_digest = dict(payload)
    without_digest.pop("manifest_sha256", None)
    if embedded != canonical_sha256(without_digest):
        raise ValueError(f"frozen key manifest digest mismatch: {path}")
    if payload.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION":
        raise ValueError(f"key manifest is not frozen: {path}")
    if payload.get("teacher_used") is not False:
        raise ValueError("key manifest permits Teacher use")
    if payload.get("privileged_truth_policy_input") is not False:
        raise ValueError("key manifest permits privileged policy input")
    return payload


def validate_key_manifests(
    training_manifest_path: Path,
    evaluation_manifest_path: Path,
) -> KeyManifestAudit:
    training = _verified_manifest(
        training_manifest_path,
        "M2CS4TrainingAndSmokeKeyManifestV1",
    )
    evaluation = _verified_manifest(
        evaluation_manifest_path,
        "M2CS6FrozenEvaluationKeyManifestV1",
    )
    if training.get("exclusions", {}).get("all_v4_keys") is not True:
        raise ValueError("training manifest does not exclude all V4 keys")
    if training.get("exclusions", {}).get("all_s6_keys") is not True:
        raise ValueError("training manifest does not exclude all S6 keys")
    if evaluation.get("excluded_from_all_training") is not True:
        raise ValueError("S6 manifest is not excluded from training")
    train_records = training.get("training_keys", [])
    smoke_records = training.get("physical_prerequisite_smoke_keys", [])
    evaluation_records = evaluation.get("evaluation_keys", [])
    if training.get("s6_evaluation_key_digest") != canonical_sha256(evaluation_records):
        raise ValueError("training manifest has the wrong S6 key digest")
    if evaluation.get("training_and_smoke_key_digest") != canonical_sha256(
        [*train_records, *smoke_records]
    ):
        raise ValueError("S6 manifest has the wrong train/smoke key digest")

    def keys(records: list[dict[str, Any]]) -> list[str]:
        result = [str(record["matched_key"]) for record in records]
        if len(result) != len(set(result)):
            raise ValueError("frozen manifest contains duplicate matched keys")
        return result

    train_keys = keys(train_records)
    smoke_keys = keys(smoke_records)
    evaluation_keys = keys(evaluation_records)
    v4_keys = [str(key) for key in training.get("v4_excluded_matched_keys", [])]
    overlaps = sorted(
        (set(train_keys) & set(smoke_keys))
        | (set(train_keys) & set(evaluation_keys))
        | (set(smoke_keys) & set(evaluation_keys))
        | ((set(train_keys) | set(smoke_keys)) & set(v4_keys))
    )
    train_seeds = {int(record["scene_seed"]) for record in train_records}
    smoke_seeds = {int(record["scene_seed"]) for record in smoke_records}
    evaluation_seeds = {int(record["scene_seed"]) for record in evaluation_records}
    v4_seeds = {int(seed) for seed in training.get("v4_excluded_scene_seeds", [])}
    if (
        train_seeds & smoke_seeds
        or train_seeds & evaluation_seeds
        or smoke_seeds & evaluation_seeds
        or (train_seeds | smoke_seeds) & v4_seeds
    ):
        overlaps.append("SCENE_SEED_OVERLAP")
    if overlaps:
        raise ValueError(f"frozen training/evaluation key overlap: {overlaps}")
    return KeyManifestAudit(
        training_manifest_sha256=sha256_file(training_manifest_path),
        evaluation_manifest_sha256=sha256_file(evaluation_manifest_path),
        training_keys=train_keys,
        smoke_keys=smoke_keys,
        evaluation_keys=evaluation_keys,
        v4_excluded_keys=v4_keys,
    )


def _validate_complete_episodes(
    samples: list[M2CQwenCoarseV2TrainingSample],
) -> None:
    by_episode: dict[str, list[M2CQwenCoarseV2TrainingSample]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    for episode_id, decisions in by_episode.items():
        ordered = sorted(decisions, key=lambda item: item.decision_index)
        indices = [item.decision_index for item in ordered]
        if indices != list(range(8)):
            raise ValueError(f"eligible episode {episode_id} is not a complete 8-step chain")
        invariant = {(item.split, item.split_group, item.matched_key) for item in ordered}
        if len(invariant) != 1:
            raise ValueError(f"episode {episode_id} changes split/group/key")
        timestamps = [item.observation.captured_at_ns for item in ordered]
        if any(after <= before for before, after in zip(timestamps, timestamps[1:])):
            raise ValueError(f"episode {episode_id} observations are not fresh")
        observation_ids = [item.observation.observation_id for item in ordered]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError(f"episode {episode_id} reuses an observation receipt")
        for item in ordered[:5]:
            if _target_public_color(item) != "red":
                raise ValueError(f"episode {episode_id} blocker is not the public red role")
        for item in ordered[6:]:
            if _target_public_color(item) != "yellow":
                raise ValueError(f"episode {episode_id} task target is not the public yellow role")
        destinations = {item.model_label.destination_cell for item in ordered[2:4]}
        if len(destinations) != 1:
            raise ValueError(f"episode {episode_id} changes destination cell")


def index_executed_histories(
    samples: list[M2CQwenCoarseV2TrainingSample],
) -> dict[str, list[PublicExecutedIntentHistoryItemV2]]:
    """Bind every sample to the exact same-episode executed public prefix."""

    _validate_complete_episodes(samples)
    by_episode: dict[str, list[M2CQwenCoarseV2TrainingSample]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    histories: dict[str, list[PublicExecutedIntentHistoryItemV2]] = {}
    for decisions in by_episode.values():
        ordered = sorted(decisions, key=lambda item: item.decision_index)
        prefix: list[PublicExecutedIntentHistoryItemV2] = []
        for sample in ordered:
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
                    execution_attribution=("SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"),
                )
            )
    if set(histories) != {sample.sample_id for sample in samples}:
        raise AssertionError("executed-intent history index is incomplete")
    return histories


def _target_public_color(sample: M2CQwenCoarseV2TrainingSample) -> str | None:
    track_id = sample.model_label.target_track_id
    if track_id is None:
        return None
    slots = canonical_slots_for_sample(sample)
    for track in slots.tracks:
        if track is None or track.track_id != track_id:
            continue
        tokens = (track.category or "").lower().replace("/", ":").split(":")
        colors = [color for color in ("red", "yellow") if color in tokens]
        return colors[0] if len(colors) == 1 else None
    return None


def load_training_dataset(
    dataset_path: Path,
    *,
    dataset_manifest_path: Path,
    training_manifest_path: Path,
    evaluation_manifest_path: Path,
) -> tuple[list[M2CQwenCoarseV2TrainingSample], DatasetLoadReport]:
    audit = validate_key_manifests(
        training_manifest_path,
        evaluation_manifest_path,
    )
    dataset_manifest = PathBlockedSupervisedDatasetV2.model_validate_json(
        dataset_manifest_path.read_text(encoding="utf-8")
    )
    if dataset_manifest.status not in {"PASS", "PARTIAL"}:
        raise ValueError("supervised dataset manifest is not usable")
    rows: list[M2CQwenCoarseV2TrainingSample] = []
    for line_number, line in enumerate(
        dataset_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            sample = M2CQwenCoarseV2TrainingSample.model_validate_json(line)
            validate_training_sample(sample)
            rows.append(sample)
        except Exception as error:
            raise ValueError(f"invalid Qwen V2 training row {line_number}: {error}") from error
    if not rows:
        raise ValueError("Qwen V2 training dataset is empty")
    sample_ids = [sample.sample_id for sample in rows]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Qwen V2 dataset contains duplicate sample IDs")
    eligible = [sample for sample in rows if sample.model_training_eligible]
    if not eligible:
        raise ValueError("Qwen V2 dataset has zero eligible samples")
    canonical_dataset_payload = "".join(
        sample.model_dump_json(by_alias=False, exclude_none=False) + "\n" for sample in rows
    ).encode("utf-8")
    canonical_dataset_sha256 = sha256_bytes(canonical_dataset_payload)
    if dataset_manifest.dataset_sha256 != canonical_dataset_sha256:
        raise ValueError("supervised dataset manifest digest differs from JSONL")
    if dataset_manifest.samples != rows:
        raise ValueError("supervised dataset manifest samples differ from JSONL")
    if dataset_manifest.samples_training_eligible != len(eligible):
        raise ValueError("supervised manifest eligible-sample count mismatch")
    if dataset_manifest.episodes_training_eligible != len(
        {sample.episode_id for sample in eligible}
    ):
        raise ValueError("supervised manifest eligible-episode count mismatch")
    allowed_by_split = {
        "train": set(audit.training_keys),
        "val": set(audit.smoke_keys),
    }
    forbidden = set(audit.evaluation_keys) | set(audit.v4_excluded_keys)
    for sample in rows:
        if sample.split == "test":
            raise ValueError("S6/test sample may not enter a Q-B training dataset")
        if sample.matched_key in forbidden:
            raise ValueError(f"sample overlaps frozen evaluation: {sample.matched_key}")
        if sample.matched_key not in allowed_by_split[sample.split]:
            raise ValueError(
                f"sample is absent from frozen {sample.split} keys: {sample.matched_key}"
            )
    if any(sample.split != "train" for sample in eligible):
        raise ValueError(
            "eligible non-train rows are not authorized; frozen SMOKE keys "
            "are physical prerequisites, not training validation data"
        )
    group_splits: dict[str, set[str]] = {}
    key_splits: dict[str, set[str]] = {}
    for sample in eligible:
        group_splits.setdefault(sample.split_group, set()).add(sample.split)
        key_splits.setdefault(sample.matched_key, set()).add(sample.split)
    if any(len(splits) != 1 for splits in group_splits.values()):
        raise ValueError("split_group leakage across train/val")
    if any(len(splits) != 1 for splits in key_splits.values()):
        raise ValueError("matched key leakage across train/val")
    receipt_hashes = [sample.physical_receipt_sha256 for sample in eligible]
    if len(receipt_hashes) != len(set(receipt_hashes)):
        raise ValueError("eligible decisions reuse a physical execution receipt")
    _validate_complete_episodes(eligible)

    split_counts = {
        split: sum(sample.split == split for sample in eligible) for split in ("train", "val")
    }
    histogram: dict[str, int] = {}
    for sample in rows:
        if sample.model_training_eligible:
            continue
        for reason in sample.exclusion_reasons:
            histogram[reason] = histogram.get(reason, 0) + 1
    report = DatasetLoadReport(
        dataset_sha256=sha256_file(dataset_path),
        rows_total=len(rows),
        rows_eligible=len(eligible),
        rows_excluded=len(rows) - len(eligible),
        eligible_episodes=len({sample.episode_id for sample in eligible}),
        split_counts=split_counts,
        exclusion_reason_histogram=dict(sorted(histogram.items())),
        dataset_manifest_path=str(dataset_manifest_path),
        dataset_manifest_sha256=sha256_file(dataset_manifest_path),
        dataset_manifest_status=dataset_manifest.status,
        key_manifest_audit=audit,
    )
    return eligible, report


def resolve_dataset_asset(
    dataset_root: Path,
    uri: str,
    expected_sha256: str,
) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported public asset URI: {uri}")
    relative = Path(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"public asset URI escapes dataset root: {uri}")
    path = dataset_root / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"public asset SHA-256 mismatch for {uri}: {actual} != {expected_sha256}")
    return path


def qwen_coarse_v2_prompt(
    sample: M2CQwenCoarseV2TrainingSample,
    *,
    executed_intent_history: list[PublicExecutedIntentHistoryItemV2],
    use_failure_context: bool,
) -> str:
    slots = canonical_slots_for_sample(sample)
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
    path_blocked_context = (
        {"failure_type": "PATH_BLOCKED"} if use_failure_context else {"failure_type": "MASKED"}
    )
    payload = {
        "task": "recover from a public PATH_BLOCKED manipulation failure",
        "canonical_public_track_slots_k8": public_tracks,
        "valid_mask": slots.valid_mask.tolist(),
        "failure_context": path_blocked_context,
        "public_executed_intent_history": prompt_executed_intent_history_v2(
            executed_intent_history,
            expected_length=sample.decision_index,
        ),
        "allowed_skills": list(SKILL_LABELS),
        "allowed_pointer_classes": list(POINTER_LABELS),
        "allowed_destinations": list(DESTINATION_LABELS),
    }
    return (
        "Select one CoarseIntentV2 skill, one literal K=8 public-track "
        "pointer (or NONE), and one registered destination cell (or NONE). "
        "Continuous coordinates and simulator truth are unavailable. Context:\n"
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


@dataclass
class NumpyThreeHeadsV2:
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
        valid_mask: list[bool] | np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = np.asarray(features, dtype=np.float64).reshape(-1)
        if x.shape != (self.hidden_size,) or not np.isfinite(x).all():
            raise ValueError("Qwen pooled feature vector has the wrong shape/value")
        mask = np.asarray(valid_mask, dtype=bool).reshape(-1)
        if mask.shape != (PUBLIC_TRACK_SLOT_COUNT,):
            raise ValueError("public pointer valid mask must have shape (8,)")
        skill = x @ self.skill_w + self.skill_b
        pointer = x @ self.pointer_w + self.pointer_b
        destination = x @ self.destination_w + self.destination_b
        pointer = pointer.copy()
        pointer[:PUBLIC_TRACK_SLOT_COUNT][~mask] = -np.inf
        if not np.isfinite(skill).all() or not np.isfinite(destination).all():
            raise ValueError("Qwen V2 head produced non-finite logits")
        if not np.isfinite(pointer[-1]):
            raise ValueError("Qwen V2 pointer NONE logit is non-finite")
        return skill, pointer, destination


def initialize_numpy_heads(hidden_size: int, seed: int) -> NumpyThreeHeadsV2:
    if hidden_size <= 0:
        raise ValueError("Qwen hidden size must be positive")
    rng = np.random.default_rng(seed)

    def weight(classes: int) -> np.ndarray:
        scale = np.sqrt(2.0 / (hidden_size + classes))
        return rng.normal(0.0, scale, size=(hidden_size, classes))

    return NumpyThreeHeadsV2(
        skill_w=weight(len(SKILL_LABELS)),
        skill_b=np.zeros(len(SKILL_LABELS)),
        pointer_w=weight(len(POINTER_LABELS)),
        pointer_b=np.zeros(len(POINTER_LABELS)),
        destination_w=weight(len(DESTINATION_LABELS)),
        destination_b=np.zeros(len(DESTINATION_LABELS)),
    )


class QwenV2HeadCheckpointMetadata(StrictModel):
    schema_version: Literal["M2CQwenCoarseV2HeadCheckpointV1"] = "M2CQwenCoarseV2HeadCheckpointV1"
    architecture_revision: Literal["M2C_Q012_V2"] = "M2C_Q012_V2"
    model_id: str = Field(min_length=1)
    model_revision: str
    hidden_size: int = Field(gt=0)
    failure_context: Literal["on", "off"]
    skill_labels: list[str]
    pointer_labels: list[str]
    destination_labels: list[str]
    public_track_slot_count: Literal[8] = 8
    public_track_slot_feature_dim: Literal[13] = 13
    qwen_track_representation: Literal["LITERAL_TRACK_ID_IN_PROMPT"] = "LITERAL_TRACK_ID_IN_PROMPT"
    qwen_slot_feature_transport: Literal["PUBLIC_FIELDS_SERIALIZED_IN_CANONICAL_K8_PROMPT"] = (
        "PUBLIC_FIELDS_SERIALIZED_IN_CANONICAL_K8_PROMPT"
    )
    public_track_slot_feature_names: list[str]
    public_track_encoding_revision: str
    public_track_pose_frame: str
    public_track_normalization: str
    executed_intent_history_schema: Literal["PublicExecutedIntentHistoryItemV2"] = (
        "PublicExecutedIntentHistoryItemV2"
    )
    executed_intent_history_training_attribution: Literal[
        "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    ] = "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    executed_intent_history_prompt_attribution: Literal["EXECUTED_PHYSICAL_SKILL"] = (
        "EXECUTED_PHYSICAL_SKILL"
    )
    executed_intent_history_exact_prior_prefix: Literal[True] = True
    current_decision_index_exposed_in_prompt: Literal[False] = False
    expected_next_skill_exposed_in_prompt: Literal[False] = False
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    training_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    evaluation_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    seed: int
    initialization_source: Literal[
        "NONE",
        "M2B_ADAPTER_INITIALIZATION_ONLY",
        "OFFLINE_SMOKE_DETERMINISTIC_FEATURES",
    ]
    initialization_adapter_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    adapter_source_architecture_revision: str | None = None
    tensor_shapes: dict[str, list[int]]
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    flow_status: Literal["DISABLED"] = "DISABLED"

    @model_validator(mode="after")
    def metadata_is_exact(self) -> "QwenV2HeadCheckpointMetadata":
        if self.skill_labels != list(SKILL_LABELS):
            raise ValueError("Qwen V2 skill label order changed")
        if self.pointer_labels != list(POINTER_LABELS):
            raise ValueError("Qwen V2 pointer label order changed")
        if self.destination_labels != list(DESTINATION_LABELS):
            raise ValueError("Qwen V2 destination label order changed")
        if self.public_track_slot_feature_names != list(PUBLIC_TRACK_SLOT_FEATURE_NAMES):
            raise ValueError("Qwen V2 public slot feature order changed")
        if self.public_track_encoding_revision != PUBLIC_TRACK_ENCODING_REVISION:
            raise ValueError("Qwen V2 public track encoding revision changed")
        if self.public_track_pose_frame != PUBLIC_TRACK_POSE_FRAME:
            raise ValueError("Qwen V2 public track pose frame changed")
        if self.public_track_normalization != PUBLIC_TRACK_NORMALIZATION:
            raise ValueError("Qwen V2 public track normalization changed")
        if self.initialization_source == "M2B_ADAPTER_INITIALIZATION_ONLY":
            if self.initialization_adapter_sha256 is None:
                raise ValueError("M2B initialization requires adapter SHA-256")
            if self.adapter_source_architecture_revision != "M2B_Q012_V1":
                raise ValueError("M2B initialization architecture is not recorded")
        elif (
            self.initialization_adapter_sha256 is not None
            or self.adapter_source_architecture_revision is not None
        ):
            raise ValueError("unexpected initialization adapter metadata")
        expected = expected_head_shapes(self.hidden_size)
        if self.tensor_shapes != {name: list(shape) for name, shape in expected.items()}:
            raise ValueError("Qwen V2 tensor shape metadata changed")
        return self


def expected_head_shapes(hidden_size: int) -> dict[str, tuple[int, ...]]:
    return {
        "skill_w": (hidden_size, len(SKILL_LABELS)),
        "skill_b": (len(SKILL_LABELS),),
        "pointer_w": (hidden_size, len(POINTER_LABELS)),
        "pointer_b": (len(POINTER_LABELS),),
        "destination_w": (hidden_size, len(DESTINATION_LABELS)),
        "destination_b": (len(DESTINATION_LABELS),),
    }


def build_head_metadata(
    *,
    model_id: str,
    model_revision: str,
    hidden_size: int,
    failure_context: Literal["on", "off"],
    dataset_sha256: str,
    dataset_manifest_sha256: str,
    training_manifest_sha256: str,
    evaluation_manifest_sha256: str,
    seed: int,
    initialization_source: Literal[
        "NONE",
        "M2B_ADAPTER_INITIALIZATION_ONLY",
        "OFFLINE_SMOKE_DETERMINISTIC_FEATURES",
    ],
    initialization_adapter_sha256: str | None = None,
    adapter_source_architecture_revision: str | None = None,
) -> QwenV2HeadCheckpointMetadata:
    return QwenV2HeadCheckpointMetadata(
        model_id=model_id,
        model_revision=model_revision,
        hidden_size=hidden_size,
        failure_context=failure_context,
        skill_labels=list(SKILL_LABELS),
        pointer_labels=list(POINTER_LABELS),
        destination_labels=list(DESTINATION_LABELS),
        public_track_slot_feature_names=list(PUBLIC_TRACK_SLOT_FEATURE_NAMES),
        public_track_encoding_revision=PUBLIC_TRACK_ENCODING_REVISION,
        public_track_pose_frame=PUBLIC_TRACK_POSE_FRAME,
        public_track_normalization=PUBLIC_TRACK_NORMALIZATION,
        dataset_sha256=dataset_sha256,
        dataset_manifest_sha256=dataset_manifest_sha256,
        training_manifest_sha256=training_manifest_sha256,
        evaluation_manifest_sha256=evaluation_manifest_sha256,
        seed=seed,
        initialization_source=initialization_source,
        initialization_adapter_sha256=initialization_adapter_sha256,
        adapter_source_architecture_revision=adapter_source_architecture_revision,
        tensor_shapes={
            name: list(shape) for name, shape in expected_head_shapes(hidden_size).items()
        },
    )


def save_head_checkpoint(
    path: Path,
    heads: NumpyThreeHeadsV2,
    metadata: QwenV2HeadCheckpointMetadata,
) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite head checkpoint: {path}")
    expected = expected_head_shapes(metadata.hidden_size)
    tensors = heads.tensors()
    for name, shape in expected.items():
        value = np.asarray(tensors[name])
        if value.shape != shape:
            raise ValueError(f"Qwen V2 tensor {name} has shape {value.shape}")
        if not np.issubdtype(value.dtype, np.number) or not np.isfinite(value).all():
            raise ValueError(f"Qwen V2 tensor {name} is nonnumeric/nonfinite")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        metadata_json=metadata.model_dump_json(),
        **tensors,
    )


def load_head_checkpoint(
    path: Path,
    *,
    expected_model_id: str | None = None,
    expected_model_revision: str | None = None,
    expected_dataset_sha256: str | None = None,
) -> tuple[NumpyThreeHeadsV2, QwenV2HeadCheckpointMetadata]:
    expected_keys = {"metadata_json", *expected_head_shapes(1)}
    with np.load(path, allow_pickle=False) as payload:
        keys = set(payload.files)
        if keys != expected_keys:
            raise ValueError(
                "Qwen V2 head checkpoint fields mismatch: "
                f"missing={sorted(expected_keys - keys)}, "
                f"unknown={sorted(keys - expected_keys)}"
            )
        raw = np.asarray(payload["metadata_json"])
        if raw.shape != ():
            raise ValueError("Qwen V2 metadata_json must be scalar")
        metadata = QwenV2HeadCheckpointMetadata.model_validate_json(str(raw.item()))
        if expected_model_id is not None and metadata.model_id != expected_model_id:
            raise ValueError("Qwen V2 checkpoint model ID mismatch")
        if (
            expected_model_revision is not None
            and metadata.model_revision != expected_model_revision
        ):
            raise ValueError("Qwen V2 checkpoint model revision mismatch")
        if (
            expected_dataset_sha256 is not None
            and metadata.dataset_sha256 != expected_dataset_sha256
        ):
            raise ValueError("Qwen V2 checkpoint dataset SHA-256 mismatch")
        tensors: dict[str, np.ndarray] = {}
        for name, shape in expected_head_shapes(metadata.hidden_size).items():
            value = np.asarray(payload[name])
            if value.shape != shape:
                raise ValueError(
                    f"Qwen V2 checkpoint tensor {name} shape mismatch: {value.shape} != {shape}"
                )
            if not np.issubdtype(value.dtype, np.number):
                raise ValueError(f"Qwen V2 checkpoint tensor {name} is not numeric")
            if not np.isfinite(value).all():
                raise ValueError(f"Qwen V2 checkpoint tensor {name} is non-finite")
            tensors[name] = value.astype(np.float64, copy=True)
    return NumpyThreeHeadsV2(**tensors), metadata


class QwenV2BundleManifest(StrictModel):
    schema_version: Literal["M2CQwenCoarseV2BundleManifestV1"] = "M2CQwenCoarseV2BundleManifestV1"
    status: Literal[
        "TRAINED_QWEN_LORA_THREE_HEADS",
        "OFFLINE_SMOKE_ONLY_NOT_QB_EVALUATION",
    ]
    head_checkpoint: Literal["qwen_coarse_v2_heads.npz"] = "qwen_coarse_v2_heads.npz"
    head_checkpoint_sha256: str = Field(pattern=SHA256_PATTERN)
    adapter_path: Literal["adapter"] | None = None
    adapter_tree_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    physical_evaluation_executed: Literal[False] = False

    @model_validator(mode="after")
    def adapter_matches_status(self) -> "QwenV2BundleManifest":
        trained = self.status == "TRAINED_QWEN_LORA_THREE_HEADS"
        if trained != (self.adapter_path == "adapter"):
            raise ValueError("trained bundle must name its adapter directory")
        if trained != (self.adapter_tree_sha256 is not None):
            raise ValueError("trained bundle must hash its adapter tree")
        return self


def write_bundle_manifest(
    output_root: Path,
    *,
    status: Literal[
        "TRAINED_QWEN_LORA_THREE_HEADS",
        "OFFLINE_SMOKE_ONLY_NOT_QB_EVALUATION",
    ],
) -> QwenV2BundleManifest:
    head_path = output_root / HEAD_CHECKPOINT_NAME
    adapter_path = output_root / "adapter"
    manifest = QwenV2BundleManifest(
        status=status,
        head_checkpoint_sha256=sha256_file(head_path),
        adapter_path=("adapter" if status == "TRAINED_QWEN_LORA_THREE_HEADS" else None),
        adapter_tree_sha256=(
            sha256_tree(adapter_path) if status == "TRAINED_QWEN_LORA_THREE_HEADS" else None
        ),
    )
    destination = output_root / BUNDLE_MANIFEST_NAME
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle manifest: {destination}")
    destination.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_bundle(
    output_root: Path,
    *,
    require_adapter: bool,
    expected_model_id: str | None = None,
    expected_model_revision: str | None = None,
) -> tuple[
    NumpyThreeHeadsV2,
    QwenV2HeadCheckpointMetadata,
    QwenV2BundleManifest,
]:
    manifest = QwenV2BundleManifest.model_validate_json(
        (output_root / BUNDLE_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    if require_adapter and manifest.status != "TRAINED_QWEN_LORA_THREE_HEADS":
        raise ValueError("offline smoke bundle has no Qwen LoRA adapter")
    head_path = output_root / manifest.head_checkpoint
    if sha256_file(head_path) != manifest.head_checkpoint_sha256:
        raise ValueError("Qwen V2 head checkpoint hash differs from bundle manifest")
    if manifest.adapter_path is not None:
        adapter = output_root / manifest.adapter_path
        if sha256_tree(adapter) != manifest.adapter_tree_sha256:
            raise ValueError("Qwen V2 adapter tree hash differs from bundle manifest")
    heads, metadata = load_head_checkpoint(
        head_path,
        expected_model_id=expected_model_id,
        expected_model_revision=expected_model_revision,
    )
    return heads, metadata, manifest


def deterministic_smoke_features(
    sample: M2CQwenCoarseV2TrainingSample,
    hidden_size: int,
    *,
    executed_intent_history: list[PublicExecutedIntentHistoryItemV2],
    use_failure_context: bool,
) -> np.ndarray:
    prompt = qwen_coarse_v2_prompt(
        sample,
        executed_intent_history=executed_intent_history,
        use_failure_context=use_failure_context,
    )
    seed_bytes = hashlib.sha256((prompt + "\0" + sample.observation.rgb_sha256).encode()).digest()
    seed = int.from_bytes(seed_bytes[:8], "little", signed=False)
    return np.random.default_rng(seed).normal(0.0, 1.0, size=hidden_size)


def _softmax(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        raise ValueError("all head logits are masked/non-finite")
    maximum = np.max(values[finite])
    exponent = np.zeros_like(values)
    exponent[finite] = np.exp(values[finite] - maximum)
    return exponent / exponent.sum()


def _update_head(
    features: np.ndarray,
    logits: np.ndarray,
    target: int,
    weight: np.ndarray,
    bias: np.ndarray,
    learning_rate: float,
) -> float:
    probabilities = _softmax(logits)
    loss = -float(np.log(max(probabilities[target], 1e-300)))
    gradient = probabilities
    gradient[target] -= 1.0
    weight -= learning_rate * np.outer(features, gradient)
    bias -= learning_rate * gradient
    return loss


def run_offline_smoke(
    samples: list[M2CQwenCoarseV2TrainingSample],
    *,
    output_root: Path,
    dataset_report: DatasetLoadReport,
    seed: int,
    failure_context: Literal["on", "off"],
    hidden_size: int = 16,
    sample_count: int = 5,
) -> dict[str, Any]:
    if sample_count != 5:
        raise ValueError("offline smoke is frozen to exactly five samples")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite smoke output: {output_root}")
    if len(samples) < sample_count:
        raise ValueError("offline smoke requires at least five eligible samples")
    selected = samples[:sample_count]
    output_root.mkdir(parents=True)
    heads = initialize_numpy_heads(hidden_size, seed)
    initial = {name: value.copy() for name, value in heads.tensors().items()}
    losses: list[float] = []
    use_fc = failure_context == "on"
    histories = index_executed_histories(samples)
    for sample in selected:
        features = deterministic_smoke_features(
            sample,
            hidden_size,
            executed_intent_history=histories[sample.sample_id],
            use_failure_context=use_fc,
        )
        skill, pointer, destination = heads.logits(
            features,
            canonical_slots_for_sample(sample).valid_mask,
        )
        losses.extend(
            [
                _update_head(
                    features,
                    skill,
                    sample.skill_label_index,
                    heads.skill_w,
                    heads.skill_b,
                    1e-3,
                ),
                _update_head(
                    features,
                    pointer,
                    sample.pointer_class_index,
                    heads.pointer_w,
                    heads.pointer_b,
                    1e-3,
                ),
                _update_head(
                    features,
                    destination,
                    sample.destination_class_index,
                    heads.destination_w,
                    heads.destination_b,
                    1e-3,
                ),
            ]
        )
    metadata = build_head_metadata(
        model_id="SMOKE_ONLY_NO_QWEN_MODEL",
        model_revision="NOT_LOADED",
        hidden_size=hidden_size,
        failure_context=failure_context,
        dataset_sha256=dataset_report.dataset_sha256,
        dataset_manifest_sha256=dataset_report.dataset_manifest_sha256,
        training_manifest_sha256=(dataset_report.key_manifest_audit.training_manifest_sha256),
        evaluation_manifest_sha256=(dataset_report.key_manifest_audit.evaluation_manifest_sha256),
        seed=seed,
        initialization_source="OFFLINE_SMOKE_DETERMINISTIC_FEATURES",
    )
    save_head_checkpoint(output_root / HEAD_CHECKPOINT_NAME, heads, metadata)
    bundle = write_bundle_manifest(
        output_root,
        status="OFFLINE_SMOKE_ONLY_NOT_QB_EVALUATION",
    )
    reloaded, reloaded_metadata, reloaded_bundle = load_bundle(
        output_root,
        require_adapter=False,
        expected_model_id="SMOKE_ONLY_NO_QWEN_MODEL",
        expected_model_revision="NOT_LOADED",
    )
    if reloaded_metadata != metadata or reloaded_bundle != bundle:
        raise AssertionError("offline smoke checkpoint metadata did not round-trip")
    for name, value in heads.tensors().items():
        if not np.array_equal(value, reloaded.tensors()[name]):
            raise AssertionError(f"offline smoke tensor {name} did not reload exactly")
    update_l2 = (
        sum(
            float(np.square(value - initial[name]).sum()) for name, value in heads.tensors().items()
        )
        ** 0.5
    )
    if update_l2 <= 0.0:
        raise AssertionError("offline smoke three-head update was zero")
    return {
        "schema_version": "M2CQwenCoarseV2OfflineSmokeReportV1",
        "status": "PASS_OFFLINE_SMOKE_ONLY_NOT_QB_EVALUATION",
        "samples": sample_count,
        "heads_exercised": ["skill", "pointer", "destination"],
        "mean_loss": sum(losses) / len(losses),
        "head_update_l2": update_l2,
        "checkpoint_reload_exact": True,
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "dataset_sha256": dataset_report.dataset_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "qwen_model_loaded": False,
        "training_claimed": False,
        "physical_evaluation_executed": False,
    }


def classification_metrics(
    truth: list[int],
    predicted: list[int],
    labels: tuple[str, ...],
) -> dict[str, Any]:
    if len(truth) != len(predicted):
        raise ValueError("truth/prediction lengths differ")
    per_class: dict[str, dict[str, float | int]] = {}
    for index, label in enumerate(labels):
        tp = sum(t == index and p == index for t, p in zip(truth, predicted))
        fp = sum(t != index and p == index for t, p in zip(truth, predicted))
        fn = sum(t == index and p != index for t, p in zip(truth, predicted))
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        per_class[label] = {
            "support": sum(t == index for t in truth),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "accuracy": sum(t == p for t, p in zip(truth, predicted)) / max(len(truth), 1),
        "macro_f1": sum(float(item["f1"]) for item in per_class.values()) / len(labels),
        "per_class": per_class,
    }
