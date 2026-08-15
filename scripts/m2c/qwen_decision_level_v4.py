#!/usr/bin/env python3
"""Load ADR-0026 decision-level V4 supervision for Qwen training.

This is an offline contract boundary.  It does not update weights.  It keeps
V3 and V4 separate, verifies the checked-in packaging report, replays every
V4 row and public RGB-D asset from the external evidence roots, and exposes
per-head loss masks for a later real trainer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Literal, Sequence

import numpy as np
from pydantic import Field, model_validator

from m2c.qwen_coarse_v4 import (
    DESTINATION_LABELS,
    HEAD_CHECKPOINT_NAME,
    HEAD_DEPLOYMENT_NAME,
    POINTER_LABELS,
    SKILL_LABELS,
    M2CQwenCoarseV4KeyManifestAuditV1,
    NumpyThreeHeadsV4,
    canonical_slots_for_sample_v4,
    initialize_numpy_heads_v4,
    save_numpy_head_checkpoint_v4,
    sha256_tree_v4,
    validate_key_manifests_v4,
    validate_head_checkpoint_binding_v4,
)
from xh_agent.policy.qrm_lite.contracts import FailureType
from xh_agent.policy.qrm_lite.decision_level_supervision_v1 import (
    ADR0026_PATH,
    ADR0026_SHA256,
    BoundEvidenceFileV1,
    M2CS4DecisionLevelDatasetManifestV1,
    M2CS4DecisionLevelSupervisionRowV1,
    M2CS4DecisionLevelTrainingSampleV1,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import EXPECTED_PATH_BLOCKED_CHAIN
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    M2CQ012DeploymentManifestV4,
    PathBlockedPublicObservationV4,
    load_m2c_q012_checkpoint_v4,
    recompute_candidate_payload_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    encode_track_pointer_target_v4,
)
from xh_agent.policy.qrm_lite.qwen_prompt_v4 import render_qwen_public_prompt_v4
from xh_agent.policy.qrm_lite.contracts import StrictModel


ROOT = Path(__file__).resolve().parents[2]
PACKAGING_REPORT_PATH = "reports/m2c-s4-decision-level-supervision-adr0026.json"
EXPECTED_DATASET_STATUS = "PASS_ADR0026_DECISION_LEVEL_DATASET"
DECISION_BUNDLE_MANIFEST_NAME = "qwen_adr0026_decision_v4_bundle.json"
DECISION_DATASET_REPORT_NAME = "qwen_adr0026_decision_v4_training_dataset_report.json"


class DecisionDatasetV4Error(ValueError):
    """Decision-level data is not the exact approved public-only replay."""


class M2CQwenADR0026DecisionDatasetLoadReportV1(StrictModel):
    schema_version: Literal["M2CQwenADR0026DecisionDatasetLoadReportV1"] = (
        "M2CQwenADR0026DecisionDatasetLoadReportV1"
    )
    status: Literal["PASS_REPLAYED_ADR0026_V4_DECISION_DATA"]
    packaging_report: BoundEvidenceFileV1
    dataset_manifest: BoundEvidenceFileV1
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    v4_shard: BoundEvidenceFileV1
    v3_shard_excluded_from_v4: BoundEvidenceFileV1
    rows_total: int = Field(gt=0)
    eligible_episodes: int = Field(gt=0)
    decision_index_counts: dict[str, int]
    skill_head_supervised_rows: int = Field(gt=0)
    pointer_head_supervised_rows: int = Field(gt=0)
    pointer_head_masked_rows: int = Field(ge=0)
    destination_head_supervised_rows: int = Field(gt=0)
    source_training_manifest_audits: list[M2CQwenCoarseV4KeyManifestAuditV1] = Field(
        min_length=2, max_length=2
    )
    source_evidence_files: list[BoundEvidenceFileV1] = Field(min_length=1)
    source_evidence_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_asset_files_verified: int = Field(gt=0)
    public_asset_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    combined_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_executed: Literal[False] = False
    model_rollout_executed: Literal[False] = False
    formal_q_b_evaluation_executed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def counts_are_exact(self) -> "M2CQwenADR0026DecisionDatasetLoadReportV1":
        if self.rows_total != sum(self.decision_index_counts.values()):
            raise ValueError("decision dataset index counts do not sum to rows")
        if set(self.decision_index_counts) != {str(index) for index in range(7)}:
            raise ValueError("V4 decision dataset must contain only prefix indices 0..6")
        if any(value != self.eligible_episodes for value in self.decision_index_counts.values()):
            raise ValueError("V4 decision dataset is not seven rows per episode")
        if self.skill_head_supervised_rows != self.rows_total:
            raise ValueError("V4 decision dataset does not supervise every skill row")
        if self.destination_head_supervised_rows != self.rows_total:
            raise ValueError("V4 decision dataset does not supervise every destination row")
        if self.pointer_head_supervised_rows + self.pointer_head_masked_rows != self.rows_total:
            raise ValueError("V4 pointer head mask does not partition every row")
        if self.combined_dataset_sha256 != self.v4_shard.sha256:
            raise ValueError("V4 combined dataset digest differs from its isolated shard")
        if self.source_evidence_inventory_sha256 != canonical_sha256(
            [item.model_dump(mode="json") for item in self.source_evidence_files]
        ):
            raise ValueError("V4 source evidence inventory digest differs")
        return self


class M2CQwenADR0026SourceTrainingManifestBindingV1(StrictModel):
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class M2CQwenADR0026DecisionBundleManifestV1(StrictModel):
    schema_version: Literal["M2CQwenADR0026DecisionBundleManifestV1"] = (
        "M2CQwenADR0026DecisionBundleManifestV1"
    )
    status: Literal["TRAINED_QWEN_LORA_M2C_Q012_V4_ADR0026_DECISION_LEVEL"]
    architecture_revision: Literal["M2C_Q012_V4"] = "M2C_Q012_V4"
    training_contract_revision: Literal["ADR0026_DECISION_LEVEL_PREFIX_0_6_V1"] = (
        "ADR0026_DECISION_LEVEL_PREFIX_0_6_V1"
    )
    public_observation_revision: Literal["PathBlockedPublicObservationV4"] = (
        "PathBlockedPublicObservationV4"
    )
    public_track_associator_revision: Literal["PublicTrackAssociatorV2"] = "PublicTrackAssociatorV2"
    public_track_candidate_revision: Literal["PublicTrackCandidateV4"] = "PublicTrackCandidateV4"
    model_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    base_model_snapshot_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_context: Literal["on", "off"]
    adapter_relative_path: Literal["adapter"] = "adapter"
    adapter_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    head_checkpoint_relative_path: Literal["qwen_coarse_v4_heads.npz"] = HEAD_CHECKPOINT_NAME
    head_checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    head_deployment_relative_path: Literal["qwen_coarse_v4_checkpoint_deployment.json"] = (
        HEAD_DEPLOYMENT_NAME
    )
    head_deployment: M2CQ012DeploymentManifestV4
    head_deployment_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_report_relative_path: Literal[
        "qwen_adr0026_decision_v4_training_dataset_report.json"
    ] = DECISION_DATASET_REPORT_NAME
    training_dataset_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_report_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_manifest_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_training_manifests: list[M2CQwenADR0026SourceTrainingManifestBindingV1] = Field(
        min_length=2, max_length=2
    )
    s6_manifest_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    s6_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    train_samples: int = Field(gt=0)
    train_episodes: int = Field(gt=0)
    optimizer_steps: int = Field(gt=0)
    training_complete: Literal[True]
    physical_evaluation_executed: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bindings_are_self_consistent(self) -> "M2CQwenADR0026DecisionBundleManifestV1":
        if self.head_checkpoint_sha256 != self.head_deployment.checkpoint_file_sha256:
            raise ValueError("ADR-0026 bundle checkpoint differs from deployment binding")
        deployment_bytes = _pretty_json_bytes(self.head_deployment.model_dump(mode="json"))
        if self.head_deployment_file_sha256 != sha256_bytes(deployment_bytes):
            raise ValueError("ADR-0026 bundle deployment file SHA-256 mismatch")
        source_pairs = [
            (item.file_sha256, item.canonical_sha256) for item in self.source_training_manifests
        ]
        if source_pairs != sorted(source_pairs) or len(set(source_pairs)) != 2:
            raise ValueError("ADR-0026 source manifest digests are not canonical")
        payload = self.model_dump(mode="json", exclude={"bundle_sha256"})
        if self.bundle_sha256 != canonical_sha256(payload):
            raise ValueError("ADR-0026 bundle canonical SHA-256 mismatch")
        return self


@dataclass(frozen=True)
class LoadedADR0026DecisionDatasetV4:
    rows: list[M2CS4DecisionLevelSupervisionRowV1]
    samples: list[M2CS4DecisionLevelTrainingSampleV1]
    report: M2CQwenADR0026DecisionDatasetLoadReportV1
    evidence_base: Path


@dataclass(frozen=True)
class LoadedADR0026DecisionBundleV4:
    manifest: M2CQwenADR0026DecisionBundleManifestV1
    heads: NumpyThreeHeadsV4


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pretty_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _write_new_decision_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while publishing ADR-0026 bundle evidence")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def decision_dataset_report_sha256_v4(
    report: M2CQwenADR0026DecisionDatasetLoadReportV1,
) -> str:
    return canonical_sha256(report.model_dump(mode="json"))


def _decision_bundle_source_bindings(
    report: M2CQwenADR0026DecisionDatasetLoadReportV1,
) -> tuple[list[M2CQwenADR0026SourceTrainingManifestBindingV1], str, str]:
    sources = sorted(
        (
            M2CQwenADR0026SourceTrainingManifestBindingV1(
                file_sha256=audit.training_manifest_file_sha256,
                canonical_sha256=audit.training_manifest_sha256,
            )
            for audit in report.source_training_manifest_audits
        ),
        key=lambda item: (item.file_sha256, item.canonical_sha256),
    )
    if (
        len(sources) != 2
        or len({(item.file_sha256, item.canonical_sha256) for item in sources}) != 2
    ):
        raise ValueError("ADR-0026 bundle requires two distinct V4 TRAIN manifests")
    s6 = {
        (audit.s6_manifest_file_sha256, audit.s6_manifest_sha256)
        for audit in report.source_training_manifest_audits
    }
    if len(s6) != 1:
        raise ValueError("ADR-0026 source manifests do not share one frozen S6 exclusion")
    s6_file_sha256, s6_sha256 = next(iter(s6))
    return sources, s6_file_sha256, s6_sha256


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DecisionDatasetV4Error(f"cannot securely open decision evidence: {path}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise DecisionDatasetV4Error("decision evidence is not a single-link regular file")
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
            raise DecisionDatasetV4Error("decision evidence changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _json_object(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DecisionDatasetV4Error(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise DecisionDatasetV4Error(f"{label} is not a JSON object")
    return value


def _git_show(root: Path, revision_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", revision_path],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise DecisionDatasetV4Error(f"cannot read committed decision binding {revision_path}")
    return completed.stdout


def _relative_to_root(root: Path, path: Path) -> str:
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise DecisionDatasetV4Error("decision binding escapes project root") from error


def _resolve_evidence_uri(evidence_base: Path, uri: str) -> Path:
    if not uri.startswith("evidence://"):
        raise DecisionDatasetV4Error("decision source is not evidence://")
    relative = Path(uri.removeprefix("evidence://"))
    if relative.is_absolute() or ".." in relative.parts:
        raise DecisionDatasetV4Error("decision evidence URI escapes its root")
    resolved = (evidence_base / relative).resolve(strict=True)
    if not resolved.is_relative_to(evidence_base):
        raise DecisionDatasetV4Error("decision evidence resolves outside evidence base")
    return resolved


def _resolve_dataset_asset(source_raw: Path, uri: str) -> Path:
    if not uri.startswith("dataset://"):
        raise DecisionDatasetV4Error("decision public asset is not dataset://")
    relative = Path(uri.removeprefix("dataset://"))
    if relative.is_absolute() or ".." in relative.parts:
        raise DecisionDatasetV4Error("decision public asset URI escapes probe root")
    root = source_raw.parent.resolve(strict=True)
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise DecisionDatasetV4Error("decision public asset resolves outside probe root")
    return resolved


def validate_decision_training_sample_v4(sample: M2CS4DecisionLevelTrainingSampleV1) -> None:
    if sample.evidence_revision != "V4" or not isinstance(
        sample.observation, PathBlockedPublicObservationV4
    ):
        raise DecisionDatasetV4Error("V3 supervision may not be upgraded into Qwen V4")
    if sample.decision_index not in range(7):
        raise DecisionDatasetV4Error("Qwen V4 decision dataset accepts prefix indices 0..6 only")
    if (
        sample.teacher_used
        or sample.privileged_truth_policy_input
        or not sample.decision_level_training_eligible
        or not sample.skill_head_supervision_eligible
        or not sample.destination_head_supervision_eligible
        or sample.split != "train"
        or sample.label_source != "EXECUTED_PUBLIC_PHYSICAL_CHAIN_ADR0026"
    ):
        raise DecisionDatasetV4Error("decision row is not approved public-only TRAIN supervision")
    expected_skill = EXPECTED_PATH_BLOCKED_CHAIN[sample.decision_index]
    if (
        sample.model_label.skill_type != expected_skill
        or SKILL_LABELS[sample.skill_label_index] != expected_skill
        or sample.skill_provenance != "MODEL"
    ):
        raise DecisionDatasetV4Error("decision skill label differs from the frozen chain")
    expected_payload, expected_digest = recompute_candidate_payload_v4(sample.observation)
    if (
        sample.observation.candidate_payload.model_dump(mode="json") != expected_payload
        or sample.observation.candidate_payload_sha256 != expected_digest
    ):
        raise DecisionDatasetV4Error("decision V4 candidates are not public-track recomputable")
    slots = canonical_slots_for_sample_v4(sample)  # type: ignore[arg-type]
    target = sample.model_label.target_track_id
    if sample.pointer_head_supervision_eligible:
        expected_pointer = encode_track_pointer_target_v4(target, slots)
        if sample.pointer_class_index != expected_pointer:
            raise DecisionDatasetV4Error("decision pointer label differs from frozen K=8 slots")
    else:
        candidate_ids = {item.track_id for item in sample.observation.candidate_payload.candidates}
        if sample.pointer_class_index is not None or target is None or target in candidate_ids:
            raise DecisionDatasetV4Error("masked pointer row does not prove target outside K=8")
    destination = sample.model_label.destination_cell or "NONE"
    if destination not in DESTINATION_LABELS:
        raise DecisionDatasetV4Error("decision destination label is not registered")
    if sample.destination_class_index != DESTINATION_LABELS.index(destination):
        raise DecisionDatasetV4Error("decision destination index differs from CoarseIntentV2")
    requires_pointer = sample.decision_index != 5
    if requires_pointer != (target is not None):
        raise DecisionDatasetV4Error("decision pointer presence differs from frozen chain")
    if target is not None:
        target_tracks = [
            track for track in sample.observation.perception_tracks if track.track_id == target
        ]
        expected_color = "red" if sample.decision_index <= 4 else "yellow"
        if len(target_tracks) != 1 or expected_color not in (
            target_tracks[0].category.casefold().replace("/", ":").split(":")
        ):
            raise DecisionDatasetV4Error("decision target lacks its frozen public semantic role")
    requires_destination = sample.decision_index in {2, 3}
    if requires_destination != (sample.model_label.destination_cell is not None):
        raise DecisionDatasetV4Error("decision destination presence differs from frozen chain")
    if sample.target_provenance != ("NONE" if sample.decision_index == 5 else "MODEL"):
        raise DecisionDatasetV4Error("decision target provenance differs from frozen chain")
    if sample.destination_provenance != ("MODEL" if sample.decision_index in {2, 3} else "NONE"):
        raise DecisionDatasetV4Error("decision destination provenance differs from frozen chain")
    if sample.model_label.failure_type_aux != FailureType.PATH_BLOCKED:
        raise DecisionDatasetV4Error("decision sample is not PATH_BLOCKED")


def index_decision_histories_v4(
    samples: Sequence[M2CS4DecisionLevelTrainingSampleV1],
) -> dict[str, list[PublicExecutedIntentHistoryItemV2]]:
    by_episode: dict[str, list[M2CS4DecisionLevelTrainingSampleV1]] = {}
    for sample in samples:
        validate_decision_training_sample_v4(sample)
        by_episode.setdefault(sample.episode_id, []).append(sample)
    histories: dict[str, list[PublicExecutedIntentHistoryItemV2]] = {}
    for episode_id, decisions in by_episode.items():
        ordered = sorted(decisions, key=lambda item: item.decision_index)
        if [item.decision_index for item in ordered] != list(range(7)):
            raise DecisionDatasetV4Error(f"episode {episode_id} is not the exact 0..6 prefix")
        if len({(item.matched_key, item.split_group) for item in ordered}) != 1:
            raise DecisionDatasetV4Error("decision episode changes matched key or split group")
        timestamps = [item.observation.captured_at_ns for item in ordered]
        if any(after <= before for before, after in zip(timestamps, timestamps[1:])):
            raise DecisionDatasetV4Error("decision episode observations are not strictly fresh")
        if len({item.observation.observation_id for item in ordered}) != 7:
            raise DecisionDatasetV4Error("decision episode reuses a public observation")
        if len({item.observation.capture_receipt_sha256 for item in ordered}) != 7:
            raise DecisionDatasetV4Error("decision episode reuses a public capture")
        if len({item.physical_receipt_sha256 for item in ordered}) != 7:
            raise DecisionDatasetV4Error("decision episode reuses a physical receipt")
        if len({item.model_label.destination_cell for item in ordered[2:4]}) != 1:
            raise DecisionDatasetV4Error("decision episode changes destination cell")
        prefix: list[PublicExecutedIntentHistoryItemV2] = []
        for sample in ordered:
            histories[sample.sample_id] = list(prefix)
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


def qwen_decision_prompt_v4(
    sample: M2CS4DecisionLevelTrainingSampleV1,
    *,
    executed_intent_history: list[PublicExecutedIntentHistoryItemV2],
    use_failure_context: bool,
) -> str:
    validate_decision_training_sample_v4(sample)
    return render_qwen_public_prompt_v4(
        candidate_payload=sample.observation.candidate_payload,
        decision_index=sample.decision_index,
        executed_intent_history=executed_intent_history,
        use_failure_context=use_failure_context,
    )


def decision_head_targets_v4(
    sample: M2CS4DecisionLevelTrainingSampleV1,
) -> dict[str, int | None]:
    validate_decision_training_sample_v4(sample)
    return {
        "skill": sample.skill_label_index,
        "pointer": (
            sample.pointer_class_index if sample.pointer_head_supervision_eligible else None
        ),
        "destination": sample.destination_class_index,
    }


def read_decision_rgb_v4(
    loaded: LoadedADR0026DecisionDatasetV4,
    row: M2CS4DecisionLevelSupervisionRowV1,
) -> bytes:
    source = _resolve_evidence_uri(loaded.evidence_base, row.source_raw_evidence.path)
    if sha256_bytes(_read_regular_file_once(source)) != row.source_raw_evidence.sha256:
        raise DecisionDatasetV4Error("decision source raw evidence digest changed")
    sample = row.training_sample
    asset = _resolve_dataset_asset(source, sample.observation.rgb_uri)
    raw = _read_regular_file_once(asset)
    if sha256_bytes(raw) != sample.observation.rgb_sha256:
        raise DecisionDatasetV4Error("decision RGB asset digest changed")
    return raw


def _validate_packaging_report(
    *, project_root: Path, report_path: Path, manifest_path: Path
) -> tuple[dict[str, object], bytes, bytes]:
    relative = _relative_to_root(project_root, report_path)
    raw = _read_regular_file_once(report_path)
    if _git_show(project_root, f"HEAD:{relative}") != raw:
        raise DecisionDatasetV4Error("decision packaging report is not exact current HEAD bytes")
    report = _json_object(raw, label="decision packaging report")
    claims = report.get("evidence_claims")
    if (
        report.get("schema_version") != "M2CS4ADR0026DecisionLevelPackagingReportV1"
        or report.get("status") != "PASS_PACKAGED_DECISION_LEVEL_SUPERVISION"
        or not isinstance(claims, dict)
        or claims.get("teacher_used") is not False
        or claims.get("privileged_truth_policy_input") is not False
        or claims.get("training_performed") is not False
        or claims.get("formal_q_b_evaluation_performed") is not False
    ):
        raise DecisionDatasetV4Error("decision packaging report is not approved offline evidence")
    accepted = report.get("accepted_adr")
    if not isinstance(accepted, dict) or (
        accepted.get("path") != ADR0026_PATH
        or accepted.get("sha256") != ADR0026_SHA256
        or accepted.get("section") != "4"
    ):
        raise DecisionDatasetV4Error("decision packaging report ADR binding changed")
    implementation = report.get("implementation")
    if not isinstance(implementation, dict):
        raise DecisionDatasetV4Error("decision packaging implementation binding is absent")
    implementation_path = project_root / str(implementation.get("path"))
    if sha256_bytes(_read_regular_file_once(implementation_path)) != implementation.get("sha256"):
        raise DecisionDatasetV4Error("decision packaging implementation bytes changed")
    manifest_ref = report.get("dataset_manifest")
    manifest_raw = _read_regular_file_once(manifest_path)
    if not isinstance(manifest_ref, dict) or (
        manifest_ref.get("path") != _relative_to_root(project_root, manifest_path)
        or manifest_ref.get("sha256") != sha256_bytes(manifest_raw)
    ):
        raise DecisionDatasetV4Error("decision packaging report differs from dataset manifest")
    source_reports = report.get("source_reports")
    if not isinstance(source_reports, list) or not source_reports:
        raise DecisionDatasetV4Error("decision packaging report has no source report closure")
    for item in source_reports:
        if not isinstance(item, dict):
            raise DecisionDatasetV4Error("decision source report binding is malformed")
        path = project_root / str(item.get("path"))
        if sha256_bytes(_read_regular_file_once(path)) != item.get("sha256"):
            raise DecisionDatasetV4Error("decision source report bytes changed")
    return report, raw, manifest_raw


def load_adr0026_decision_dataset_v4(
    *,
    project_root: Path,
    evidence_base: Path,
    dataset_manifest_path: Path,
    packaging_report_path: Path,
    training_manifest_paths: Sequence[Path],
    evaluation_manifest_path: Path,
) -> LoadedADR0026DecisionDatasetV4:
    project_root = project_root.resolve(strict=True)
    evidence_base = evidence_base.resolve(strict=True)
    if not evidence_base.is_dir() or evidence_base.is_symlink():
        raise DecisionDatasetV4Error("decision evidence base is not a real directory")
    adr_raw = _read_regular_file_once(project_root / ADR0026_PATH)
    if sha256_bytes(adr_raw) != ADR0026_SHA256:
        raise DecisionDatasetV4Error("accepted ADR-0026 bytes changed")
    packaging, packaging_raw, manifest_raw = _validate_packaging_report(
        project_root=project_root,
        report_path=packaging_report_path,
        manifest_path=dataset_manifest_path,
    )
    manifest = M2CS4DecisionLevelDatasetManifestV1.model_validate_json(manifest_raw)
    if manifest.status != EXPECTED_DATASET_STATUS:
        raise DecisionDatasetV4Error("decision dataset manifest is not passing")
    manifest_ref = packaging["dataset_manifest"]
    assert isinstance(manifest_ref, dict)
    if manifest.manifest_sha256 != manifest_ref.get("manifest_sha256"):
        raise DecisionDatasetV4Error("decision manifest canonical digest differs from report")
    shards = {item.revision: item for item in manifest.shards}
    if set(shards) != {"V3", "V4"}:
        raise DecisionDatasetV4Error("decision dataset must keep exact V3/V4 shards")
    shard_raw: dict[str, bytes] = {}
    for revision, shard in shards.items():
        path = project_root / shard.path
        raw = _read_regular_file_once(path)
        if sha256_bytes(raw) != shard.sha256 or len(raw) != shard.byte_count:
            raise DecisionDatasetV4Error(f"decision {revision} shard differs from manifest")
        if len(raw.splitlines()) != shard.row_count:
            raise DecisionDatasetV4Error(f"decision {revision} shard row count differs")
        shard_raw[revision] = raw
    rows = [
        M2CS4DecisionLevelSupervisionRowV1.model_validate_json(line)
        for line in shard_raw["V4"].splitlines()
    ]
    if any(row.evidence_revision != "V4" for row in rows):
        raise DecisionDatasetV4Error("V4 decision shard contains another observation revision")
    if [(row.matched_key, row.decision_index) for row in rows] != sorted(
        (row.matched_key, row.decision_index) for row in rows
    ):
        raise DecisionDatasetV4Error("V4 decision rows are not deterministically ordered")
    if len({row.row_id for row in rows}) != len(rows):
        raise DecisionDatasetV4Error("V4 decision dataset repeats a row identity")
    samples = [row.training_sample for row in rows]
    histories = index_decision_histories_v4(samples)
    if set(histories) != {sample.sample_id for sample in samples}:
        raise DecisionDatasetV4Error("V4 decision histories do not cover every sample")

    manifest_audits: list[M2CQwenCoarseV4KeyManifestAuditV1] = []
    source_training_keys: set[str] = set()
    if len(training_manifest_paths) != 2:
        raise DecisionDatasetV4Error("ADR-0026 V4 data requires the two frozen TRAIN manifests")
    for path in training_manifest_paths:
        audit, training, _ = validate_key_manifests_v4(path, evaluation_manifest_path)
        keys = {item.matched_key for item in training.training_keys}
        if source_training_keys & keys:
            raise DecisionDatasetV4Error("V4 source TRAIN manifests overlap")
        source_training_keys.update(keys)
        manifest_audits.append(audit)
    row_keys = {row.matched_key for row in rows}
    if not row_keys.issubset(source_training_keys):
        raise DecisionDatasetV4Error("V4 decision row is outside frozen TRAIN manifests")

    report_sources = {
        str(item["path"]): str(item["sha256"])
        for item in packaging["source_reports"]  # type: ignore[index]
        if isinstance(item, dict)
    }
    raw_cache: dict[Path, bytes] = {}
    asset_inventory: dict[Path, str] = {}
    for row in rows:
        expected_report_sha = report_sources.get(row.source_report.path)
        if expected_report_sha != row.source_report.sha256:
            raise DecisionDatasetV4Error("V4 row source report is outside packaging closure")
        source = _resolve_evidence_uri(evidence_base, row.source_raw_evidence.path)
        if source not in raw_cache:
            raw_cache[source] = _read_regular_file_once(source)
        raw = raw_cache[source]
        if sha256_bytes(raw) != row.source_raw_evidence.sha256:
            raise DecisionDatasetV4Error("V4 row source evidence digest changed")
        sample = row.training_sample
        validate_decision_training_sample_v4(sample)
        for uri, expected in (
            (sample.observation.rgb_uri, sample.observation.rgb_sha256),
            (sample.observation.depth_uri, sample.observation.depth_sha256),
        ):
            asset = _resolve_dataset_asset(source, uri)
            if asset not in asset_inventory:
                asset_inventory[asset] = sha256_bytes(_read_regular_file_once(asset))
            actual = asset_inventory[asset]
            if actual != expected:
                raise DecisionDatasetV4Error("V4 decision public asset digest changed")
    source_refs = [
        BoundEvidenceFileV1(
            path="evidence://" + path.relative_to(evidence_base).as_posix(),
            sha256=sha256_bytes(raw),
        )
        for path, raw in sorted(raw_cache.items(), key=lambda item: str(item[0]))
    ]
    asset_refs = [
        {"path": path.relative_to(evidence_base).as_posix(), "sha256": digest}
        for path, digest in sorted(asset_inventory.items(), key=lambda item: str(item[0]))
    ]
    counts = {
        str(index): sum(sample.decision_index == index for sample in samples) for index in range(7)
    }
    report = M2CQwenADR0026DecisionDatasetLoadReportV1(
        status="PASS_REPLAYED_ADR0026_V4_DECISION_DATA",
        packaging_report=BoundEvidenceFileV1(
            path=_relative_to_root(project_root, packaging_report_path),
            sha256=sha256_bytes(packaging_raw),
        ),
        dataset_manifest=BoundEvidenceFileV1(
            path=_relative_to_root(project_root, dataset_manifest_path),
            sha256=sha256_bytes(manifest_raw),
        ),
        dataset_manifest_sha256=manifest.manifest_sha256,
        v4_shard=BoundEvidenceFileV1(path=shards["V4"].path, sha256=shards["V4"].sha256),
        v3_shard_excluded_from_v4=BoundEvidenceFileV1(
            path=shards["V3"].path,
            sha256=shards["V3"].sha256,
        ),
        rows_total=len(rows),
        eligible_episodes=len({row.episode_id for row in rows}),
        decision_index_counts=counts,
        skill_head_supervised_rows=sum(
            sample.skill_head_supervision_eligible for sample in samples
        ),
        pointer_head_supervised_rows=sum(
            sample.pointer_head_supervision_eligible for sample in samples
        ),
        pointer_head_masked_rows=sum(
            not sample.pointer_head_supervision_eligible for sample in samples
        ),
        destination_head_supervised_rows=sum(
            sample.destination_head_supervision_eligible for sample in samples
        ),
        source_training_manifest_audits=manifest_audits,
        source_evidence_files=source_refs,
        source_evidence_inventory_sha256=canonical_sha256(
            [item.model_dump(mode="json") for item in source_refs]
        ),
        public_asset_files_verified=len(asset_refs),
        public_asset_inventory_sha256=canonical_sha256(asset_refs),
        combined_dataset_sha256=shards["V4"].sha256,
    )
    return LoadedADR0026DecisionDatasetV4(
        rows=rows,
        samples=samples,
        report=report,
        evidence_base=evidence_base,
    )


def write_adr0026_decision_bundle_v4(
    output_root: Path,
    *,
    heads: NumpyThreeHeadsV4,
    model_id: str,
    model_revision: str,
    base_model_snapshot_tree_sha256: str,
    failure_context: Literal["on", "off"],
    dataset_report: M2CQwenADR0026DecisionDatasetLoadReportV1,
    seed: int,
    optimizer_steps: int,
) -> M2CQwenADR0026DecisionBundleManifestV1:
    if optimizer_steps <= 0:
        raise ValueError("ADR-0026 trained bundle requires at least one optimizer step")
    if len(base_model_snapshot_tree_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in base_model_snapshot_tree_sha256
    ):
        raise ValueError("ADR-0026 base-model snapshot tree SHA-256 is malformed")
    if not output_root.is_dir() or output_root.is_symlink():
        raise FileNotFoundError("ADR-0026 output staging root does not exist")
    sources, s6_file_sha256, s6_sha256 = _decision_bundle_source_bindings(dataset_report)
    adapter_sha256 = sha256_tree_v4(output_root / "adapter")
    _, deployment, checkpoint_bytes = save_numpy_head_checkpoint_v4(
        output_root / HEAD_CHECKPOINT_NAME,
        heads,
    )
    deployment_bytes = _pretty_json_bytes(deployment.model_dump(mode="json"))
    _write_new_decision_file(output_root / HEAD_DEPLOYMENT_NAME, deployment_bytes)
    dataset_report_bytes = _pretty_json_bytes(dataset_report.model_dump(mode="json"))
    _write_new_decision_file(output_root / DECISION_DATASET_REPORT_NAME, dataset_report_bytes)
    payload: dict[str, object] = {
        "schema_version": "M2CQwenADR0026DecisionBundleManifestV1",
        "status": "TRAINED_QWEN_LORA_M2C_Q012_V4_ADR0026_DECISION_LEVEL",
        "architecture_revision": "M2C_Q012_V4",
        "training_contract_revision": "ADR0026_DECISION_LEVEL_PREFIX_0_6_V1",
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
        "training_dataset_report_relative_path": DECISION_DATASET_REPORT_NAME,
        "training_dataset_report_sha256": decision_dataset_report_sha256_v4(dataset_report),
        "training_dataset_report_file_sha256": sha256_bytes(dataset_report_bytes),
        "training_dataset_manifest_file_sha256": dataset_report.dataset_manifest.sha256,
        "training_dataset_manifest_sha256": dataset_report.dataset_manifest_sha256,
        "source_training_manifests": [item.model_dump(mode="json") for item in sources],
        "s6_manifest_file_sha256": s6_file_sha256,
        "s6_manifest_sha256": s6_sha256,
        "seed": seed,
        "train_samples": dataset_report.rows_total,
        "train_episodes": dataset_report.eligible_episodes,
        "optimizer_steps": optimizer_steps,
        "training_complete": True,
        "physical_evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["bundle_sha256"] = canonical_sha256(payload)
    manifest = M2CQwenADR0026DecisionBundleManifestV1.model_validate(payload)
    _write_new_decision_file(
        output_root / DECISION_BUNDLE_MANIFEST_NAME,
        _pretty_json_bytes(manifest.model_dump(mode="json")),
    )
    return manifest


def load_adr0026_decision_bundle_v4(
    output_root: Path,
    *,
    expected_bundle_sha256: str,
) -> LoadedADR0026DecisionBundleV4:
    manifest = M2CQwenADR0026DecisionBundleManifestV1.model_validate_json(
        _read_regular_file_once(output_root / DECISION_BUNDLE_MANIFEST_NAME)
    )
    if manifest.bundle_sha256 != expected_bundle_sha256:
        raise ValueError("ADR-0026 bundle differs from external expected digest")
    if sha256_tree_v4(output_root / manifest.adapter_relative_path) != (
        manifest.adapter_tree_sha256
    ):
        raise ValueError("ADR-0026 adapter tree SHA-256 mismatch")
    deployment_raw = _read_regular_file_once(output_root / manifest.head_deployment_relative_path)
    if sha256_bytes(deployment_raw) != manifest.head_deployment_file_sha256:
        raise ValueError("ADR-0026 deployment file SHA-256 mismatch")
    if M2CQ012DeploymentManifestV4.model_validate_json(deployment_raw) != (
        manifest.head_deployment
    ):
        raise ValueError("ADR-0026 deployment file differs from bundle manifest")
    report_raw = _read_regular_file_once(
        output_root / manifest.training_dataset_report_relative_path
    )
    if sha256_bytes(report_raw) != manifest.training_dataset_report_file_sha256:
        raise ValueError("ADR-0026 training dataset report file SHA-256 mismatch")
    report = M2CQwenADR0026DecisionDatasetLoadReportV1.model_validate_json(report_raw)
    sources, s6_file_sha256, s6_sha256 = _decision_bundle_source_bindings(report)
    if (
        decision_dataset_report_sha256_v4(report) != manifest.training_dataset_report_sha256
        or report.combined_dataset_sha256 != manifest.training_dataset_sha256
        or report.dataset_manifest.sha256 != manifest.training_dataset_manifest_file_sha256
        or report.dataset_manifest_sha256 != manifest.training_dataset_manifest_sha256
        or sources != manifest.source_training_manifests
        or s6_file_sha256 != manifest.s6_manifest_file_sha256
        or s6_sha256 != manifest.s6_manifest_sha256
        or report.rows_total != manifest.train_samples
        or report.eligible_episodes != manifest.train_episodes
    ):
        raise ValueError("ADR-0026 training dataset report differs from bundle manifest")
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
    return LoadedADR0026DecisionBundleV4(manifest=manifest, heads=heads)


def run_offline_decision_contract_smoke_v4(
    loaded: LoadedADR0026DecisionDatasetV4,
    *,
    hidden_size: int = 16,
    seed: int = 20260815,
) -> dict[str, object]:
    if not loaded.samples:
        raise DecisionDatasetV4Error("decision contract smoke requires real replayed rows")
    histories = index_decision_histories_v4(loaded.samples)
    heads: NumpyThreeHeadsV4 = initialize_numpy_heads_v4(hidden_size, seed)
    prompts = bytearray()
    masked = 0
    for sample in loaded.samples:
        prompt = qwen_decision_prompt_v4(
            sample,
            executed_intent_history=histories[sample.sample_id],
            use_failure_context=True,
        )
        prompts.extend(prompt.encode("utf-8") + b"\n")
        feature_bytes = hashlib.sha256(prompt.encode()).digest()
        features = np.resize(np.frombuffer(feature_bytes, dtype=np.uint8), hidden_size).astype(
            np.float64
        )
        features /= 255.0
        logits = heads.logits(features, sample.observation.candidate_payload.valid_mask)
        if [len(item) for item in logits] != [
            len(SKILL_LABELS),
            len(POINTER_LABELS),
            len(DESTINATION_LABELS),
        ]:
            raise DecisionDatasetV4Error("decision contract smoke head shapes changed")
        targets = decision_head_targets_v4(sample)
        masked += targets["pointer"] is None
    return {
        "schema_version": "M2CQwenADR0026DecisionContractSmokeV1",
        "status": "CONTRACT_SMOKE_PASS_NO_TRAINING",
        "rows_checked": len(loaded.samples),
        "episodes_checked": loaded.report.eligible_episodes,
        "pointer_rows_masked": masked,
        "prompts_sha256": sha256_bytes(bytes(prompts)),
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--evidence-base", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument(
        "--packaging-report",
        type=Path,
        default=ROOT / PACKAGING_REPORT_PATH,
    )
    parser.add_argument("--training-keys", type=Path, action="append", required=True)
    parser.add_argument("--evaluation-keys", type=Path, required=True)
    args = parser.parse_args()
    loaded = load_adr0026_decision_dataset_v4(
        project_root=args.project_root,
        evidence_base=args.evidence_base,
        dataset_manifest_path=args.dataset_manifest,
        packaging_report_path=args.packaging_report,
        training_manifest_paths=args.training_keys,
        evaluation_manifest_path=args.evaluation_keys,
    )
    output = {
        "dataset_report": loaded.report.model_dump(mode="json"),
        "contract_smoke": run_offline_decision_contract_smoke_v4(loaded),
    }
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
