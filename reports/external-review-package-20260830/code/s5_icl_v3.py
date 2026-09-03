"""Executable ICL protocol V3 for reconstructed S5 TRAIN and DEV rows."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
import random
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib import error, request

from pydantic import Field, model_validator

from xh_agent.qwen_brain.client_v1 import COMMANDER_SYSTEM_PROMPT_V1
from xh_agent.qwen_brain.contracts_v1 import CommanderPlanV1
from xh_agent.qwen_brain.s5_data_v1 import canonical_json, sha256_bytes, sha256_file
from xh_agent.qwen_brain.s5_evaluation_v1 import (
    PHYSICAL_PRIMITIVES,
    audit_reassociation_boundary,
    flatten_primitives,
    flatten_target_refs,
    paired_transition_matrix,
)
from xh_agent.qwen_brain.s5_schemas_v1 import (
    S5DatasetRowV1,
    S5DatasetSplitV1,
    S5EvaluationExpectationV1,
    StrictS5Model,
)

_FROZEN_TRAIN_DEV_IMAGE_MANIFEST_SHA256 = (
    "9c0b7157f29d3bc1d9b3ef3e963ac02417a8fc54a23a8bfda11ff645b5853960"
)


class S5IclRuntimeConfigV3(StrictS5Model):
    host: Literal["node2"]
    accelerator: Literal["NVIDIA A100-SXM4-80GB"]
    cuda_device_index: Literal[0]
    snapshot_path: Literal["/home/gl/qwen38-27b-mtp/Qwen3.8-27B"]
    snapshot_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_regular_file_count: Literal[32]
    training_venv_path: Literal["/home/gl/xh-202607-qwen-s5/.venv-s5"]
    environment_identity_report_path: Literal[
        "/home/gl/xh-202607-qwen-s5/preflight/environment-identity-node2-v1.json"
    ]
    environment_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenizer_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenizer_json_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chat_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessor_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_dtype: Literal["bfloat16"]
    local_files_only: Literal[True]
    direct_transformers_no_service: Literal[True]
    deterministic_algorithms: Literal[True]
    cudnn_benchmark: Literal[False]
    matmul_precision: Literal["highest"]


class S5IclDataConfigV3(StrictS5Model):
    train_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconstruction_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_dataset_sha256_binding: str = Field(pattern=r"^[0-9a-f]{64}$")
    train_rows: Literal[428]
    train_sources: Literal[374]
    train_components: Literal[34]
    dev_rows: Literal[78]
    dev_sources: Literal[66]
    dev_components: Literal[6]
    unique_image_count: Literal[440]
    total_image_bytes: Literal[39606063]
    image_set_sha256: Literal[
        "29cab593f28abea6f4a57f5471cfb1d29f9fd4efa0252d00f11afa782bc1e0eb"
    ]
    node2_materialization_root: Literal[
        "/home/gl/xh-202607-qwen-s5/icl-input-v2"
    ]
    node2_image_root: Literal[
        "/home/gl/xh-202607-qwen-s5/icl-input-v2/images"
    ]
    node2_image_manifest_path: Literal[
        "/home/gl/xh-202607-qwen-s5/icl-input-v2/image-manifest-v2.json"
    ]
    allowed_builder_splits: tuple[Literal["TRAIN"], Literal["DEV"]]
    evaluation_rows_read: Literal[False]
    evaluation_rows_materialized: Literal[False]


class S5IclPolicyConfigV3(StrictS5Model):
    policy_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    shot_count: Literal[0, 2, 4]
    demo_selection: Literal[
        "NONE",
        "SAME_FAMILY_THEN_GLOBAL_SHA256_V2",
        "TARGET_FAMILY_THEN_OTHER_FAMILIES_SHA256_V2",
    ]


class S5IclMessageConfigV3(StrictS5Model):
    representation: Literal["MULTIMODAL_MULTI_TURN_V2"]
    demo_turn_pair: Literal[
        "INDEPENDENT_USER_IMAGE_INSTRUCTION_PUBLIC_CONTEXT_THEN_ASSISTANT_CANONICAL_JSON"
    ]
    target_turn: Literal["INDEPENDENT_USER_IMAGE_INSTRUCTION_PUBLIC_CONTEXT"]
    zero_shot_target_turn_identical: Literal[True]
    demo_order: Literal["SELECTION_PRIORITY_THEN_SHA256_SAMPLE_ID_ASCENDING_V2"]
    per_case_exclusions: tuple[
        Literal["SAME_COMPONENT"],
        Literal["SAME_SOURCE_IDENTITY"],
        Literal["SAME_IMAGE_SHA256"],
    ]
    image_resolution_policy: Literal[
        "SAME_AS_SINGLE_IMAGE_RUNTIME_NO_ICL_SPECIFIC_TRANSFORM"
    ]
    image_content_order: Literal["IMAGE_THEN_TEXT"]


class S5IclDecodingConfigV3(StrictS5Model):
    temperature: Literal[0.0]
    max_tokens: Literal[2048]
    enable_thinking: Literal[False]
    guided_json: Literal[False]
    max_attempts: Literal[1]
    retry_or_schema_correction_allowed: Literal[False]


class S5IclDevSelectionConfigV3(StrictS5Model):
    primary_metric: Literal["EXPECTATION_MATCH_RATE"]
    secondary_metrics_in_order: tuple[
        Literal["STRICT_VALID_RATE"],
        Literal["PRIMITIVE_CHECK_PASS_RATE"],
        Literal["REASSOCIATION_BOUNDARY_PASS_RATE"],
    ]
    tie_break: Literal["LOWER_SHOT_COUNT_THEN_POLICY_ID_ASCENDING"]
    all_78_rows_in_denominator: Literal[True]
    policy_freeze_create_only: Literal[True]


class S5IclPairedPreregistrationV3(StrictS5Model):
    comparison: Literal["TRAINED_LORA_VS_DEV_SELECTED_ICL_BASELINE"]
    selected_policy_id: Literal["two_shot_family_first_v2"]
    selected_shot_count: Literal[2]
    closed_v2_protocol_config_sha256: Literal[
        "a79a55a3c3b0dc036d1853431d92aed10a54326f1bdaad7bcbd8efdbb1e0729a"
    ]
    historical_dev_execution_config_sha256: Literal[
        "8d6ba48cf26462796bdb01d7bb876ee10e06e3296d1d72d331dec97dc6aecb7f"
    ]
    selected_policy_artifact_sha256: Literal[
        "95c881d2d907d3ded7ec51c21fb95802c6fa8a3b809d214887ded19659e29ef6"
    ]
    selected_base_dev_report_sha256: Literal[
        "76f7d6b83e400670773a343b875b31659eec372f90b2420ea9724222cc753c95"
    ]
    selected_dev_request_manifest_sha256: Literal[
        "e555b43f3428e2836d343ad11fee1b961271dba15752f966c8ad584e74b54ff1"
    ]
    trained_adapter_tree_sha256: Literal[
        "8a09f56a4a77c0127c0f1c2008efb8726e11d4a9b0c56f526a9934ce0a88f0b9"
    ]
    binary_primary_metric: Literal["EXPECTATION_MATCH"]
    paired_transition_table: Literal["N11_N10_N01_N00"]
    exact_mcnemar: Literal["TWO_SIDED_EXACT_BINOMIAL_ON_DISCORDANT_PAIRS"]
    cluster_bootstrap_replicates: Literal[10000]
    cluster_unit: Literal["FROZEN_GRAPH_COMPONENT"]
    confidence_interval: Literal["PERCENTILE_95_PERCENT"]
    bootstrap_seed: Literal[20260830]
    expected_component_counts: dict[str, int]
    low_cluster_count_threshold: Literal[8]
    low_cluster_count_flag: Literal["UNSTABLE_LOW_CLUSTER_COUNT"]
    unstable_interval_presentation: Literal[
        "DO_NOT_PRESENT_AS_ORDINARY_STABLE_STATISTICAL_INTERVAL"
    ]
    practical_difference_minimum: Literal[0.05]
    practical_difference_interpretation: Literal[
        "AT_LEAST_ONE_FEWER_ERROR_PER_TWENTY_INDEPENDENT_EPISODES"
    ]
    benefit_gate: Literal[
        "POINT_DELTA_GTE_0_05_AND_CI_LOWER_NOT_NEGATIVE_AND_MANUAL_BLIND_NONREGRESSION_AND_COMPLETE_EVIDENCE_AND_NO_CONTRACT_OR_SAFETY_REGRESSION_AND_NO_UNSTABLE_INTERVAL"
    ]
    claim_levels: tuple[
        Literal["FULL_TRAINING_BENEFIT"],
        Literal["POINT_ESTIMATE_BENEFIT_UNSTABLE_CLUSTER_COUNT"],
        Literal["NO_BENEFIT_EVIDENCE"],
    ]
    directional_claim_text: Literal[
        "点估计收益，评测集聚类规模不足以给出稳定区间"
    ]
    full_benefit_disallows_unstable_interval: Literal[True]
    paired_dev_rows: Literal[78]
    paired_dev_supporting_only: Literal[True]
    paired_dev_tuning_split: Literal[True]
    paired_dev_both_arms_have_seen_split: Literal[True]
    paired_dev_before_test_read: Literal[True]
    synthetic_test_rows: Literal[22]
    manual_blind_rows: Literal[45]
    read_once_order: tuple[
        Literal["FREEZE_DEV_SELECTED_POLICY"],
        Literal["FREEZE_PAIRED_EVALUATION_PREREGISTRATION_WITH_A1_A2_A3"],
        Literal["ATTEST_EXISTING_DEV_SELECTION_CREATE_ONLY"],
        Literal["RUN_TRAINED_LORA_SELECTED_TWO_SHOT_PAIRED_DEV_SUPPORTING_ANALYSIS"],
        Literal["RUN_UNIQUE_READ_ONCE_SPLITTER_AND_EXACT_RECONSTRUCTION_ATTESTATION"],
        Literal["EVALUATE_SYNTHETIC_TEST_ONCE"],
        Literal["EVALUATE_MANUAL_BLIND_ONCE"],
    ]
    canonical_evaluation_separately_gated: Literal[True]

    @model_validator(mode="after")
    def frozen_amendments(self) -> S5IclPairedPreregistrationV3:
        if self.expected_component_counts != {
            "DEV": 6,
            "MANUAL_BLIND": 3,
            "SYNTHETIC_TEST": 2,
        }:
            raise ValueError("paired split component counts do not match A1")
        return self


class S5IclPublicationConfigV3(StrictS5Model):
    request_manifest_create_only: Literal[True]
    raw_attempt_create_only: Literal[True]
    dev_report_create_only: Literal[True]
    policy_freeze_create_only: Literal[True]
    paired_report_create_only: Literal[True]


class S5IclConfigV3(StrictS5Model):
    schema_version: Literal["QwenBrainS5IclConfigV3"]
    experiment_identity: Literal["s5-icl-v3"]
    protocol_v1_status: Literal["CREATED_AND_CLOSED_TOMBSTONE"]
    protocol_v1_evaluation_effect: Literal["NIL"]
    protocol_v2_status: Literal[
        "CREATED_AND_CLOSED_REAL_EVALUATION_DECODE_IN_PYTEST"
    ]
    protocol_v2_evaluation_effect: Literal["INHERITED_FROZEN_DEV_SELECTION_ONLY"]
    protocol_v2_frozen_scientific_content_inherited: Literal[True]
    protocol_v2_closure_disclosure: Literal[
        "A splitter pytest decoded the real frozen monolithic V4 dataset into temporary outputs before the authoritative unique splitter; temporary outputs were naturally removed, but the decode closes V2 under the same mechanical standard as V1."
    ]
    evaluation_code_test_data_policy: Literal[
        "SYNTHETIC_FIXTURES_ONLY_NO_REAL_MONOLITHIC_OR_SPLIT_FILES"
    ]
    model: Literal["Qwen3.8-27B"]
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime: S5IclRuntimeConfigV3
    data: S5IclDataConfigV3
    policies: list[S5IclPolicyConfigV3] = Field(min_length=3, max_length=3)
    messages: S5IclMessageConfigV3
    decoding: S5IclDecodingConfigV3
    dev_selection: S5IclDevSelectionConfigV3
    paired_evaluation_preregistration: S5IclPairedPreregistrationV3
    publication: S5IclPublicationConfigV3
    forbidden_actions: list[str] = Field(min_length=7)
    no_remote_action_authorized_by_config: Literal[True]

    @model_validator(mode="after")
    def frozen_policy_surface(self) -> S5IclConfigV3:
        observed = {
            policy.policy_id: (policy.shot_count, policy.demo_selection)
            for policy in self.policies
        }
        expected = {
            "zero_shot_v2": (0, "NONE"),
            "two_shot_family_first_v2": (
                2,
                "SAME_FAMILY_THEN_GLOBAL_SHA256_V2",
            ),
            "four_shot_family_cover_v2": (
                4,
                "TARGET_FAMILY_THEN_OTHER_FAMILIES_SHA256_V2",
            ),
        }
        if observed != expected:
            raise ValueError("ICL policy surface does not match the V2 preregistration")
        prompt_sha256 = hashlib.sha256(COMMANDER_SYSTEM_PROMPT_V1.encode()).hexdigest()
        if self.system_prompt_sha256 != prompt_sha256:
            raise ValueError("frozen commander system prompt digest mismatch")
        return self


@dataclass(frozen=True)
class S5IclEvaluationBindingsV3:
    split: S5DatasetSplitV1
    row_count: int
    component_count: int
    evaluation_rows_sha256: str
    read_once_attestation_sha256: str
    dataset_sha256: str = (
        "749316f5adf4f2db3df4a5a9c76bc5604d5060f80cb899c222609ae4e4003f3a"
    )
    train_sha256: str = (
        "3d3675e919babaf2e967c5162a84e699c0f2986f7b7557a466d3c8d1fa0945a8"
    )
    dev_sha256: str = (
        "f0218a6d2267a59b3426d35632906a300d7e1b56b0039037e5ff1fc6799332e7"
    )
    train_row_count: int = 428
    train_source_count: int = 374
    train_component_count: int = 34
    read_once_process_role: str = "UNIQUE_READ_ONCE_SPLITTER"
    process_role: str = "AUTHORITATIVE_PAIRED_EVALUATION"

    def __post_init__(self) -> None:
        if self.split not in {
            S5DatasetSplitV1.SYNTHETIC_TEST,
            S5DatasetSplitV1.MANUAL_BLIND,
        }:
            raise ValueError("paired evaluation supports only TEST or BLIND")
        if self.row_count < 1 or self.component_count < 1:
            raise ValueError("paired evaluation counts must be positive")
        if (
            self.train_row_count < 1
            or self.train_source_count < 1
            or self.train_component_count < 1
        ):
            raise ValueError("TRAIN binding counts must be positive")
        for digest in (
            self.evaluation_rows_sha256,
            self.read_once_attestation_sha256,
            self.dataset_sha256,
            self.train_sha256,
            self.dev_sha256,
        ):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("paired evaluation bindings require SHA-256 digests")


class S5IclEvaluationExpectationV3(S5EvaluationExpectationV1):
    required_primitive_counts: dict[str, int]

    @model_validator(mode="after")
    def primitive_counts_match_required_set(self) -> S5IclEvaluationExpectationV3:
        if set(self.required_primitive_counts) != set(self.required_primitives):
            raise ValueError("primitive count keys must match required primitives")
        if any(count < 1 for count in self.required_primitive_counts.values()):
            raise ValueError("required primitive counts must be positive")
        return self


class S5IclDatasetRowV3(S5DatasetRowV1):
    prompt_context: dict[str, Any]

    @model_validator(mode="after")
    def prompt_context_is_public_view(self) -> S5IclDatasetRowV3:
        expected = self.context.model_dump(mode="json")
        if self.family.value == "VISUAL_CONDITION_SELECTION":
            expected.pop("target_ref", None)
            expected.pop("approach_pose_ref", None)
        if self.prompt_context != expected:
            raise ValueError("row prompt_context is not the frozen public prompt view")
        return self


def load_icl_config(path: Path) -> S5IclConfigV3:
    _require_regular_file(path, role="ICL config")
    return S5IclConfigV3.model_validate_json(path.read_text(encoding="utf-8"))


def _require_regular_file(path: Path, *, role: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{role} must be a regular non-symlink file")


def snapshot_tree_identity(path: Path, *, expected_file_count: int = 32) -> tuple[str, list[str]]:
    entries = []
    ignored_top_level_dirs = []
    if not path.is_dir() or path.is_symlink():
        raise ValueError("snapshot must be a local regular directory")
    for candidate in sorted(path.iterdir(), key=lambda item: item.name):
        if candidate.is_symlink():
            raise ValueError("snapshot top-level entries must not be symlinks")
        if candidate.is_dir():
            ignored_top_level_dirs.append(candidate.name)
            continue
        if not candidate.is_file():
            raise ValueError("snapshot contains a non-regular top-level entry")
        entries.append(
            {
                "name": candidate.name,
                "size": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
        )
    if len(entries) != expected_file_count:
        raise ValueError("snapshot regular top-level file count mismatch")
    return sha256_bytes(canonical_json(entries).encode()), ignored_top_level_dirs


def regular_tree_identity(path: Path) -> tuple[str, list[dict[str, object]]]:
    if not path.is_dir() or path.is_symlink():
        raise ValueError("tree root must be a regular non-symlink directory")
    entries = []
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink() or (not candidate.is_file() and not candidate.is_dir()):
            raise ValueError("tree contains a symlink or unsupported entry")
        if candidate.is_file():
            entries.append(
                {
                    "path": candidate.relative_to(path).as_posix(),
                    "size": candidate.stat().st_size,
                    "sha256": sha256_file(candidate),
                }
            )
    if not entries:
        raise ValueError("tree must contain at least one regular file")
    return sha256_bytes(canonical_json(entries).encode()), entries


def _write_create_only(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def write_create_only_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    _write_create_only(path, encoded)


def _load_reconstructed_split(
    path: Path,
    *,
    expected_sha256: str,
    split: S5DatasetSplitV1,
    expected_rows: int,
    expected_sources: int,
    expected_components: int,
) -> list[S5IclDatasetRowV3]:
    _require_regular_file(path, role=f"reconstructed {split.value}")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"reconstructed {split.value} digest mismatch")
    rows = [
        S5IclDatasetRowV3.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    if len(rows) != expected_rows or {row.split for row in rows} != {split}:
        raise ValueError(f"reconstructed {split.value} row identity mismatch")
    if len({row.sample_id for row in rows}) != len(rows):
        raise ValueError(f"reconstructed {split.value} sample IDs must be unique")
    if len({row.source_identity_sha256 for row in rows}) != expected_sources:
        raise ValueError(f"reconstructed {split.value} source count mismatch")
    if len({row.component_id for row in rows}) != expected_components:
        raise ValueError(f"reconstructed {split.value} component count mismatch")
    return rows


def _validate_reconstruction_manifest(
    path: Path,
    *,
    config: S5IclConfigV3,
) -> dict[str, object]:
    _require_regular_file(path, role="TRAIN/DEV reconstruction manifest")
    if sha256_file(path) != config.data.reconstruction_manifest_sha256:
        raise ValueError("TRAIN/DEV reconstruction manifest digest mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("TRAIN/DEV reconstruction manifest must be a JSON object")
    if (
        payload.get("schema_version")
        != "QwenBrainS5TrainDevReconstructionManifestV2"
        or payload.get("status") != "PASS"
        or payload.get("allowed_splits") != ["TRAIN", "DEV"]
        or payload.get("evaluation_rows_read") is not False
        or payload.get("evaluation_rows_materialized") is not False
        or payload.get("frozen_dataset_sha256_binding")
        != config.data.frozen_dataset_sha256_binding
        or payload.get("output_sha256")
        != {"DEV": config.data.dev_sha256, "TRAIN": config.data.train_sha256}
        or payload.get("row_counts") != {"DEV": 78, "TRAIN": 428}
        or payload.get("source_counts") != {"DEV": 66, "TRAIN": 374}
    ):
        raise ValueError("TRAIN/DEV reconstruction manifest identity mismatch")
    return payload


def _selection_digest(policy_id: str, target_id: str, candidate_id: str) -> str:
    payload = (
        "QWEN_BRAIN_S5_ICL_DEMO_ORDER_V2\0"
        + policy_id
        + "\0"
        + target_id
        + "\0"
        + candidate_id
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _eligible_demonstrations(
    train_rows: Sequence[S5IclDatasetRowV3],
    target: S5IclDatasetRowV3,
) -> list[S5IclDatasetRowV3]:
    return [
        row
        for row in train_rows
        if row.component_id != target.component_id
        and row.source_identity_sha256 != target.source_identity_sha256
        and row.image_sha256 != target.image_sha256
    ]


def select_demonstrations(
    train_rows: Sequence[S5IclDatasetRowV3],
    target: S5IclDatasetRowV3,
    policy: S5IclPolicyConfigV3,
) -> list[S5IclDatasetRowV3]:
    if policy.shot_count == 0:
        return []
    eligible = _eligible_demonstrations(train_rows, target)
    ranked = sorted(
        eligible,
        key=lambda row: (
            _selection_digest(policy.policy_id, target.sample_id, row.sample_id),
            row.sample_id,
        ),
    )
    selected: list[S5IclDatasetRowV3] = []
    selected_components: set[str] = set()

    def add_first(candidates: Sequence[S5IclDatasetRowV3]) -> None:
        for row in candidates:
            if row.component_id in selected_components:
                continue
            selected.append(row)
            selected_components.add(row.component_id)
            return

    if policy.shot_count == 2:
        same_family = [row for row in ranked if row.family == target.family]
        while len(selected) < policy.shot_count:
            before = len(selected)
            add_first(same_family if same_family else ranked)
            if len(selected) == before:
                add_first(ranked)
            if len(selected) == before:
                break
    else:
        family_order = [target.family.value, *sorted(
            family.value
            for family in {row.family for row in eligible}
            if family != target.family
        )]
        for family in family_order:
            add_first([row for row in ranked if row.family.value == family])
        while len(selected) < policy.shot_count:
            before = len(selected)
            add_first(ranked)
            if len(selected) == before:
                break
    if len(selected) != policy.shot_count:
        raise ValueError(f"policy {policy.policy_id} lacks eligible demonstration components")
    if any(
        row.component_id == target.component_id
        or row.source_identity_sha256 == target.source_identity_sha256
        or row.image_sha256 == target.image_sha256
        for row in selected
    ):
        raise ValueError("demonstration exclusion invariant failed")
    if len({row.component_id for row in selected}) != len(selected):
        raise ValueError("demonstrations must come from distinct frozen components")
    return selected


def _user_text(row: S5IclDatasetRowV3) -> str:
    return row.instruction + "\n已知上下文(JSON): " + json.dumps(
        row.prompt_context,
        ensure_ascii=False,
        sort_keys=True,
    )


def _user_message(
    row: S5IclDatasetRowV3,
    *,
    image_root: Path | None = None,
) -> dict[str, object]:
    if row.image_path is None or row.image_sha256 is None:
        raise ValueError("ICL V3 requires an image for every TRAIN and DEV turn")
    image_path = (
        image_root / f"{row.image_sha256}.png"
        if image_root is not None
        else Path(row.image_path)
    )
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "image_path": str(image_path),
                "image_sha256": row.image_sha256,
            },
            {"type": "text", "text": _user_text(row)},
        ],
    }


def build_multiturn_messages(
    *,
    target: S5IclDatasetRowV3,
    demonstrations: Sequence[S5IclDatasetRowV3],
    image_root: Path | None = None,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": COMMANDER_SYSTEM_PROMPT_V1}
    ]
    for row in demonstrations:
        messages.append(_user_message(row, image_root=image_root))
        messages.append({"role": "assistant", "content": row.target_json})
    messages.append(_user_message(target, image_root=image_root))
    expected_roles = ["system"] + [role for _ in demonstrations for role in ("user", "assistant")] + ["user"]
    if [message["role"] for message in messages] != expected_roles:
        raise ValueError("ICL V3 message turn structure mismatch")
    return messages


def _expectation_from_row(row: S5IclDatasetRowV3) -> S5IclEvaluationExpectationV3:
    unresolved = row.prompt_context.get("binding_unresolved") is True
    forbidden = sorted(PHYSICAL_PRIMITIVES) if unresolved else []
    primitive_counts = dict(sorted(Counter(flatten_primitives(row.target_plan)).items()))
    return S5IclEvaluationExpectationV3(
        expected_outcome="REFUSE" if row.target_plan.refused else "PLAN",
        required_primitives=list(primitive_counts),
        required_primitive_counts=primitive_counts,
        forbidden_primitives=forbidden,
        unresolved_binding=unresolved,
        expected_target_refs=sorted(flatten_target_refs(row.target_plan)),
    )


def build_request_record(
    *,
    target: S5IclDatasetRowV3,
    demonstrations: Sequence[S5IclDatasetRowV3],
    policy: S5IclPolicyConfigV3,
    image_root: Path | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "QwenBrainS5IclRequestV3",
        "policy_id": policy.policy_id,
        "shot_count": policy.shot_count,
        "case_id": target.sample_id,
        "split": target.split.value,
        "family": target.family.value,
        "component_id": target.component_id,
        "source_identity_sha256": target.source_identity_sha256,
        "image_sha256": target.image_sha256,
        "demo_sample_ids": [row.sample_id for row in demonstrations],
        "demo_component_ids": [row.component_id for row in demonstrations],
        "messages": build_multiturn_messages(
            target=target,
            demonstrations=demonstrations,
            image_root=image_root,
        ),
        "expectation": _expectation_from_row(target).model_dump(mode="json"),
        "target_plan": target.target_plan.model_dump(mode="json"),
    }
    record["request_identity_sha256"] = sha256_bytes(canonical_json(record).encode())
    return record


def _verify_images(rows: Sequence[S5IclDatasetRowV3]) -> None:
    observed: dict[str, Path] = {}
    for row in rows:
        if row.image_path is None or row.image_sha256 is None:
            raise ValueError("ICL rows require images")
        path = Path(row.image_path)
        prior = observed.get(row.image_sha256)
        if prior is not None and prior != path:
            raise ValueError("one image digest maps to multiple paths")
        observed[row.image_sha256] = path
    for digest, path in observed.items():
        _require_regular_file(path, role="ICL image")
        if sha256_file(path) != digest:
            raise ValueError("ICL image digest mismatch")


def build_icl_request_manifests(
    *,
    config_path: Path,
    reconstruction_manifest_path: Path,
    train_path: Path,
    dev_path: Path,
    policy_output_paths: Mapping[str, Path],
    manifest_output_path: Path,
    image_root: Path | None = None,
    image_manifest_path: Path | None = None,
) -> dict[str, object]:
    config = load_icl_config(config_path)
    expected_policy_ids = {policy.policy_id for policy in config.policies}
    if set(policy_output_paths) != expected_policy_ids:
        raise ValueError("policy output paths must exactly cover the frozen policies")
    outputs = [*policy_output_paths.values(), manifest_output_path]
    if len(set(outputs)) != len(outputs):
        raise ValueError("ICL output paths must be distinct")
    for path in outputs:
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    reconstruction_manifest = _validate_reconstruction_manifest(
        reconstruction_manifest_path,
        config=config,
    )
    train_rows = _load_reconstructed_split(
        train_path,
        expected_sha256=config.data.train_sha256,
        split=S5DatasetSplitV1.TRAIN,
        expected_rows=config.data.train_rows,
        expected_sources=config.data.train_sources,
        expected_components=config.data.train_components,
    )
    dev_rows = _load_reconstructed_split(
        dev_path,
        expected_sha256=config.data.dev_sha256,
        split=S5DatasetSplitV1.DEV,
        expected_rows=config.data.dev_rows,
        expected_sources=config.data.dev_sources,
        expected_components=config.data.dev_components,
    )
    if (image_root is None) != (image_manifest_path is None):
        raise ValueError("image root and image manifest must be supplied together")
    image_manifest_sha256 = None
    if image_root is None:
        _verify_images([*train_rows, *dev_rows])
    else:
        if not image_root.is_dir() or image_root.is_symlink():
            raise ValueError("ICL image root must be a regular directory")
        assert image_manifest_path is not None
        _require_regular_file(image_manifest_path, role="ICL image manifest")
        image_manifest = json.loads(image_manifest_path.read_text(encoding="utf-8"))
        expected_hashes = {row.image_sha256 for row in [*train_rows, *dev_rows]}
        expected_names = {f"{digest}.png" for digest in expected_hashes}
        entries = image_manifest.get("entries")
        if not isinstance(entries, list):
            raise TypeError("ICL image manifest entries must be a list")
        identity_entries = [
            {
                "image_sha256": entry.get("image_sha256"),
                "relative_path": entry.get("relative_path"),
                "size_bytes": entry.get("size_bytes"),
            }
            for entry in entries
        ]
        expected_relative_paths = {
            f"images/{digest}.png" for digest in expected_hashes
        }
        if (
            image_manifest.get("schema_version")
            != "QwenBrainS5IclImageMaterializationV2"
            or image_manifest.get("status") != "PASS"
            or image_manifest.get("config_sha256") != sha256_file(config_path)
            or image_manifest.get("train_sha256") != config.data.train_sha256
            or image_manifest.get("dev_sha256") != config.data.dev_sha256
            or image_manifest.get("train_rows") != config.data.train_rows
            or image_manifest.get("dev_rows") != config.data.dev_rows
            or image_manifest.get("unique_image_count")
            != config.data.unique_image_count
            or image_manifest.get("total_image_bytes")
            != config.data.total_image_bytes
            or image_manifest.get("image_set_sha256") != config.data.image_set_sha256
            or sha256_bytes(canonical_json(identity_entries).encode())
            != config.data.image_set_sha256
            or image_manifest.get("allowed_splits") != ["TRAIN", "DEV"]
            or image_manifest.get("evaluation_rows_read") is not False
            or image_manifest.get("evaluation_images_materialized") is not False
            or image_manifest.get("canonical_images_materialized") is not False
            or len(entries) != config.data.unique_image_count
            or {entry.get("image_sha256") for entry in entries} != expected_hashes
            or {entry.get("relative_path") for entry in entries}
            != expected_relative_paths
            or sum(int(entry.get("size_bytes", -1)) for entry in entries)
            != config.data.total_image_bytes
            or {path.name for path in image_root.iterdir()} != expected_names
        ):
            raise ValueError("ICL image materialization identity mismatch")
        entry_by_digest = {
            str(entry["image_sha256"]): entry for entry in entries
        }
        for digest in expected_hashes:
            path = image_root / f"{digest}.png"
            _require_regular_file(path, role="materialized ICL image")
            if (
                sha256_file(path) != digest
                or path.stat().st_size != entry_by_digest[digest]["size_bytes"]
            ):
                raise ValueError("materialized ICL image digest or size mismatch")
        image_manifest_sha256 = sha256_file(image_manifest_path)

    output_sha256: dict[str, str] = {}
    output_counts: dict[str, int] = {}
    for policy in config.policies:
        records = [
            build_request_record(
                target=row,
                demonstrations=select_demonstrations(train_rows, row, policy),
                policy=policy,
                image_root=image_root,
            )
            for row in dev_rows
        ]
        payload = ("\n".join(canonical_json(record) for record in records) + "\n").encode()
        _write_create_only(policy_output_paths[policy.policy_id], payload)
        output_sha256[policy.policy_id] = sha256_bytes(payload)
        output_counts[policy.policy_id] = len(records)

    manifest: dict[str, object] = {
        "schema_version": "QwenBrainS5IclRequestManifestBundleV3",
        "status": "PASS",
        "experiment_identity": config.experiment_identity,
        "config_sha256": sha256_file(config_path),
        "reconstruction_manifest_sha256": sha256_file(reconstruction_manifest_path),
        "reconstruction_evaluation_rows_read": reconstruction_manifest[
            "evaluation_rows_read"
        ],
        "reconstruction_evaluation_rows_materialized": reconstruction_manifest[
            "evaluation_rows_materialized"
        ],
        "input_sha256": {
            "TRAIN": sha256_file(train_path),
            "DEV": sha256_file(dev_path),
            "image_manifest": image_manifest_sha256,
        },
        "image_root": str(image_root) if image_root is not None else None,
        "image_set_sha256": config.data.image_set_sha256,
        "unique_image_count": config.data.unique_image_count,
        "total_image_bytes": config.data.total_image_bytes,
        "allowed_splits": ["TRAIN", "DEV"],
        "output_counts": output_counts,
        "output_sha256": output_sha256,
        "dev_case_order": [row.sample_id for row in dev_rows],
        "evaluation_rows_read": False,
        "evaluation_rows_materialized": False,
        "canonical_evaluation_read": False,
    }
    write_create_only_json(manifest_output_path, manifest)
    return manifest


def _load_evaluation_rows(
    path: Path,
    *,
    bindings: S5IclEvaluationBindingsV3,
) -> list[S5IclDatasetRowV3]:
    _require_regular_file(path, role=f"{bindings.split.value} evaluation rows")
    payload = path.read_bytes()
    if sha256_bytes(payload) != bindings.evaluation_rows_sha256:
        raise ValueError(f"{bindings.split.value} evaluation-row digest mismatch")
    rows = [
        S5IclDatasetRowV3.model_validate(json.loads(line))
        for line in payload.splitlines()
    ]
    if len(rows) != bindings.row_count or {row.split for row in rows} != {
        bindings.split
    }:
        raise ValueError(f"{bindings.split.value} evaluation-row identity mismatch")
    if len({row.sample_id for row in rows}) != len(rows):
        raise ValueError("evaluation sample IDs must be unique")
    if len({row.component_id for row in rows}) != bindings.component_count:
        raise ValueError("evaluation component count mismatch")
    return rows


def _validate_read_once_evaluation_attestation(
    path: Path,
    *,
    config: S5IclConfigV3,
    bindings: S5IclEvaluationBindingsV3,
) -> dict[str, object]:
    _require_regular_file(path, role="unique read-once attestation")
    if sha256_file(path) != bindings.read_once_attestation_sha256:
        raise ValueError("unique read-once attestation digest mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    output_sha256 = payload.get("output_sha256") if isinstance(payload, dict) else None
    row_counts = payload.get("row_counts") if isinstance(payload, dict) else None
    component_counts = (
        payload.get("component_counts") if isinstance(payload, dict) else None
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "QwenBrainS5UniqueReadOnceSplitAttestationV3"
        or payload.get("status") != "PASS"
        or payload.get("process_role") != bindings.read_once_process_role
        or payload.get("dataset_sha256") != bindings.dataset_sha256
        or payload.get("dataset_read_count") != 1
        or payload.get("dataset_decoded_once") is not True
        or payload.get("reconstructed_train_sha256") != bindings.train_sha256
        or payload.get("reconstructed_dev_sha256") != bindings.dev_sha256
        or payload.get("reconstructed_train_row_for_row_exact") is not True
        or payload.get("reconstructed_dev_row_for_row_exact") is not True
        or payload.get("materialized_splits")
        != ["SYNTHETIC_TEST", "MANUAL_BLIND"]
        or payload.get("canonical_evaluation_read") is not False
        or payload.get("canonical_evaluation_materialized") is not False
        or not isinstance(output_sha256, dict)
        or output_sha256.get(bindings.split.value)
        != bindings.evaluation_rows_sha256
        or not isinstance(row_counts, dict)
        or row_counts.get(bindings.split.value) != bindings.row_count
        or not isinstance(component_counts, dict)
        or component_counts.get(bindings.split.value) != bindings.component_count
    ):
        raise ValueError("unique read-once attestation identity mismatch")
    return payload


def build_icl_evaluation_request_manifest(
    *,
    config_path: Path,
    train_path: Path,
    evaluation_rows_path: Path,
    read_once_attestation_path: Path,
    train_image_root: Path,
    train_image_manifest_path: Path,
    evaluation_image_root: Path,
    evaluation_image_manifest_path: Path,
    request_manifest_output_path: Path,
    manifest_output_path: Path,
    bindings: S5IclEvaluationBindingsV3,
) -> dict[str, object]:
    """Build the frozen selected-two-shot request manifest for one evaluation split."""

    config = load_icl_config(config_path)
    outputs = (request_manifest_output_path, manifest_output_path)
    if len(set(outputs)) != len(outputs):
        raise ValueError("evaluation request outputs must be distinct")
    for path in outputs:
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise ValueError("evaluation request output parent must be a regular directory")
        if not os.access(path.parent, os.W_OK | os.X_OK):
            raise PermissionError(
                "evaluation request output parent must be writable and searchable"
            )
    if not train_image_root.is_dir() or train_image_root.is_symlink():
        raise ValueError("TRAIN image root must be a regular directory")
    if not evaluation_image_root.is_dir() or evaluation_image_root.is_symlink():
        raise ValueError("evaluation image root must be a regular directory")
    _require_regular_file(train_image_manifest_path, role="TRAIN image manifest")
    _require_regular_file(
        evaluation_image_manifest_path,
        role="evaluation image materialization manifest",
    )
    expected_rows = {
        S5DatasetSplitV1.SYNTHETIC_TEST: (
            config.paired_evaluation_preregistration.synthetic_test_rows
        ),
        S5DatasetSplitV1.MANUAL_BLIND: (
            config.paired_evaluation_preregistration.manual_blind_rows
        ),
    }[bindings.split]
    expected_components = config.paired_evaluation_preregistration.expected_component_counts[
        bindings.split.value
    ]
    if bindings.process_role == "AUTHORITATIVE_PAIRED_EVALUATION" and (
        bindings.row_count != expected_rows
        or bindings.component_count != expected_components
    ):
        raise ValueError("evaluation bindings do not match the frozen protocol")
    if bindings.process_role == "AUTHORITATIVE_PAIRED_EVALUATION" and (
        bindings.dataset_sha256 != config.data.frozen_dataset_sha256_binding
        or bindings.train_sha256 != config.data.train_sha256
        or bindings.dev_sha256 != config.data.dev_sha256
        or bindings.train_row_count != config.data.train_rows
        or bindings.train_source_count != config.data.train_sources
        or bindings.train_component_count != config.data.train_components
        or bindings.read_once_process_role != "UNIQUE_READ_ONCE_SPLITTER"
    ):
        raise ValueError("authoritative evaluation bindings violate the frozen identities")
    _validate_read_once_evaluation_attestation(
        read_once_attestation_path,
        config=config,
        bindings=bindings,
    )
    train_rows = _load_reconstructed_split(
        train_path,
        expected_sha256=bindings.train_sha256,
        split=S5DatasetSplitV1.TRAIN,
        expected_rows=bindings.train_row_count,
        expected_sources=bindings.train_source_count,
        expected_components=bindings.train_component_count,
    )
    evaluation_rows = _load_evaluation_rows(
        evaluation_rows_path,
        bindings=bindings,
    )
    train_manifest_sha256 = sha256_file(train_image_manifest_path)
    if (
        bindings.process_role == "AUTHORITATIVE_PAIRED_EVALUATION"
        and train_manifest_sha256
        != _FROZEN_TRAIN_DEV_IMAGE_MANIFEST_SHA256
    ):
        raise ValueError("frozen TRAIN image manifest digest mismatch")
    train_hashes = {str(row.image_sha256) for row in train_rows}
    image_manifest = json.loads(
        evaluation_image_manifest_path.read_text(encoding="utf-8")
    )
    entries = image_manifest.get("entries") if isinstance(image_manifest, dict) else None
    expected_image_hashes = {str(row.image_sha256) for row in evaluation_rows}
    if (
        not isinstance(image_manifest, dict)
        or image_manifest.get("schema_version")
        != "QwenBrainS5IclEvaluationImageMaterializationV3"
        or image_manifest.get("status") != "PASS"
        or image_manifest.get("experiment_identity") != config.experiment_identity
        or image_manifest.get("process_role") != bindings.process_role
        or image_manifest.get("config_sha256") != sha256_file(config_path)
        or image_manifest.get("split") != bindings.split.value
        or image_manifest.get("evaluation_rows_sha256")
        != bindings.evaluation_rows_sha256
        or image_manifest.get("read_once_attestation_sha256")
        != bindings.read_once_attestation_sha256
        or image_manifest.get("row_count") != bindings.row_count
        or image_manifest.get("component_count") != bindings.component_count
        or image_manifest.get("evaluation_rows_read") is not True
        or image_manifest.get("evaluation_split_materialized_by_unique_splitter")
        is not True
        or image_manifest.get("canonical_images_materialized") is not False
        or not isinstance(entries, list)
        or {entry.get("image_sha256") for entry in entries} != expected_image_hashes
        or {entry.get("relative_path") for entry in entries}
        != {f"images/{digest}.png" for digest in expected_image_hashes}
        or {path.name for path in evaluation_image_root.iterdir()}
        != {f"{digest}.png" for digest in expected_image_hashes}
    ):
        raise ValueError("evaluation image materialization identity mismatch")
    image_paths_by_sha256 = _load_content_addressed_image_index(
        train_image_root=train_image_root,
        train_image_manifest_path=train_image_manifest_path,
        evaluation_image_root=evaluation_image_root,
        evaluation_image_manifest_path=evaluation_image_manifest_path,
        expected_train_manifest_sha256=train_manifest_sha256,
        expected_evaluation_manifest_sha256=sha256_file(
            evaluation_image_manifest_path
        ),
    )
    if not (train_hashes | expected_image_hashes).issubset(
        image_paths_by_sha256
    ):
        raise ValueError("request image digest is absent from frozen manifests")

    policy = next(
        policy
        for policy in config.policies
        if policy.policy_id
        == config.paired_evaluation_preregistration.selected_policy_id
    )
    records = [
        build_request_record(
            target=row,
            demonstrations=select_demonstrations(train_rows, row, policy),
            policy=policy,
            image_root=evaluation_image_root,
        )
        for row in evaluation_rows
    ]
    for record in records:
        demonstration_hashes = {
            str(message["content"][0]["image_sha256"])
            for message in record["messages"][:-1]
            if message["role"] == "user"
        }
        for message in record["messages"][:-1]:
            if message["role"] == "user":
                image_part = message["content"][0]
                image_part["image_path"] = f"sha256:{image_part['image_sha256']}"
        target_image = record["messages"][-1]["content"][0]
        target_image["image_path"] = f"sha256:{target_image['image_sha256']}"
        if target_image["image_sha256"] in demonstration_hashes:
            raise ValueError("evaluation target image overlaps selected demonstrations")
        record.pop("request_identity_sha256")
        record["request_identity_sha256"] = sha256_bytes(canonical_json(record).encode())
    request_payload = (
        "\n".join(canonical_json(record) for record in records) + "\n"
    ).encode()
    _write_create_only(request_manifest_output_path, request_payload)
    manifest: dict[str, object] = {
        "schema_version": "QwenBrainS5IclEvaluationRequestManifestBundleV3",
        "status": "PASS",
        "experiment_identity": config.experiment_identity,
        "process_role": bindings.process_role,
        "config_sha256": sha256_file(config_path),
        "split": bindings.split.value,
        "policy_id": policy.policy_id,
        "shot_count": policy.shot_count,
        "train_sha256": sha256_file(train_path),
        "evaluation_rows_sha256": sha256_file(evaluation_rows_path),
        "read_once_attestation_sha256": sha256_file(read_once_attestation_path),
        "train_image_manifest_sha256": train_manifest_sha256,
        "evaluation_image_manifest_sha256": sha256_file(
            evaluation_image_manifest_path
        ),
        "image_resolution_policy": "SHA256_MANIFEST_ONLY_PATH_STRINGS_NOT_IO_AUTHORITY",
        "request_manifest_sha256": sha256_bytes(request_payload),
        "row_count": len(records),
        "component_count": len({row.component_id for row in evaluation_rows}),
        "case_order": [row.sample_id for row in evaluation_rows],
        "evaluation_rows_read": True,
        "evaluation_split_materialized_by_unique_splitter": True,
        "canonical_evaluation_read": False,
    }
    write_create_only_json(manifest_output_path, manifest)
    return manifest


def _data_url(path: Path) -> str:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def materialize_http_messages(messages: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role != "user":
            result.append({"role": role, "content": content})
            continue
        if not isinstance(content, list) or len(content) != 2:
            raise ValueError("ICL user turn must contain exactly image then text")
        image_part, text_part = content
        if not isinstance(image_part, Mapping) or not isinstance(text_part, Mapping):
            raise TypeError("ICL user turn content parts must be objects")
        if image_part.get("type") != "image" or text_part.get("type") != "text":
            raise ValueError("ICL user turn must preserve image-then-text order")
        image_path = Path(str(image_part.get("image_path")))
        image_sha256 = image_part.get("image_sha256")
        _require_regular_file(image_path, role="ICL request image")
        if sha256_file(image_path) != image_sha256:
            raise ValueError("ICL request image digest mismatch")
        result.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(image_path)},
                    },
                    {"type": "text", "text": text_part.get("text")},
                ],
            }
        )
    return result


def _extract_content(payload: object) -> str:
    if not isinstance(payload, Mapping):
        raise TypeError("response body is not a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("response has no choices")
    choice = choices[0]
    if not isinstance(choice, Mapping) or not isinstance(choice.get("message"), Mapping):
        raise TypeError("response choice has no message")
    content = choice["message"].get("content")
    if not isinstance(content, str):
        raise TypeError("response message content is not a string")
    return content


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip() in {"```", "```json"} and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise TypeError("model content is not a JSON object")
    return payload


def _open_without_proxy(outbound: request.Request, timeout_s: float):
    return request.build_opener(request.ProxyHandler({})).open(
        outbound,
        timeout=timeout_s,
    )


def _plan_signature(plan: CommanderPlanV1) -> str:
    payload = plan.model_dump(mode="json")
    payload.pop("rationale", None)
    return canonical_json(payload)


def _request_body(
    *,
    config: S5IclConfigV3,
    messages: Sequence[Mapping[str, object]],
    model: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": model,
        "messages": materialize_http_messages(messages),
        "temperature": config.decoding.temperature,
        "max_tokens": config.decoding.max_tokens,
        "chat_template_kwargs": {"enable_thinking": config.decoding.enable_thinking},
    }
    if config.decoding.guided_json:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "commander_plan_v1",
                "schema": CommanderPlanV1.model_json_schema(),
            },
        }
    return body


def evaluate_icl_response(
    *,
    record: Mapping[str, object],
    payload: object,
) -> dict[str, object]:
    expectation = S5IclEvaluationExpectationV3.model_validate(record["expectation"])
    try:
        observed_plan = CommanderPlanV1.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - invalid model output remains in denominator
        return {
            "strict_valid": False,
            "observed_outcome": "ERROR",
            "expectation_match": False,
            "primitive_checks_pass": False,
            "reassociation_boundary_pass": False,
            "structural_plan_match": False,
            "reasons": [f"{type(exc).__name__}: {exc}"],
        }
    primitive_counts = Counter(flatten_primitives(observed_plan))
    missing_primitive_counts = {
        primitive: expected_count - primitive_counts[primitive]
        for primitive, expected_count in expectation.required_primitive_counts.items()
        if primitive_counts[primitive] < expected_count
    }
    forbidden = sorted(
        set(primitive_counts) & set(expectation.forbidden_primitives)
    )
    missing_target_refs = sorted(
        set(expectation.expected_target_refs) - flatten_target_refs(observed_plan)
    )
    observed_outcome = "REFUSE" if observed_plan.refused else "PLAN"
    boundary = audit_reassociation_boundary(
        observed_plan,
        unresolved_binding=expectation.unresolved_binding,
    )
    reasons = []
    if observed_outcome != expectation.expected_outcome:
        reasons.append(
            "outcome mismatch: expected "
            f"{expectation.expected_outcome}, observed {observed_outcome}"
        )
    if missing_primitive_counts:
        reasons.append(
            f"missing required primitive counts: {missing_primitive_counts}"
        )
    if forbidden:
        reasons.append(f"forbidden primitives present: {forbidden}")
    if missing_target_refs:
        reasons.append(f"missing expected target refs: {missing_target_refs}")
    if boundary.status != "PASS":
        reasons.extend(
            f"reassociation boundary: {reason}" for reason in boundary.reasons
        )
    primitive_checks_pass = (
        not missing_primitive_counts and not forbidden and not missing_target_refs
    )
    expectation_match = (
        observed_outcome == expectation.expected_outcome
        and primitive_checks_pass
        and boundary.status == "PASS"
    )
    expected_plan = CommanderPlanV1.model_validate(record["target_plan"])
    structural_match = _plan_signature(observed_plan) == _plan_signature(expected_plan)
    return {
        "strict_valid": True,
        "observed_outcome": observed_outcome,
        "expectation_match": expectation_match,
        "primitive_checks_pass": primitive_checks_pass,
        "reassociation_boundary_pass": boundary.status == "PASS",
        "structural_plan_match": structural_match,
        "reasons": reasons,
    }


def _load_request_manifest(
    path: Path,
    *,
    expected_rows: int = 78,
    expected_split: S5DatasetSplitV1 | None = None,
) -> list[dict[str, object]]:
    _require_regular_file(path, role="ICL request manifest")
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    if len(records) != expected_rows:
        raise ValueError("ICL request manifest row count mismatch")
    if any(not isinstance(record, dict) for record in records):
        raise TypeError("ICL request records must be JSON objects")
    if expected_split is not None and {
        record.get("split") for record in records
    } != {expected_split.value}:
        raise ValueError("ICL request manifest split mismatch")
    case_ids = [record.get("case_id") for record in records]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("ICL request case IDs must be unique")
    for record in records:
        identity = record.pop("request_identity_sha256", None)
        expected = sha256_bytes(canonical_json(record).encode())
        record["request_identity_sha256"] = identity
        if identity != expected:
            raise ValueError("ICL request identity digest mismatch")
    return records


def _metric_summary(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    count = len(results)
    if count == 0:
        raise ValueError("ICL report cannot use an empty denominator")
    metrics = {}
    for field, label in (
        ("expectation_match", "expectation_match"),
        ("strict_valid", "strict_valid"),
        ("primitive_checks_pass", "primitive_check_pass"),
        ("reassociation_boundary_pass", "reassociation_boundary_pass"),
        ("structural_plan_match", "structural_plan_match"),
    ):
        passed = sum(result.get(field) is True for result in results)
        metrics[f"{label}_count"] = passed
        metrics[f"{label}_rate"] = passed / count
    metrics["case_count"] = count
    return metrics


def run_icl_dev_manifest(
    *,
    config_path: Path,
    request_manifest_path: Path,
    endpoint: str,
    model: str,
    evidence_root: Path,
    report_output_path: Path,
    timeout_s: float = 600.0,
) -> dict[str, object]:
    """Run a frozen DEV manifest against a separately authorized HTTP endpoint."""
    config = load_icl_config(config_path)
    if report_output_path.exists() or report_output_path.is_symlink():
        raise FileExistsError(report_output_path)
    records = _load_request_manifest(request_manifest_path)
    policy_ids = {record.get("policy_id") for record in records}
    shot_counts = {record.get("shot_count") for record in records}
    if len(policy_ids) != 1 or len(shot_counts) != 1:
        raise ValueError("one DEV run must contain exactly one frozen policy")
    policy_id = str(next(iter(policy_ids)))
    policy_by_id = {policy.policy_id: policy for policy in config.policies}
    if policy_id not in policy_by_id or shot_counts != {policy_by_id[policy_id].shot_count}:
        raise ValueError("DEV request policy identity is not frozen in the config")

    results: list[dict[str, object]] = []
    for record in records:
        case_id = str(record["case_id"])
        body = _request_body(
            config=config,
            messages=record["messages"],
            model=model,
        )
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        status: int | None = None
        response_body = ""
        content: str | None = None
        parsed_payload: object = None
        failure: str | None = None
        evaluation = {
            "strict_valid": False,
            "observed_outcome": "ERROR",
            "expectation_match": False,
            "primitive_checks_pass": False,
            "reassociation_boundary_pass": False,
            "structural_plan_match": False,
            "reasons": [],
        }
        try:
            outbound = request.Request(
                endpoint.rstrip("/") + "/v1/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _open_without_proxy(outbound, timeout_s) as incoming:
                status = incoming.status
                response_body = incoming.read().decode("utf-8")
            content = _extract_content(json.loads(response_body))
            parsed_payload = _extract_json_object(content)
            evaluation = evaluate_icl_response(record=record, payload=parsed_payload)
        except error.HTTPError as exc:
            status = exc.code
            response_body = exc.read().decode("utf-8", errors="replace")
            failure = f"HTTPError: {exc}"
        except Exception as exc:  # noqa: BLE001 - every model or transport failure stays in the denominator
            failure = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started
        if failure is not None:
            evaluation["reasons"] = [failure]
        result = {
            "case_id": case_id,
            "family": record["family"],
            "component_id": record["component_id"],
            "source_identity_sha256": record["source_identity_sha256"],
            **evaluation,
        }
        results.append(result)
        attempt = {
            "schema_version": "QwenBrainS5IclAttemptV3",
            "experiment_identity": config.experiment_identity,
            "policy_id": policy_id,
            "case_id": case_id,
            "started_at_utc": started_at,
            "elapsed_s": elapsed,
            "endpoint": endpoint,
            "model": model,
            "request_identity_sha256": record["request_identity_sha256"],
            "http_request_body": body,
            "http_status": status,
            "http_response_body": response_body,
            "parsed_content": content,
            "parsed_payload": parsed_payload,
            "failure": failure,
            "evaluation": evaluation,
        }
        write_create_only_json(evidence_root / policy_id / f"{case_id}.json", attempt)

    report: dict[str, object] = {
        "schema_version": "QwenBrainS5IclDevReportV3",
        "status": "PASS",
        "experiment_identity": config.experiment_identity,
        "split": "DEV",
        "policy_id": policy_id,
        "shot_count": policy_by_id[policy_id].shot_count,
        "config_sha256": sha256_file(config_path),
        "request_manifest_sha256": sha256_file(request_manifest_path),
        "endpoint": endpoint,
        "model": model,
        "decoding": config.decoding.model_dump(mode="json"),
        "denominator_policy": "ALL_78_FROZEN_DEV_ROWS_NO_RETRY_NO_SELECTION",
        "metrics": _metric_summary(results),
        "family_counts": dict(sorted(Counter(result["family"] for result in results).items())),
        "results": results,
        "evaluation_rows_read": False,
        "evaluation_rows_materialized": False,
        "canonical_evaluation_read": False,
    }
    write_create_only_json(report_output_path, report)
    return report


def _load_content_addressed_image_index(
    *,
    train_image_root: Path,
    train_image_manifest_path: Path,
    evaluation_image_root: Path,
    evaluation_image_manifest_path: Path,
    expected_train_manifest_sha256: str = _FROZEN_TRAIN_DEV_IMAGE_MANIFEST_SHA256,
    expected_evaluation_manifest_sha256: str | None = None,
) -> dict[str, Path]:
    """Resolve request images only from digest-bound frozen manifests."""

    if not train_image_root.is_dir() or train_image_root.is_symlink():
        raise ValueError("TRAIN image root must be a regular directory")
    if not evaluation_image_root.is_dir() or evaluation_image_root.is_symlink():
        raise ValueError("evaluation image root must be a regular directory")
    _require_regular_file(train_image_manifest_path, role="TRAIN image manifest")
    _require_regular_file(
        evaluation_image_manifest_path,
        role="evaluation image manifest",
    )
    if sha256_file(train_image_manifest_path) != expected_train_manifest_sha256:
        raise ValueError("frozen TRAIN image manifest digest mismatch")
    if (
        expected_evaluation_manifest_sha256 is not None
        and sha256_file(evaluation_image_manifest_path)
        != expected_evaluation_manifest_sha256
    ):
        raise ValueError("frozen evaluation image manifest digest mismatch")
    manifests = (
        (
            "TRAIN",
            train_image_root,
            json.loads(train_image_manifest_path.read_text(encoding="utf-8")),
        ),
        (
            "evaluation",
            evaluation_image_root,
            json.loads(evaluation_image_manifest_path.read_text(encoding="utf-8")),
        ),
    )
    index: dict[str, Path] = {}
    for manifest_role, image_root, manifest in manifests:
        entries = manifest.get("entries") if isinstance(manifest, dict) else None
        expected_schema = (
            "QwenBrainS5IclImageMaterializationV2"
            if manifest_role == "TRAIN"
            else "QwenBrainS5IclEvaluationImageMaterializationV3"
        )
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != expected_schema
            or manifest.get("status") != "PASS"
            or not isinstance(entries, list)
            or manifest.get("unique_image_count") != len(entries)
            or manifest.get("total_image_bytes")
            != sum(
                entry.get("size_bytes", -1)
                for entry in entries
                if isinstance(entry, Mapping)
            )
        ):
            raise ValueError(
                f"content-addressed {manifest_role} image manifest is invalid"
            )
        expected_names: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise TypeError("content-addressed image manifest entry is invalid")
            digest = entry.get("image_sha256")
            size_bytes = entry.get("size_bytes")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 1
            ):
                raise ValueError("content-addressed image identity is invalid")
            if manifest_role == "TRAIN":
                splits = entry.get("splits")
                if (
                    not isinstance(splits, list)
                    or not splits
                    or any(split not in {"TRAIN", "DEV"} for split in splits)
                ):
                    raise ValueError("frozen TRAIN image split identity is invalid")
            name = f"{digest}.png"
            if name in expected_names:
                raise ValueError("content-addressed image digest is duplicated")
            expected_names.add(name)
            path = image_root / name
            _require_regular_file(path, role="content-addressed request image")
            if (
                entry.get("relative_path") != f"images/{name}"
                or sha256_file(path) != digest
                or path.stat().st_size != size_bytes
            ):
                raise ValueError("content-addressed image identity mismatch")
            prior = index.setdefault(digest, path)
            if prior != path:
                raise ValueError("one image digest maps to multiple manifest roots")
        if {path.name for path in image_root.iterdir()} != expected_names:
            raise ValueError("content-addressed image root differs from its manifest")
    return index


def _materialize_processor_messages(
    messages: Sequence[Mapping[str, object]],
    *,
    image_paths_by_sha256: Mapping[str, Path] | None = None,
) -> tuple[list[dict[str, object]], list[Any]]:
    from PIL import Image

    processor_messages: list[dict[str, object]] = []
    images: list[Any] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role != "user":
            processor_messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list) or len(content) != 2:
            raise ValueError("ICL user turn must contain exactly image then text")
        image_part, text_part = content
        if not isinstance(image_part, Mapping) or not isinstance(text_part, Mapping):
            raise TypeError("ICL user turn content parts must be objects")
        if image_part.get("type") != "image" or text_part.get("type") != "text":
            raise ValueError("ICL user turn must preserve image-then-text order")
        image_sha256 = str(image_part.get("image_sha256"))
        if image_paths_by_sha256 is None:
            image_path = Path(str(image_part.get("image_path")))
        else:
            if image_part.get("image_path") != f"sha256:{image_sha256}":
                raise ValueError("ICL request path is not a content-addressed placeholder")
            try:
                image_path = image_paths_by_sha256[image_sha256]
            except KeyError as exc:
                raise ValueError("ICL request image digest is absent from manifests") from exc
        _require_regular_file(image_path, role="ICL processor image")
        if sha256_file(image_path) != image_sha256:
            raise ValueError("ICL processor image digest mismatch")
        with Image.open(image_path) as source:
            images.append(source.convert("RGB"))
        processor_messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": images[-1]},
                    {"type": "text", "text": text_part.get("text")},
                ],
            }
        )
    return processor_messages, images


def run_icl_dev_transformers(
    *,
    config_path: Path,
    request_manifest_paths: Mapping[str, Path],
    adapter_path: Path | None,
    evidence_root: Path,
    report_output_paths: Mapping[str, Path],
) -> list[dict[str, object]]:
    """Run frozen DEV policies by direct local Transformers inference.

    Base ICL must cover all three policies. The trained adapter is restricted to the
    already-selected two-shot policy for the A3 supporting analysis.
    """

    config = load_icl_config(config_path)
    policy_by_id = {policy.policy_id: policy for policy in config.policies}
    expected_policy_ids = (
        {config.paired_evaluation_preregistration.selected_policy_id}
        if adapter_path is not None
        else set(policy_by_id)
    )
    if set(request_manifest_paths) != expected_policy_ids:
        raise ValueError("request manifest paths do not match the authorized policy set")
    if set(report_output_paths) != expected_policy_ids:
        raise ValueError("report output paths do not match the authorized policy set")
    outputs = list(report_output_paths.values())
    if len(set(outputs)) != len(outputs):
        raise ValueError("DEV report output paths must be distinct")
    for path in outputs:
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    if adapter_path is not None and (not adapter_path.is_dir() or adapter_path.is_symlink()):
        raise ValueError("adapter must be a regular non-symlink directory")

    import torch
    from peft import PeftModel
    from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration

    torch.manual_seed(config.paired_evaluation_preregistration.bootstrap_seed)
    torch.cuda.manual_seed_all(config.paired_evaluation_preregistration.bootstrap_seed)
    torch.use_deterministic_algorithms(config.runtime.deterministic_algorithms)
    torch.backends.cudnn.benchmark = config.runtime.cudnn_benchmark
    torch.set_float32_matmul_precision(config.runtime.matmul_precision)
    if torch.cuda.device_count() != 1:
        raise ValueError("authorized ICL runtime must expose exactly one CUDA device")
    if torch.cuda.get_device_name(config.runtime.cuda_device_index) != config.runtime.accelerator:
        raise ValueError("authorized ICL accelerator identity mismatch")

    environment_report = Path(config.runtime.environment_identity_report_path)
    _require_regular_file(environment_report, role="ICL environment identity report")
    if sha256_file(environment_report) != config.runtime.environment_identity_sha256:
        raise ValueError("ICL environment identity report digest mismatch")
    snapshot = Path(config.runtime.snapshot_path)
    snapshot_before, ignored_dirs_before = snapshot_tree_identity(
        snapshot,
        expected_file_count=config.runtime.snapshot_regular_file_count,
    )
    if snapshot_before != config.runtime.snapshot_tree_sha256:
        raise ValueError("frozen ICL snapshot digest mismatch")
    for name, expected_sha256 in (
        ("tokenizer_config.json", config.runtime.tokenizer_config_sha256),
        ("tokenizer.json", config.runtime.tokenizer_json_sha256),
        ("chat_template.jinja", config.runtime.chat_template_sha256),
        ("preprocessor_config.json", config.runtime.preprocessor_config_sha256),
    ):
        path = snapshot / name
        _require_regular_file(path, role=f"frozen ICL processor file {name}")
        if sha256_file(path) != expected_sha256:
            raise ValueError(f"frozen ICL processor digest mismatch: {name}")

    processor = AutoProcessor.from_pretrained(snapshot, local_files_only=True)
    model: Any = Qwen3_5ForConditionalGeneration.from_pretrained(
        snapshot,
        local_files_only=True,
        dtype=torch.bfloat16,
        device_map={"": config.runtime.cuda_device_index},
        low_cpu_mem_usage=True,
        use_kernels=False,
    )
    system_kind = "BASE_ICL"
    adapter_tree_sha256 = None
    if adapter_path is not None:
        adapter_tree_sha256, _ = regular_tree_identity(adapter_path)
        if (
            adapter_tree_sha256
            != config.paired_evaluation_preregistration.trained_adapter_tree_sha256
        ):
            raise ValueError("trained adapter tree identity mismatch")
        model = PeftModel.from_pretrained(model, adapter_path, is_trainable=False)
        system_kind = "TRAINED_LORA"
    model.eval()

    reports = []
    pending_reports: list[tuple[Path, dict[str, object]]] = []
    with torch.inference_mode():
        for policy_id in sorted(expected_policy_ids):
            records = _load_request_manifest(request_manifest_paths[policy_id])
            if {record.get("policy_id") for record in records} != {policy_id}:
                raise ValueError("DEV request manifest policy mismatch")
            results = []
            for record in records:
                case_id = str(record["case_id"])
                started_at = datetime.now(timezone.utc).isoformat()
                started = time.monotonic()
                generated_text = ""
                parsed_payload: object = None
                failure: str | None = None
                evaluation = {
                    "strict_valid": False,
                    "observed_outcome": "ERROR",
                    "expectation_match": False,
                    "primitive_checks_pass": False,
                    "reassociation_boundary_pass": False,
                    "structural_plan_match": False,
                    "reasons": [],
                }
                images: list[Any] = []
                try:
                    processor_messages, images = _materialize_processor_messages(
                        record["messages"]
                    )
                    encoded = processor.apply_chat_template(
                        processor_messages,
                        tokenize=True,
                        add_generation_prompt=True,
                        return_dict=True,
                        return_tensors="pt",
                        enable_thinking=False,
                    )
                    encoded = {
                        key: value.to(config.runtime.cuda_device_index)
                        if hasattr(value, "to")
                        else value
                        for key, value in encoded.items()
                    }
                    input_length = encoded["input_ids"].shape[-1]
                    generated = model.generate(
                        **encoded,
                        do_sample=False,
                        max_new_tokens=config.decoding.max_tokens,
                        use_cache=True,
                    )
                    generated_text = processor.decode(
                        generated[0, input_length:],
                        skip_special_tokens=True,
                    )
                    parsed_payload = _extract_json_object(generated_text)
                    evaluation = evaluate_icl_response(record=record, payload=parsed_payload)
                except Exception as exc:  # noqa: BLE001 - every generation failure stays in the denominator
                    failure = f"{type(exc).__name__}: {exc}"
                    evaluation["reasons"] = [failure]
                finally:
                    for image in images:
                        image.close()
                elapsed = time.monotonic() - started
                result = {
                    "case_id": case_id,
                    "family": record["family"],
                    "component_id": record["component_id"],
                    "source_identity_sha256": record["source_identity_sha256"],
                    **evaluation,
                }
                results.append(result)
                attempt = {
                    "schema_version": "QwenBrainS5IclTransformersAttemptV3",
                    "experiment_identity": config.experiment_identity,
                    "system_kind": system_kind,
                    "policy_id": policy_id,
                    "case_id": case_id,
                    "started_at_utc": started_at,
                    "elapsed_s": elapsed,
                    "request_identity_sha256": record["request_identity_sha256"],
                    "generated_text": generated_text,
                    "parsed_payload": parsed_payload,
                    "failure": failure,
                    "evaluation": evaluation,
                }
                write_create_only_json(
                    evidence_root / system_kind / policy_id / f"{case_id}.json",
                    attempt,
                )
            report: dict[str, object] = {
                "schema_version": "QwenBrainS5IclDevReportV3",
                "status": "PASS",
                "experiment_identity": config.experiment_identity,
                "system_kind": system_kind,
                "split": "DEV",
                "policy_id": policy_id,
                "shot_count": policy_by_id[policy_id].shot_count,
                "config_sha256": sha256_file(config_path),
                "request_manifest_sha256": sha256_file(
                    request_manifest_paths[policy_id]
                ),
                "model": config.model,
                "snapshot_tree_sha256_before": snapshot_before,
                "ignored_top_level_dirs_before": ignored_dirs_before,
                "environment_identity_sha256": sha256_file(environment_report),
                "adapter_tree_sha256": adapter_tree_sha256,
                "decoding": config.decoding.model_dump(mode="json"),
                "denominator_policy": "ALL_78_FROZEN_DEV_ROWS_NO_RETRY_NO_SELECTION",
                "component_count": len({result["component_id"] for result in results}),
                "evidence_role": (
                    "TUNING_SPLIT_SUPPORTING_ANALYSIS_ONLY_BOTH_ARMS_HAVE_SEEN_DEV"
                    if system_kind == "TRAINED_LORA"
                    else "DEV_POLICY_SELECTION_BASELINE"
                ),
                "primary_test_or_blind_evidence": False,
                "metrics": _metric_summary(results),
                "family_counts": dict(
                    sorted(Counter(result["family"] for result in results).items())
                ),
                "results": results,
                "evaluation_rows_read": False,
                "evaluation_rows_materialized": False,
                "canonical_evaluation_read": False,
            }
            pending_reports.append((report_output_paths[policy_id], report))
            reports.append(report)
    snapshot_after, ignored_dirs_after = snapshot_tree_identity(
        snapshot,
        expected_file_count=config.runtime.snapshot_regular_file_count,
    )
    if snapshot_after != snapshot_before or ignored_dirs_after != ignored_dirs_before:
        raise ValueError("snapshot identity changed during direct ICL DEV inference")
    if adapter_path is not None:
        adapter_tree_after, _ = regular_tree_identity(adapter_path)
        if adapter_tree_after != adapter_tree_sha256:
            raise ValueError("adapter identity changed during direct ICL DEV inference")
    for output_path, report in pending_reports:
        report["snapshot_tree_sha256_after"] = snapshot_after
        report["ignored_top_level_dirs_after"] = ignored_dirs_after
        write_create_only_json(output_path, report)
    return reports


def run_icl_evaluation_transformers(
    *,
    config_path: Path,
    request_manifest_path: Path,
    request_bundle_path: Path,
    train_image_root: Path,
    train_image_manifest_path: Path,
    evaluation_image_root: Path,
    evaluation_image_manifest_path: Path,
    adapter_path: Path,
    evidence_root: Path,
    baseline_report_output_path: Path,
    candidate_report_output_path: Path,
    bindings: S5IclEvaluationBindingsV3,
) -> list[dict[str, object]]:
    """Evaluate one frozen TEST or BLIND manifest once under both paired arms."""

    config = load_icl_config(config_path)
    outputs = (baseline_report_output_path, candidate_report_output_path)
    if len(set(outputs)) != len(outputs):
        raise ValueError("paired evaluation report outputs must be distinct")
    for path in outputs:
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    if bindings.process_role != "AUTHORITATIVE_PAIRED_EVALUATION":
        raise ValueError("model evaluation requires authoritative frozen bindings")
    expected_rows = {
        S5DatasetSplitV1.SYNTHETIC_TEST: (
            config.paired_evaluation_preregistration.synthetic_test_rows
        ),
        S5DatasetSplitV1.MANUAL_BLIND: (
            config.paired_evaluation_preregistration.manual_blind_rows
        ),
    }[bindings.split]
    expected_components = config.paired_evaluation_preregistration.expected_component_counts[
        bindings.split.value
    ]
    if (
        bindings.row_count != expected_rows
        or bindings.component_count != expected_components
        or bindings.dataset_sha256 != config.data.frozen_dataset_sha256_binding
        or bindings.train_sha256 != config.data.train_sha256
        or bindings.dev_sha256 != config.data.dev_sha256
    ):
        raise ValueError("model evaluation bindings violate the frozen protocol")
    _require_regular_file(request_bundle_path, role="evaluation request bundle")
    request_bundle = json.loads(request_bundle_path.read_text(encoding="utf-8"))
    if (
        not isinstance(request_bundle, dict)
        or request_bundle.get("schema_version")
        != "QwenBrainS5IclEvaluationRequestManifestBundleV3"
        or request_bundle.get("status") != "PASS"
        or request_bundle.get("experiment_identity") != config.experiment_identity
        or request_bundle.get("process_role") != bindings.process_role
        or request_bundle.get("config_sha256") != sha256_file(config_path)
        or request_bundle.get("split") != bindings.split.value
        or request_bundle.get("policy_id")
        != config.paired_evaluation_preregistration.selected_policy_id
        or request_bundle.get("shot_count")
        != config.paired_evaluation_preregistration.selected_shot_count
        or request_bundle.get("evaluation_rows_sha256")
        != bindings.evaluation_rows_sha256
        or request_bundle.get("read_once_attestation_sha256")
        != bindings.read_once_attestation_sha256
        or request_bundle.get("request_manifest_sha256")
        != sha256_file(request_manifest_path)
        or request_bundle.get("row_count") != bindings.row_count
        or request_bundle.get("component_count") != bindings.component_count
        or request_bundle.get("evaluation_rows_read") is not True
        or request_bundle.get("evaluation_split_materialized_by_unique_splitter")
        is not True
        or request_bundle.get("canonical_evaluation_read") is not False
    ):
        raise ValueError("evaluation request bundle identity mismatch")
    records = _load_request_manifest(
        request_manifest_path,
        expected_rows=bindings.row_count,
        expected_split=bindings.split,
    )
    if [record.get("case_id") for record in records] != request_bundle.get(
        "case_order"
    ):
        raise ValueError("evaluation request order differs from the frozen bundle")
    if {record.get("policy_id") for record in records} != {
        config.paired_evaluation_preregistration.selected_policy_id
    } or {record.get("shot_count") for record in records} != {
        config.paired_evaluation_preregistration.selected_shot_count
    }:
        raise ValueError("evaluation request policy identity mismatch")
    if not adapter_path.is_dir() or adapter_path.is_symlink():
        raise ValueError("adapter must be a regular non-symlink directory")
    train_image_manifest_sha256 = request_bundle.get(
        "train_image_manifest_sha256"
    )
    evaluation_image_manifest_sha256 = request_bundle.get(
        "evaluation_image_manifest_sha256"
    )
    if (
        train_image_manifest_sha256 != sha256_file(train_image_manifest_path)
        or evaluation_image_manifest_sha256
        != sha256_file(evaluation_image_manifest_path)
    ):
        raise ValueError("evaluation request image manifests differ from the bundle")
    image_paths_by_sha256 = _load_content_addressed_image_index(
        train_image_root=train_image_root,
        train_image_manifest_path=train_image_manifest_path,
        evaluation_image_root=evaluation_image_root,
        evaluation_image_manifest_path=evaluation_image_manifest_path,
        expected_evaluation_manifest_sha256=str(
            evaluation_image_manifest_sha256
        ),
    )
    if (
        request_bundle.get("image_resolution_policy")
        != "SHA256_MANIFEST_ONLY_PATH_STRINGS_NOT_IO_AUTHORITY"
    ):
        raise ValueError("evaluation request image resolution policy mismatch")
    request_image_hashes = {
        str(message["content"][0]["image_sha256"])
        for record in records
        for message in record["messages"]
        if message.get("role") == "user"
    }
    if not request_image_hashes.issubset(image_paths_by_sha256):
        raise ValueError("evaluation request references an unmaterialized image digest")

    import torch
    from peft import PeftModel
    from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration

    torch.manual_seed(config.paired_evaluation_preregistration.bootstrap_seed)
    torch.cuda.manual_seed_all(config.paired_evaluation_preregistration.bootstrap_seed)
    torch.use_deterministic_algorithms(config.runtime.deterministic_algorithms)
    torch.backends.cudnn.benchmark = config.runtime.cudnn_benchmark
    torch.set_float32_matmul_precision(config.runtime.matmul_precision)
    if torch.cuda.device_count() != 1:
        raise ValueError("authorized evaluation runtime must expose one CUDA device")
    if torch.cuda.get_device_name(config.runtime.cuda_device_index) != config.runtime.accelerator:
        raise ValueError("authorized evaluation accelerator identity mismatch")

    environment_report = Path(config.runtime.environment_identity_report_path)
    _require_regular_file(environment_report, role="evaluation environment report")
    if sha256_file(environment_report) != config.runtime.environment_identity_sha256:
        raise ValueError("evaluation environment identity digest mismatch")
    snapshot = Path(config.runtime.snapshot_path)
    snapshot_before, ignored_dirs_before = snapshot_tree_identity(
        snapshot,
        expected_file_count=config.runtime.snapshot_regular_file_count,
    )
    if snapshot_before != config.runtime.snapshot_tree_sha256:
        raise ValueError("frozen evaluation snapshot digest mismatch")
    for name, expected_sha256 in (
        ("tokenizer_config.json", config.runtime.tokenizer_config_sha256),
        ("tokenizer.json", config.runtime.tokenizer_json_sha256),
        ("chat_template.jinja", config.runtime.chat_template_sha256),
        ("preprocessor_config.json", config.runtime.preprocessor_config_sha256),
    ):
        path = snapshot / name
        _require_regular_file(path, role=f"frozen evaluation processor file {name}")
        if sha256_file(path) != expected_sha256:
            raise ValueError(f"frozen evaluation processor digest mismatch: {name}")
    adapter_tree_sha256, _ = regular_tree_identity(adapter_path)
    if (
        adapter_tree_sha256
        != config.paired_evaluation_preregistration.trained_adapter_tree_sha256
    ):
        raise ValueError("trained adapter tree identity mismatch")

    processor = AutoProcessor.from_pretrained(snapshot, local_files_only=True)
    base_model: Any = Qwen3_5ForConditionalGeneration.from_pretrained(
        snapshot,
        local_files_only=True,
        dtype=torch.bfloat16,
        device_map={"": config.runtime.cuda_device_index},
        low_cpu_mem_usage=True,
        use_kernels=False,
    )
    base_model.eval()

    reports: list[dict[str, object]] = []
    pending_reports: list[tuple[Path, dict[str, object]]] = []

    def execute_arm(model: Any, *, system_kind: str) -> dict[str, object]:
        results = []
        with torch.inference_mode():
            for record in records:
                case_id = str(record["case_id"])
                started_at = datetime.now(timezone.utc).isoformat()
                started = time.monotonic()
                generated_text = ""
                parsed_payload: object = None
                failure: str | None = None
                evaluation = {
                    "strict_valid": False,
                    "observed_outcome": "ERROR",
                    "expectation_match": False,
                    "primitive_checks_pass": False,
                    "reassociation_boundary_pass": False,
                    "structural_plan_match": False,
                    "reasons": [],
                }
                images: list[Any] = []
                try:
                    processor_messages, images = _materialize_processor_messages(
                        record["messages"],
                        image_paths_by_sha256=image_paths_by_sha256,
                    )
                    encoded = processor.apply_chat_template(
                        processor_messages,
                        tokenize=True,
                        add_generation_prompt=True,
                        return_dict=True,
                        return_tensors="pt",
                        enable_thinking=False,
                    )
                    encoded = {
                        key: value.to(config.runtime.cuda_device_index)
                        if hasattr(value, "to")
                        else value
                        for key, value in encoded.items()
                    }
                    input_length = encoded["input_ids"].shape[-1]
                    generated = model.generate(
                        **encoded,
                        do_sample=False,
                        max_new_tokens=config.decoding.max_tokens,
                        use_cache=True,
                    )
                    generated_text = processor.decode(
                        generated[0, input_length:],
                        skip_special_tokens=True,
                    )
                    parsed_payload = _extract_json_object(generated_text)
                    evaluation = evaluate_icl_response(
                        record=record,
                        payload=parsed_payload,
                    )
                except Exception as exc:  # noqa: BLE001 - failures remain in denominator
                    failure = f"{type(exc).__name__}: {exc}"
                    evaluation["reasons"] = [failure]
                finally:
                    for image in images:
                        image.close()
                elapsed = time.monotonic() - started
                result = {
                    "case_id": case_id,
                    "family": record["family"],
                    "component_id": record["component_id"],
                    "source_identity_sha256": record["source_identity_sha256"],
                    **evaluation,
                }
                results.append(result)
                attempt = {
                    "schema_version": "QwenBrainS5IclEvaluationAttemptV3",
                    "experiment_identity": config.experiment_identity,
                    "system_kind": system_kind,
                    "split": bindings.split.value,
                    "policy_id": config.paired_evaluation_preregistration.selected_policy_id,
                    "case_id": case_id,
                    "started_at_utc": started_at,
                    "elapsed_s": elapsed,
                    "request_identity_sha256": record["request_identity_sha256"],
                    "generated_text": generated_text,
                    "parsed_payload": parsed_payload,
                    "failure": failure,
                    "evaluation": evaluation,
                }
                write_create_only_json(
                    evidence_root / system_kind / f"{case_id}.json",
                    attempt,
                )
        report: dict[str, object] = {
            "schema_version": "QwenBrainS5IclEvaluationReportV3",
            "status": "PASS",
            "experiment_identity": config.experiment_identity,
            "system_kind": system_kind,
            "split": bindings.split.value,
            "policy_id": config.paired_evaluation_preregistration.selected_policy_id,
            "shot_count": config.paired_evaluation_preregistration.selected_shot_count,
            "config_sha256": sha256_file(config_path),
            "request_manifest_sha256": sha256_file(request_manifest_path),
            "request_bundle_sha256": sha256_file(request_bundle_path),
            "train_image_manifest_sha256": train_image_manifest_sha256,
            "evaluation_image_manifest_sha256": (
                evaluation_image_manifest_sha256
            ),
            "image_resolution_policy": (
                "SHA256_MANIFEST_ONLY_PATH_STRINGS_NOT_IO_AUTHORITY"
            ),
            "read_once_attestation_sha256": bindings.read_once_attestation_sha256,
            "evaluation_rows_sha256": bindings.evaluation_rows_sha256,
            "model": config.model,
            "snapshot_tree_sha256_before": snapshot_before,
            "ignored_top_level_dirs_before": ignored_dirs_before,
            "environment_identity_sha256": sha256_file(environment_report),
            "adapter_tree_sha256": (
                adapter_tree_sha256 if system_kind == "TRAINED_LORA" else None
            ),
            "decoding": config.decoding.model_dump(mode="json"),
            "denominator_policy": (
                f"ALL_{bindings.row_count}_FROZEN_{bindings.split.value}_ROWS_"
                "NO_RETRY_NO_SELECTION"
            ),
            "component_count": len({result["component_id"] for result in results}),
            "metrics": _metric_summary(results),
            "family_counts": dict(
                sorted(Counter(result["family"] for result in results).items())
            ),
            "results": results,
            "evaluation_rows_read": True,
            "evaluation_split_materialized_by_unique_splitter": True,
            "canonical_evaluation_read": False,
        }
        return report

    baseline_report = execute_arm(base_model, system_kind="BASE_ICL")
    candidate_model = PeftModel.from_pretrained(
        base_model,
        adapter_path,
        is_trainable=False,
    )
    candidate_model.eval()
    candidate_report = execute_arm(candidate_model, system_kind="TRAINED_LORA")
    pending_reports.extend(
        (
            (baseline_report_output_path, baseline_report),
            (candidate_report_output_path, candidate_report),
        )
    )
    reports.extend((baseline_report, candidate_report))

    snapshot_after, ignored_dirs_after = snapshot_tree_identity(
        snapshot,
        expected_file_count=config.runtime.snapshot_regular_file_count,
    )
    if snapshot_after != snapshot_before or ignored_dirs_after != ignored_dirs_before:
        raise ValueError("snapshot identity changed during paired evaluation")
    adapter_tree_after, _ = regular_tree_identity(adapter_path)
    if adapter_tree_after != adapter_tree_sha256:
        raise ValueError("adapter identity changed during paired evaluation")
    for output_path, report in pending_reports:
        report["snapshot_tree_sha256_after"] = snapshot_after
        report["ignored_top_level_dirs_after"] = ignored_dirs_after
        write_create_only_json(output_path, report)
    return reports


def freeze_dev_selected_policy(
    *,
    config_path: Path,
    report_paths: Sequence[Path],
    output_path: Path,
) -> dict[str, object]:
    config = load_icl_config(config_path)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(output_path)
    if len(report_paths) != len(config.policies):
        raise ValueError("DEV selection requires exactly one report per frozen policy")
    reports = []
    report_sha256 = {}
    policy_by_id = {policy.policy_id: policy for policy in config.policies}
    for path in report_paths:
        _require_regular_file(path, role="ICL DEV report")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("ICL DEV report must be a JSON object")
        policy_id = payload.get("policy_id")
        if not isinstance(policy_id, str) or policy_id not in policy_by_id:
            raise TypeError("ICL DEV report lacks a frozen policy ID")
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != config.data.dev_rows:
            raise ValueError("ICL DEV report result denominator mismatch")
        case_ids = [result.get("case_id") for result in results]
        if len(set(case_ids)) != len(case_ids) or any(
            not isinstance(case_id, str) for case_id in case_ids
        ):
            raise ValueError("ICL DEV report case IDs must be unique strings")
        expected_metrics = _metric_summary(results)
        expected_family_counts = dict(
            sorted(Counter(result.get("family") for result in results).items())
        )
        for result in results:
            if any(
                not isinstance(result.get(field), bool)
                for field in (
                    "expectation_match",
                    "strict_valid",
                    "primitive_checks_pass",
                    "reassociation_boundary_pass",
                    "structural_plan_match",
                )
            ):
                raise TypeError("ICL DEV result metrics must be booleans")
        if (
            payload.get("schema_version") != "QwenBrainS5IclDevReportV3"
            or payload.get("status") != "PASS"
            or payload.get("experiment_identity") != config.experiment_identity
            or payload.get("system_kind") != "BASE_ICL"
            or payload.get("adapter_tree_sha256") is not None
            or payload.get("split") != "DEV"
            or payload.get("shot_count") != policy_by_id[policy_id].shot_count
            or payload.get("config_sha256") != sha256_file(config_path)
            or payload.get("snapshot_tree_sha256_before")
            != config.runtime.snapshot_tree_sha256
            or payload.get("snapshot_tree_sha256_after")
            != config.runtime.snapshot_tree_sha256
            or payload.get("ignored_top_level_dirs_before")
            != payload.get("ignored_top_level_dirs_after")
            or payload.get("environment_identity_sha256")
            != config.runtime.environment_identity_sha256
            or payload.get("denominator_policy")
            != "ALL_78_FROZEN_DEV_ROWS_NO_RETRY_NO_SELECTION"
            or payload.get("metrics") != expected_metrics
            or payload.get("family_counts") != expected_family_counts
            or payload.get("evaluation_rows_read") is not False
            or payload.get("evaluation_rows_materialized") is not False
            or payload.get("canonical_evaluation_read") is not False
        ):
            raise ValueError("ICL DEV report identity mismatch")
        reports.append(payload)
        report_sha256[policy_id] = sha256_file(path)
    expected_ids = {policy.policy_id for policy in config.policies}
    if {report["policy_id"] for report in reports} != expected_ids:
        raise ValueError("DEV reports do not exactly cover the frozen policy set")
    denominators = [
        [result["case_id"] for result in report["results"]] for report in reports
    ]
    if any(case_ids != denominators[0] for case_ids in denominators[1:]):
        raise ValueError("DEV reports must use the same frozen row order")

    def rank(report: Mapping[str, object]) -> tuple[float, float, float, float, int, str]:
        metrics = report["metrics"]
        assert isinstance(metrics, Mapping)
        return (
            -float(metrics["expectation_match_rate"]),
            -float(metrics["strict_valid_rate"]),
            -float(metrics["primitive_check_pass_rate"]),
            -float(metrics["reassociation_boundary_pass_rate"]),
            int(report["shot_count"]),
            str(report["policy_id"]),
        )

    selected = min(reports, key=rank)
    frozen: dict[str, object] = {
        "schema_version": "QwenBrainS5IclDevSelectedPolicyV3",
        "status": "FROZEN",
        "experiment_identity": config.experiment_identity,
        "config_sha256": sha256_file(config_path),
        "selection_split": "DEV",
        "selection_rule": config.dev_selection.model_dump(mode="json"),
        "selected_policy_id": selected["policy_id"],
        "selected_shot_count": selected["shot_count"],
        "selected_metrics": selected["metrics"],
        "report_sha256": dict(sorted(report_sha256.items())),
        "policy_comparison": [
            {
                "policy_id": report["policy_id"],
                "shot_count": report["shot_count"],
                "metrics": report["metrics"],
            }
            for report in sorted(reports, key=lambda item: str(item["policy_id"]))
        ],
        "evaluation_rows_read": False,
        "evaluation_rows_materialized": False,
        "canonical_evaluation_read": False,
        "test_or_blind_used_for_selection": False,
    }
    write_create_only_json(output_path, frozen)
    return frozen


def attest_existing_dev_selection(
    *,
    config_path: Path,
    report_paths: Sequence[Path],
    selected_policy_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Create a strengthened attestation without mutating historical DEV evidence."""

    config = load_icl_config(config_path)
    preregistration = config.paired_evaluation_preregistration
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(output_path)
    _require_regular_file(selected_policy_path, role="historical selected-policy artifact")
    if sha256_file(selected_policy_path) != preregistration.selected_policy_artifact_sha256:
        raise ValueError("historical selected-policy artifact digest mismatch")
    selected = json.loads(selected_policy_path.read_text(encoding="utf-8"))
    if not isinstance(selected, dict):
        raise TypeError("historical selected-policy artifact must be a JSON object")

    policy_by_id = {policy.policy_id: policy for policy in config.policies}
    if len(report_paths) != len(policy_by_id):
        raise ValueError("attestation requires all three historical DEV reports")
    reports: dict[str, dict[str, object]] = {}
    report_sha256: dict[str, str] = {}
    frozen_order: list[str] | None = None
    for path in report_paths:
        _require_regular_file(path, role="historical ICL DEV report")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("historical ICL DEV report must be a JSON object")
        policy_id = payload.get("policy_id")
        if not isinstance(policy_id, str) or policy_id not in policy_by_id:
            raise ValueError("historical ICL DEV report policy mismatch")
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != config.data.dev_rows:
            raise ValueError("historical ICL DEV report denominator mismatch")
        case_ids = [result.get("case_id") for result in results]
        if (
            any(not isinstance(case_id, str) for case_id in case_ids)
            or len(set(case_ids)) != len(case_ids)
            or (frozen_order is not None and case_ids != frozen_order)
        ):
            raise ValueError("historical ICL DEV row order or identity mismatch")
        frozen_order = case_ids
        if len({result.get("component_id") for result in results}) != config.data.dev_components:
            raise ValueError("historical ICL DEV component count mismatch")
        for result in results:
            if any(
                not isinstance(result.get(field), bool)
                for field in (
                    "expectation_match",
                    "strict_valid",
                    "primitive_checks_pass",
                    "reassociation_boundary_pass",
                    "structural_plan_match",
                )
            ):
                raise TypeError("historical ICL DEV result metrics must be booleans")
        expected_metrics = _metric_summary(results)
        expected_family_counts = dict(
            sorted(Counter(result.get("family") for result in results).items())
        )
        digest = sha256_file(path)
        if (
            payload.get("schema_version") != "QwenBrainS5IclDevReportV2"
            or payload.get("status") != "PASS"
            or payload.get("experiment_identity") != "s5-icl-v2"
            or payload.get("system_kind") != "BASE_ICL"
            or payload.get("split") != "DEV"
            or payload.get("shot_count") != policy_by_id[policy_id].shot_count
            or payload.get("config_sha256") != preregistration.historical_dev_execution_config_sha256
            or payload.get("snapshot_tree_sha256_before")
            != config.runtime.snapshot_tree_sha256
            or payload.get("snapshot_tree_sha256_after")
            != config.runtime.snapshot_tree_sha256
            or payload.get("ignored_top_level_dirs_before")
            != payload.get("ignored_top_level_dirs_after")
            or payload.get("environment_identity_sha256")
            != config.runtime.environment_identity_sha256
            or payload.get("adapter_tree_sha256") is not None
            or payload.get("denominator_policy")
            != "ALL_78_FROZEN_DEV_ROWS_NO_RETRY_NO_SELECTION"
            or payload.get("metrics") != expected_metrics
            or payload.get("family_counts") != expected_family_counts
            or payload.get("evaluation_rows_read") is not False
            or payload.get("evaluation_rows_materialized") is not False
            or payload.get("canonical_evaluation_read") is not False
        ):
            raise ValueError("historical ICL DEV report identity mismatch")
        if policy_id in reports:
            raise ValueError("historical ICL DEV policies must be unique")
        reports[policy_id] = payload
        report_sha256[policy_id] = digest
    if set(reports) != set(policy_by_id):
        raise ValueError("historical ICL DEV reports do not cover the frozen policies")

    def rank(payload: Mapping[str, object]) -> tuple[float, float, float, float, int, str]:
        metrics = payload["metrics"]
        assert isinstance(metrics, Mapping)
        return (
            -float(metrics["expectation_match_rate"]),
            -float(metrics["strict_valid_rate"]),
            -float(metrics["primitive_check_pass_rate"]),
            -float(metrics["reassociation_boundary_pass_rate"]),
            int(payload["shot_count"]),
            str(payload["policy_id"]),
        )

    recomputed = min(reports.values(), key=rank)
    if (
        selected.get("schema_version") != "QwenBrainS5IclDevSelectedPolicyV2"
        or selected.get("status") != "FROZEN"
        or selected.get("experiment_identity") != "s5-icl-v2"
        or selected.get("config_sha256") != preregistration.historical_dev_execution_config_sha256
        or selected.get("selection_split") != "DEV"
        or selected.get("selected_policy_id") != recomputed.get("policy_id")
        or selected.get("selected_policy_id") != preregistration.selected_policy_id
        or selected.get("selected_shot_count") != preregistration.selected_shot_count
        or selected.get("selected_metrics") != recomputed.get("metrics")
        or selected.get("report_sha256") != dict(sorted(report_sha256.items()))
        or selected.get("evaluation_rows_read") is not False
        or selected.get("evaluation_rows_materialized") is not False
        or selected.get("canonical_evaluation_read") is not False
        or selected.get("test_or_blind_used_for_selection") is not False
    ):
        raise ValueError("historical selected-policy content mismatch")
    if report_sha256[preregistration.selected_policy_id] != (
        preregistration.selected_base_dev_report_sha256
    ):
        raise ValueError("selected historical DEV report digest mismatch")

    attestation: dict[str, object] = {
        "schema_version": "QwenBrainS5IclDevSelectionAttestationV3",
        "status": "PASS",
        "experiment_identity": config.experiment_identity,
        "amended_config_sha256": sha256_file(config_path),
        "closed_v2_protocol_config_sha256": preregistration.closed_v2_protocol_config_sha256,
        "historical_dev_execution_config_sha256": preregistration.historical_dev_execution_config_sha256,
        "validator_source_sha256": sha256_file(Path(__file__)),
        "historical_selected_policy_sha256": sha256_file(selected_policy_path),
        "historical_report_sha256": dict(sorted(report_sha256.items())),
        "recomputed_selected_policy_id": recomputed["policy_id"],
        "recomputed_selected_shot_count": recomputed["shot_count"],
        "recomputed_selected_metrics": recomputed["metrics"],
        "split": "DEV",
        "case_count": config.data.dev_rows,
        "component_count": config.data.dev_components,
        "selection_split_role": "TUNING_SPLIT_POLICY_SELECTION",
        "selection_artifact_mutated": False,
        "test_or_blind_used_for_selection": False,
        "canonical_evaluation_read": False,
    }
    write_create_only_json(output_path, attestation)
    return attestation


def exact_mcnemar(
    baseline_outcomes: Mapping[str, bool],
    candidate_outcomes: Mapping[str, bool],
) -> dict[str, object]:
    transitions = paired_transition_matrix(baseline_outcomes, candidate_outcomes)
    regressions = transitions["pass_to_fail"]
    corrections = transitions["fail_to_pass"]
    discordant = regressions + corrections
    if discordant == 0:
        p_value = 1.0
    else:
        lower = min(regressions, corrections)
        tail_numerator = sum(math.comb(discordant, index) for index in range(lower + 1))
        p_value = min(1.0, 2.0 * tail_numerator / (2**discordant))
    return {
        "method": "TWO_SIDED_EXACT_BINOMIAL_ON_DISCORDANT_PAIRS",
        "n11": transitions["pass_to_pass"],
        "n10": regressions,
        "n01": corrections,
        "n00": transitions["fail_to_fail"],
        "discordant_count": discordant,
        "net_improvement_count": corrections - regressions,
        "p_value": p_value,
    }


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def paired_cluster_bootstrap(
    baseline_values: Mapping[str, float | bool],
    candidate_values: Mapping[str, float | bool],
    component_by_case: Mapping[str, str],
    *,
    replicates: int = 10000,
    seed: int = 20260830,
) -> dict[str, object]:
    case_ids = set(baseline_values)
    if case_ids != set(candidate_values) or case_ids != set(component_by_case):
        raise ValueError("paired bootstrap inputs must use the same full denominator")
    if not case_ids:
        raise ValueError("paired bootstrap denominator cannot be empty")
    if replicates != 10000:
        raise ValueError("ICL V3 freezes exactly 10,000 bootstrap replicates")
    components: dict[str, list[str]] = {}
    for case_id in sorted(case_ids):
        components.setdefault(component_by_case[case_id], []).append(case_id)
    component_ids = sorted(components)
    observed = sum(
        float(candidate_values[case_id]) - float(baseline_values[case_id])
        for case_id in case_ids
    ) / len(case_ids)
    rng = random.Random(seed)
    deltas = []
    for _ in range(replicates):
        sampled_cases: list[str] = []
        for _ in component_ids:
            sampled_component = component_ids[rng.randrange(len(component_ids))]
            sampled_cases.extend(components[sampled_component])
        delta = sum(
            float(candidate_values[case_id]) - float(baseline_values[case_id])
            for case_id in sampled_cases
        ) / len(sampled_cases)
        deltas.append(delta)
    deltas.sort()
    cluster_count = len(component_ids)
    stability_flags = (
        ["UNSTABLE_LOW_CLUSTER_COUNT"] if cluster_count < 8 else []
    )
    return {
        "method": "PAIRED_CLUSTER_BOOTSTRAP_PERCENTILE_95_PERCENT",
        "cluster_unit": "FROZEN_GRAPH_COMPONENT",
        "case_count": len(case_ids),
        "cluster_count": cluster_count,
        "replicates": replicates,
        "seed": seed,
        "candidate_minus_baseline": observed,
        "ci_lower": _percentile(deltas, 0.025),
        "ci_upper": _percentile(deltas, 0.975),
        "stability_flags": stability_flags,
        "stable_statistical_interval": not stability_flags,
        "interval_presentation": (
            "UNSTABLE_LOW_CLUSTER_COUNT_DO_NOT_PRESENT_AS_ORDINARY_STABLE_STATISTICAL_INTERVAL"
            if stability_flags
            else "ORDINARY_STABLE_STATISTICAL_INTERVAL"
        ),
    }


def build_paired_evaluation_report(
    *,
    config_path: Path,
    baseline_report_path: Path,
    candidate_report_path: Path,
    output_path: Path,
) -> dict[str, object]:
    config = load_icl_config(config_path)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(output_path)
    reports = []
    for path, role in (
        (baseline_report_path, "baseline"),
        (candidate_report_path, "candidate"),
    ):
        _require_regular_file(path, role=f"paired {role} report")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise TypeError(f"paired {role} report lacks result records")
        reports.append(payload)
    baseline, candidate = reports
    split = baseline.get("split")
    preregistration = config.paired_evaluation_preregistration
    if split not in preregistration.expected_component_counts or candidate.get("split") != split:
        raise ValueError("paired reports must use the same preregistered split")
    expected_rows = {
        "DEV": preregistration.paired_dev_rows,
        "SYNTHETIC_TEST": preregistration.synthetic_test_rows,
        "MANUAL_BLIND": preregistration.manual_blind_rows,
    }[str(split)]
    expected_baseline_schema = (
        "QwenBrainS5IclDevReportV2"
        if split == "DEV"
        else "QwenBrainS5IclEvaluationReportV3"
    )
    expected_baseline_identity = "s5-icl-v2" if split == "DEV" else config.experiment_identity
    expected_baseline_config_sha256 = (
        preregistration.historical_dev_execution_config_sha256
        if split == "DEV"
        else sha256_file(config_path)
    )
    expected_candidate_schema = (
        "QwenBrainS5IclDevReportV3"
        if split == "DEV"
        else "QwenBrainS5IclEvaluationReportV3"
    )
    if (
        baseline.get("schema_version") != expected_baseline_schema
        or candidate.get("schema_version") != expected_candidate_schema
        or baseline.get("experiment_identity") != expected_baseline_identity
        or candidate.get("experiment_identity") != config.experiment_identity
        or baseline.get("status") != "PASS"
        or candidate.get("status") != "PASS"
        or baseline.get("system_kind") != "BASE_ICL"
        or candidate.get("system_kind") != "TRAINED_LORA"
        or baseline.get("policy_id") != preregistration.selected_policy_id
        or candidate.get("policy_id") != preregistration.selected_policy_id
        or baseline.get("shot_count") != preregistration.selected_shot_count
        or candidate.get("shot_count") != preregistration.selected_shot_count
        or candidate.get("adapter_tree_sha256")
        != preregistration.trained_adapter_tree_sha256
        or baseline.get("adapter_tree_sha256") is not None
        or candidate.get("config_sha256") != sha256_file(config_path)
        or baseline.get("config_sha256") != expected_baseline_config_sha256
        or (
            split == "DEV"
            and baseline.get("request_manifest_sha256")
            != preregistration.selected_dev_request_manifest_sha256
        )
        or (
            split == "DEV"
            and candidate.get("request_manifest_sha256")
            != preregistration.selected_dev_request_manifest_sha256
        )
        or (
            split != "DEV"
            and baseline.get("request_manifest_sha256")
            != candidate.get("request_manifest_sha256")
        )
        or (
            split != "DEV"
            and baseline.get("request_bundle_sha256")
            != candidate.get("request_bundle_sha256")
        )
        or (
            split != "DEV"
            and baseline.get("read_once_attestation_sha256")
            != candidate.get("read_once_attestation_sha256")
        )
        or (
            split != "DEV"
            and baseline.get("evaluation_rows_sha256")
            != candidate.get("evaluation_rows_sha256")
        )
        or (
            split != "DEV"
            and baseline.get("train_image_manifest_sha256")
            != candidate.get("train_image_manifest_sha256")
        )
        or (
            split != "DEV"
            and baseline.get("evaluation_image_manifest_sha256")
            != candidate.get("evaluation_image_manifest_sha256")
        )
        or (
            split != "DEV"
            and (
                baseline.get("image_resolution_policy")
                != "SHA256_MANIFEST_ONLY_PATH_STRINGS_NOT_IO_AUTHORITY"
                or candidate.get("image_resolution_policy")
                != "SHA256_MANIFEST_ONLY_PATH_STRINGS_NOT_IO_AUTHORITY"
            )
        )
        or (
            split != "DEV"
            and (
                baseline.get("evaluation_rows_read") is not True
                or candidate.get("evaluation_rows_read") is not True
                or baseline.get("evaluation_split_materialized_by_unique_splitter")
                is not True
                or candidate.get("evaluation_split_materialized_by_unique_splitter")
                is not True
            )
        )
        or baseline.get("snapshot_tree_sha256_before")
        != config.runtime.snapshot_tree_sha256
        or baseline.get("snapshot_tree_sha256_after")
        != config.runtime.snapshot_tree_sha256
        or candidate.get("snapshot_tree_sha256_before")
        != config.runtime.snapshot_tree_sha256
        or candidate.get("snapshot_tree_sha256_after")
        != config.runtime.snapshot_tree_sha256
        or baseline.get("canonical_evaluation_read") is not False
        or candidate.get("canonical_evaluation_read") is not False
    ):
        raise ValueError("paired report system or protocol identity mismatch")
    baseline_results = baseline["results"]
    candidate_results = candidate["results"]
    if len(baseline_results) != expected_rows or len(candidate_results) != expected_rows:
        raise ValueError("paired report row count mismatch")
    baseline_order = [record.get("case_id") for record in baseline_results]
    candidate_order = [record.get("case_id") for record in candidate_results]
    if (
        any(not isinstance(case_id, str) for case_id in baseline_order)
        or len(set(baseline_order)) != len(baseline_order)
        or candidate_order != baseline_order
    ):
        raise ValueError("paired reports must use the same unique frozen row order")
    baseline_records = {record["case_id"]: record for record in baseline_results}
    candidate_records = {record["case_id"]: record for record in candidate_results}
    component_by_case = {
        case_id: str(record["component_id"])
        for case_id, record in baseline_records.items()
    }
    if any(
        candidate_records[case_id].get("component_id") != component_by_case[case_id]
        for case_id in component_by_case
    ):
        raise ValueError("paired reports disagree on frozen component identity")
    component_count = len(set(component_by_case.values()))
    expected_component_count = preregistration.expected_component_counts[str(split)]
    if component_count != expected_component_count:
        raise ValueError("paired report component count mismatch")
    fields = (
        "expectation_match",
        "strict_valid",
        "primitive_checks_pass",
        "reassociation_boundary_pass",
    )
    for record in (*baseline_records.values(), *candidate_records.values()):
        if any(not isinstance(record.get(field), bool) for field in fields):
            raise TypeError("paired report binary metrics must be booleans")
    metrics = {}
    for field in fields:
        baseline_values = {
            case_id: bool(record[field]) for case_id, record in baseline_records.items()
        }
        candidate_values = {
            case_id: bool(candidate_records[case_id][field])
            for case_id in baseline_records
        }
        metrics[field] = paired_cluster_bootstrap(
            baseline_values,
            candidate_values,
            component_by_case,
            replicates=config.paired_evaluation_preregistration.cluster_bootstrap_replicates,
            seed=config.paired_evaluation_preregistration.bootstrap_seed,
        )
        if field == "expectation_match":
            metrics[field]["exact_mcnemar"] = exact_mcnemar(
                baseline_values,
                candidate_values,
            )
    primary = metrics["expectation_match"]
    practical_threshold = preregistration.practical_difference_minimum
    stability_flags = list(primary["stability_flags"])
    report: dict[str, object] = {
        "schema_version": "QwenBrainS5PairedEvaluationReportV3",
        "status": "PASS",
        "experiment_identity": config.experiment_identity,
        "config_sha256": sha256_file(config_path),
        "baseline_report_sha256": sha256_file(baseline_report_path),
        "candidate_report_sha256": sha256_file(candidate_report_path),
        "split": split,
        "case_count": len(baseline_records),
        "component_count": component_count,
        "expected_component_count": expected_component_count,
        "stability_flags": stability_flags,
        "stable_statistical_interval": not stability_flags,
        "metrics": metrics,
        "practical_difference_minimum": practical_threshold,
        "primary_point_gate_pass": primary["candidate_minus_baseline"]
        >= practical_threshold,
        "primary_ci_not_negative": primary["ci_lower"] >= 0.0,
        "evidence_role": (
            "TUNING_SPLIT_SUPPORTING_ANALYSIS_ONLY_BOTH_ARMS_HAVE_SEEN_DEV"
            if split == "DEV"
            else "PRIMARY_PAIRED_EVALUATION"
        ),
        "primary_test_or_blind_definition_changed": False,
        "benefit_claim_authorized": False,
        "claim_classification": "SUPPORTING_EVIDENCE_ONLY"
        if split == "DEV"
        else "PENDING_CROSS_SPLIT_FINAL_CLASSIFICATION",
        "benefit_claim_note": (
            "DEV is a tuning split already seen by both arms and is supporting "
            "evidence only; it cannot establish training benefit."
            if split == "DEV"
            else "Final A2 classification requires both primary split reports, "
            "manual-blind non-regression, complete evidence, and no contract or "
            "safety regression."
        ),
        "canonical_evaluation_read": False,
    }
    write_create_only_json(output_path, report)
    return report


def classify_final_benefit_claim(
    *,
    config_path: Path,
    synthetic_test_paired_report_path: Path,
    manual_blind_paired_report_path: Path,
    complete_evidence: bool,
    no_contract_or_safety_regression: bool,
    output_path: Path,
) -> dict[str, object]:
    """Apply the coordinator-frozen A2 claim levels across primary paired splits."""

    config = load_icl_config(config_path)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(output_path)
    loaded: dict[str, tuple[dict[str, object], Path]] = {}
    for path in (synthetic_test_paired_report_path, manual_blind_paired_report_path):
        _require_regular_file(path, role="paired claim input")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("paired claim input must be a JSON object")
        split = payload.get("split")
        if split not in {"SYNTHETIC_TEST", "MANUAL_BLIND"} or split in loaded:
            raise ValueError("claim inputs must cover test and blind exactly once")
        expected_components = config.paired_evaluation_preregistration.expected_component_counts[
            str(split)
        ]
        metrics = payload.get("metrics")
        primary = metrics.get("expectation_match") if isinstance(metrics, dict) else None
        if (
            payload.get("schema_version") != "QwenBrainS5PairedEvaluationReportV3"
            or payload.get("status") != "PASS"
            or payload.get("experiment_identity") != config.experiment_identity
            or payload.get("config_sha256") != sha256_file(config_path)
            or payload.get("component_count") != expected_components
            or payload.get("expected_component_count") != expected_components
            or not isinstance(primary, dict)
            or payload.get("canonical_evaluation_read") is not False
        ):
            raise ValueError("paired claim input identity mismatch")
        loaded[str(split)] = (payload, path)
    if set(loaded) != {"SYNTHETIC_TEST", "MANUAL_BLIND"}:
        raise ValueError("claim inputs do not cover both primary paired splits")

    test = loaded["SYNTHETIC_TEST"][0]
    blind = loaded["MANUAL_BLIND"][0]
    test_primary = test["metrics"]["expectation_match"]
    blind_primary = blind["metrics"]["expectation_match"]
    threshold = config.paired_evaluation_preregistration.practical_difference_minimum
    point_gate = float(test_primary["candidate_minus_baseline"]) >= threshold
    ci_gate = float(test_primary["ci_lower"]) >= 0.0
    blind_nonregression = float(blind_primary["candidate_minus_baseline"]) >= 0.0
    flags = sorted(
        {
            flag
            for payload in (test, blind)
            for flag in payload.get("stability_flags", [])
        }
    )
    unstable = config.paired_evaluation_preregistration.low_cluster_count_flag in flags
    full_gate = (
        point_gate
        and ci_gate
        and blind_nonregression
        and complete_evidence
        and no_contract_or_safety_regression
        and not unstable
    )
    directional_gate = point_gate and blind_nonregression and unstable
    if full_gate:
        claim_level = "FULL_TRAINING_BENEFIT"
        claim_text = "训练有收益"
        benefit_claim_authorized = True
    elif directional_gate:
        claim_level = "POINT_ESTIMATE_BENEFIT_UNSTABLE_CLUSTER_COUNT"
        claim_text = config.paired_evaluation_preregistration.directional_claim_text
        benefit_claim_authorized = False
    else:
        claim_level = "NO_BENEFIT_EVIDENCE"
        claim_text = "无收益证据"
        benefit_claim_authorized = False
    report: dict[str, object] = {
        "schema_version": "QwenBrainS5FinalBenefitClaimV3",
        "status": "PASS",
        "experiment_identity": config.experiment_identity,
        "config_sha256": sha256_file(config_path),
        "synthetic_test_paired_report_sha256": sha256_file(
            loaded["SYNTHETIC_TEST"][1]
        ),
        "manual_blind_paired_report_sha256": sha256_file(
            loaded["MANUAL_BLIND"][1]
        ),
        "point_delta_gate_pass": point_gate,
        "ci_lower_not_negative_gate_pass": ci_gate,
        "manual_blind_nonregression_gate_pass": blind_nonregression,
        "complete_evidence": complete_evidence,
        "no_contract_or_safety_regression": no_contract_or_safety_regression,
        "stability_flags": flags,
        "unstable_interval_present": unstable,
        "claim_level": claim_level,
        "claim_text": claim_text,
        "benefit_claim_authorized": benefit_claim_authorized,
        "canonical_evaluation_read": False,
    }
    write_create_only_json(output_path, report)
    return report
