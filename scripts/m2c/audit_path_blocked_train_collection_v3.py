#!/usr/bin/env python3
"""Fail-closed audit of the observed ADR-0021 V3 TRAIN collection attempts.

This program is an offline byte/contract verifier.  It never packages rows,
trains a model, runs a policy, or executes a Q-B evaluation.  A complete raw
chain is still excluded when its final physical task predicate is false.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    M2CPathBlockedProbeChainV3,
    load_v3_training_manifest,
    recompute_candidate_payload_v3,
)


SCHEMA_VERSION = "M2CS4V3TrainCollectionAuditV1"
MANIFEST_PATH = "configs/m2c_s4_v3_training_keys.json"
MANIFEST_FILE_SHA256 = "b5a2da566f4086724e99cea1664aeeac3b91344a68b72be84bcf6c5d0ddad65c"
MANIFEST_CONTENT_SHA256 = "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
ADR_PATH = "docs/decisions/ADR-0021-m2c-public-semantic-candidate-contract.md"
ADR_SHA256 = "60161eb2b40cdf7e32cd5714ef420b7bfb74d28a4a6b5789eecdd9cc73cba7cf"
CATEGORY_AUDIT_PATH = "reports/m2c-s3-public-category-vocabulary-audit.json"
CATEGORY_AUDIT_SHA256 = "7946d610b677981ac56b223067cd63fdd10ccde140ae6dccc13ffb4688b90bfa"
PUBLIC_TRACKS_PATH = "src/xh_agent/policy/qrm_lite/public_tracks_v3.py"
PUBLIC_TRACKS_SHA256 = "20d53a15ff94aab63a1e09042b2e546ffc36ceebf94bb3059d34ca651cc05752"
PREREG_PATH = "docs/decisions/M2C-S4-V3-TRAIN-COLLECTION-BATCH-02-PREREG.md"
PREREG_SHA256 = "896cd5436e99427ab960cc93f68775e0fc746d8515cbc53fed0f32dbb14bb6d8"
PREREG_COMMIT = "e02115d912a263a52d2aeeaf5a5e8c15f9506e4b"
SOURCE_COMMIT = "60b9578f3a20aab434d3bcb8d03e63c21ea09f01"
PRE_TZDATA_FIX_COMMIT = "6a556943164d70c7fe7e6d0c23d6b0fe88e7adca"
DERIVED_PROBE_SHA256 = "0ea4de677f43bd6f32a1b3ddec9b88c8851723d176f5136e1df8601215c8dd50"
UPSTREAM_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
RUNTIME_REGISTRY_SHA256 = "3572f80f1597b7f3bdffb1f8aad90d5baeb086b25c371b88511bc58444813359"
S6_MANIFEST_SHA256 = "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"

RAW_FINAL_CONTACT = "RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED"
RAW_FINAL_PREGRASP_IK = "RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED"
INFRASTRUCTURE_EXIT_139 = "INFRASTRUCTURE_STAGE_EXIT_139"
PRE_KIT_TZDATA_GUARD = "PRE_KIT_TZDATA_GUARD_FAILURE"
EXIT_139_SUFFIX = "terminating this process with exit code 139."
TZDATA_SUFFIX = (
    "xh_agent.policy.qrm_lite.m2c_hard_freeze.M2CHardFreezeError: "
    "M2C_HARD_FREEZE_CLOCK_INVALID:Asia/Shanghai timezone data unavailable"
)
DECISION_SOURCE = "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
EXPECTED_SKILLS = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)
EXPECTED_PROTOCOLS = (
    ("world", "m_rad", 3),
    ("world", "m", 3),
    ("world", "m_rad", 3),
    ("world", "m_rad", 3),
    ("world", "m", 3),
    ("policy_rgbd_optical", "none", 0),
    ("world", "none", 0),
    ("world", "m_rad", 3),
)
EXPECTED_ATTEMPT_DIRS = (
    "batch01-retry1",
    "batch01-tzdata-failure",
    "batch02",
    "batch02-prereg-01",
    "batch02-prereg-02",
    "batch02-prereg-03",
    "batch03",
    "batch04",
    "batch05",
)
INITIAL_SCENES = (16012, 16022, 16025, 16026, 16063)
PREREG_SCENES = (16047, 16066, 16081)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_MOUNT = re.compile(
    r"^/var/tmp/m2c-isaac-project-20260813-([0-9a-f]{7}):/workspace/project:ro$"
)

IMPLEMENTATION_PATHS = (
    "scripts/isaac_m1b_dataset_benchmark.py",
    "src/xh_agent/policy/qrm_lite/m2c_hard_freeze.py",
    PUBLIC_TRACKS_PATH,
    "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py",
    "scripts/m2c/build_s4_v3_training_manifest.py",
    "scripts/m2c/materialize_s4_s6_scenes.py",
    "scripts/m2c/derive_model_owned_chain_probe.py",
    "scripts/m2c/run_path_blocked_collection_worker.py",
    "scripts/m2c/package_path_blocked_collection.py",
)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a non-symlink regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _git(project: Path, *arguments: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *arguments], cwd=project, check=True, capture_output=True, text=not binary
    )
    return result.stdout


def _git_file(project: Path, commit: str, path: str) -> bytes:
    return _git(project, "show", f"{commit}:{path}", binary=True)  # type: ignore[return-value]


def _regular_file_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"evidence root must be a non-symlink directory: {root}")
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"evidence contains a symlink: {path}")
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = sha256_file(path)
        elif not path.is_dir():
            raise ValueError(f"evidence contains a non-regular entry: {path}")
    return hashes


def _require_file_hash(project: Path, relative: str, expected: str) -> dict[str, str]:
    path = project / relative
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"frozen source SHA-256 mismatch: {relative}")
    return {"path": relative, "file_sha256": actual}


def _validate_sources(project: Path) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    manifest_path = project / MANIFEST_PATH
    manifest = load_v3_training_manifest(manifest_path)
    if sha256_file(manifest_path) != MANIFEST_FILE_SHA256:
        raise ValueError("V3 TRAIN manifest file SHA-256 mismatch")
    if manifest.manifest_sha256 != MANIFEST_CONTENT_SHA256:
        raise ValueError("V3 TRAIN manifest content SHA-256 mismatch")
    records = {item.matched_key: item.model_dump(mode="json") for item in manifest.training_keys}
    if len(records) != 36:
        raise ValueError("V3 TRAIN manifest must contain 36 unique keys")

    bindings: dict[str, Any] = {
        "training_manifest": {
            "path": MANIFEST_PATH,
            "file_sha256": MANIFEST_FILE_SHA256,
            "content_sha256": MANIFEST_CONTENT_SHA256,
        },
        "adr_0021": _require_file_hash(project, ADR_PATH, ADR_SHA256),
        "category_vocabulary_audit": _require_file_hash(
            project, CATEGORY_AUDIT_PATH, CATEGORY_AUDIT_SHA256
        ),
        "public_track_candidate_implementation": _require_file_hash(
            project, PUBLIC_TRACKS_PATH, PUBLIC_TRACKS_SHA256
        ),
    }
    category = _load_object(project / CATEGORY_AUDIT_PATH, label="category vocabulary audit")
    expected_category = {
        "schema_version": "M2CS3PublicCategoryVocabularyAuditV1",
        "status": "PASS_CATEGORY_CARRIES_DECLARED_ATTRIBUTE_VOCABULARY",
        "collection_or_training_executed": False,
        "task_spec_target_track_id_read": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    for field, expected in expected_category.items():
        if category.get(field) != expected:
            raise ValueError(f"category vocabulary audit has invalid {field}")
    if manifest.source_bindings.get(ADR_PATH) != ADR_SHA256:
        raise ValueError("V3 manifest does not bind ADR-0021")
    if manifest.source_bindings.get(CATEGORY_AUDIT_PATH) != CATEGORY_AUDIT_SHA256:
        raise ValueError("V3 manifest does not bind the category audit")
    candidate = manifest.candidate_implementation
    if candidate != {"path": PUBLIC_TRACKS_PATH, "sha256": PUBLIC_TRACKS_SHA256}:
        raise ValueError("V3 manifest candidate implementation binding changed")
    return bindings, records


def _prereg_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if match is None:
        raise ValueError("batch-02 preregistration lacks its JSON payload")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("batch-02 preregistration JSON must be an object")
    return value


def _validate_prereg(
    project: Path, records: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = project / PREREG_PATH
    if sha256_file(path) != PREREG_SHA256:
        raise ValueError("batch-02 preregistration SHA-256 mismatch")
    resolved = str(_git(project, "rev-parse", f"{PREREG_COMMIT}^{{commit}}")).strip()
    if resolved != PREREG_COMMIT:
        raise ValueError("batch-02 preregistration commit does not resolve exactly")
    if hashlib.sha256(_git_file(project, PREREG_COMMIT, PREREG_PATH)).hexdigest() != PREREG_SHA256:
        raise ValueError("batch-02 preregistration differs from introduced commit bytes")
    payload = _prereg_payload(path)
    expected = {
        "schema_version": "M2CS4V3TrainCollectionBatch02PreregV1",
        "registered_before_any_batch02_outcome": True,
        "batch02_outcome_observed_before_registration": False,
        "source_commit": SOURCE_COMMIT,
        "selection_rule": "manifest_order_first_unattempted_per_new_sdf_v1",
        "selection_uses_outcomes": False,
        "stop_after_selected_keys": 3,
        "attempt_each_selected_key_at_most_once": True,
        "retry_or_replacement_authorized": False,
    }
    for field, wanted in expected.items():
        if payload.get(field) != wanted:
            raise ValueError(f"batch-02 preregistration has invalid {field}")
    if payload.get("attempted_scene_seed_exclusions") != list(INITIAL_SCENES):
        raise ValueError("batch-02 preregistration exclusions changed")
    scope = payload.get("scope")
    if scope != {
        "role": "TRAIN",
        "split": "train",
        "scripted_public_physical_supervision_collection": True,
        "teacher_used": False,
        "model_rollout": False,
        "training_execution": False,
        "q_b_evaluation": False,
        "privileged_truth_policy_input": False,
    }:
        raise ValueError("batch-02 preregistration scope changed")
    ordered_records = [records[key] for key in records]
    selected: list[dict[str, Any]] = []
    seen_sdfs: set[str] = set()
    fields = ("scene_seed", "failure_seed", "matched_key", "sdf_sha256", "supervision_sha256")
    for record in ordered_records:
        if int(record["scene_seed"]) in INITIAL_SCENES or str(record["sdf_sha256"]) in seen_sdfs:
            continue
        selected.append({field: record[field] for field in fields})
        seen_sdfs.add(str(record["sdf_sha256"]))
        if len(selected) == 3:
            break
    if payload.get("selected_keys") != selected:
        raise ValueError("batch-02 preregistration selection does not recompute")
    if tuple(int(item["scene_seed"]) for item in selected) != PREREG_SCENES:
        raise ValueError("batch-02 preregistration selected unexpected scenes")
    return (
        {
            "path": PREREG_PATH,
            "file_sha256": PREREG_SHA256,
            "introduced_commit": PREREG_COMMIT,
            "source_commit": SOURCE_COMMIT,
            "selection_recomputed_without_outcomes": True,
            "stop_after_three_observed": True,
            "selected_scene_seeds": list(PREREG_SCENES),
            "selected_matched_keys": [str(item["matched_key"]) for item in selected],
        },
        selected,
    )


def _implementation_binding(project: Path, commit: str) -> dict[str, Any]:
    resolved = str(_git(project, "rev-parse", f"{commit}^{{commit}}")).strip()
    if resolved != commit:
        raise ValueError(f"implementation commit does not resolve exactly: {commit}")
    return {
        "commit": commit,
        "git_tree": str(_git(project, "show", "-s", "--format=%T", commit)).strip(),
        "source_sha256": {
            path: hashlib.sha256(_git_file(project, commit, path)).hexdigest()
            for path in IMPLEMENTATION_PATHS
        },
    }


def _find_single_attempt_root(batch: Path) -> Path:
    jobs = list(batch.glob("train/*/collection-job-v3.json"))
    if len(jobs) != 1:
        raise ValueError(f"batch must contain exactly one V3 collection job: {batch}")
    return jobs[0].parent


def _option(command: Sequence[object], option: str) -> str:
    values = [
        str(command[index + 1]) for index, token in enumerate(command[:-1]) if token == option
    ]
    if len(values) != 1:
        raise ValueError(f"collection command must contain exactly one {option}")
    return values[0]


def _validate_job(
    job: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    attempt_id: str,
    project: Path,
) -> str:
    exact = {
        "schema_version": "M2CPathBlockedCollectionJobV3",
        "status": "PREPARED_NOT_EXECUTED",
        "collection_contract_revision": "V3",
        "collection_role": "TRAIN",
        "split": "train",
        "candidate_contract_revision": "PublicTrackCandidateV3",
        "checkpoint_architecture_revision": "M2C_Q012_V3",
        "decision_source": DECISION_SOURCE,
        "model_owned": False,
        "model_rollout": False,
        "training_executed": False,
        "evaluation_executed": False,
        "formal_q_b_evaluation": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_key_manifest_sha256": MANIFEST_FILE_SHA256,
        "s6_key_manifest_sha256": S6_MANIFEST_SHA256,
        "runtime_registry_sha256": RUNTIME_REGISTRY_SHA256,
        "derived_probe_sha256": DERIVED_PROBE_SHA256,
        "upstream_v4_probe_sha256": UPSTREAM_V4_PROBE_SHA256,
        "urdf_sha256": URDF_SHA256,
    }
    for field, wanted in exact.items():
        if job.get(field) != wanted:
            raise ValueError(f"{attempt_id} collection job has invalid {field}")
    for field in ("matched_key", "scene_seed", "failure_seed", "sdf_sha256", "supervision_sha256"):
        if job.get(field) != record.get(field):
            raise ValueError(f"{attempt_id} collection job differs from frozen {field}")
    commits: list[str] = []
    for prefix in ("stage", "probe"):
        command = job.get(f"{prefix}_command")
        shell = job.get(f"{prefix}_command_shell")
        if not isinstance(command, list) or shell != shlex.join([str(item) for item in command]):
            raise ValueError(f"{attempt_id} {prefix} command/shell binding mismatch")
        mounts = [
            match.group(1) for token in command if (match := _PROJECT_MOUNT.fullmatch(str(token)))
        ]
        if len(mounts) != 1:
            raise ValueError(f"{attempt_id} {prefix} lacks one read-only project commit mount")
        commits.append(mounts[0])
        if "nvcr.io/nvidia/isaac-sim:6.0.1" not in command:
            raise ValueError(f"{attempt_id} {prefix} image changed")
    if commits[0] != commits[1]:
        raise ValueError(f"{attempt_id} stage/probe implementation commits differ")
    expected_commit = (
        PRE_TZDATA_FIX_COMMIT if attempt_id == "batch01-tzdata-failure" else SOURCE_COMMIT
    )
    if commits[0] != expected_commit[:7]:
        raise ValueError(
            f"{attempt_id} project mount does not bind the expected implementation commit"
        )
    probe_command = job["probe_command"]
    expected_options = {
        "--m2c-chain-role": "TRAIN",
        "--m2c-split": "train",
        "--m2c-matched-key": str(record["matched_key"]),
        "--m2c-failure-seed": str(record["failure_seed"]),
        "--m2c-decision-source": DECISION_SOURCE,
        "--m2c-declared-target-attribute": "yellow",
    }
    for option, wanted in expected_options.items():
        if _option(probe_command, option) != wanted:
            raise ValueError(f"{attempt_id} probe command has invalid {option}")
    if not _git_file(project, expected_commit, PUBLIC_TRACKS_PATH):
        raise ValueError("implementation commit lacks PublicTrackCandidateV3")
    return expected_commit


def _validate_stage_metrics(path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _load_object(path, label="stage metrics")
    if metrics.get("status") != "PASS":
        raise ValueError("stage metrics status is not PASS")
    scene = record["scene_seed"]
    expected = {
        f"scene-{scene}.sdf": record["sdf_sha256"],
        f"scene-{scene}.supervision.json": record["supervision_sha256"],
        "panda_controlled.urdf": URDF_SHA256,
    }
    if metrics.get("source_hashes") != expected:
        raise ValueError("stage metrics source hashes differ from frozen TRAIN identity")
    smoke = metrics.get("qrm_closed_loop_smoke")
    if (
        not isinstance(smoke, Mapping)
        or smoke.get("enabled") is not False
        or smoke.get("decision_count") != 0
    ):
        raise ValueError("stage metrics unexpectedly contain a model rollout")
    protocol = metrics.get("student_dataset_protocol")
    if not isinstance(protocol, Mapping) or protocol.get("teacher_required") is not False:
        raise ValueError("stage metrics do not prove Teacher-free collection")
    return metrics


def _asset_path(probe_root: Path, uri: str) -> Path:
    if not uri.startswith("dataset://"):
        raise ValueError("public asset URI is not dataset://")
    relative = uri.removeprefix("dataset://")
    if relative.startswith("/") or ".." in relative.split("/"):
        raise ValueError("public asset URI escapes the probe evidence root")
    path = probe_root / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or not path.resolve().is_relative_to(probe_root.resolve())
    ):
        raise ValueError("public asset is not a contained regular file")
    return path


def validate_raw_chain(
    raw_path: Path, *, record: Mapping[str, Any], stage_path: Path
) -> dict[str, Any]:
    raw = _load_object(raw_path, label="raw V3 actuation probe")
    if raw.get("schema_version") != "IsaacM1BActuationProbeV1" or raw.get("status") != "PASS":
        raise ValueError("raw V3 probe must be an IsaacM1BActuationProbeV1 PASS envelope")
    if raw.get("not_policy_rollout") is not True:
        raise ValueError("raw V3 probe must state not_policy_rollout=true")
    if raw.get("actuation_probe_source_sha256") != DERIVED_PROBE_SHA256:
        raise ValueError("raw V3 probe source SHA-256 mismatch")
    expected_sources = {
        "m1b_physics_scene.usdc": sha256_file(stage_path),
        "panda_controlled.urdf": URDF_SHA256,
        f"scene-{record['scene_seed']}.sdf": record["sdf_sha256"],
        f"scene-{record['scene_seed']}.supervision.json": record["supervision_sha256"],
    }
    if raw.get("source_hashes") != expected_sources:
        raise ValueError("raw V3 probe source hashes differ from frozen/actual bytes")
    chain_value = raw.get("m2c_path_blocked_physical_chain")
    try:
        chain = M2CPathBlockedProbeChainV3.model_validate(chain_value)
    except ValidationError as error:
        raise ValueError("raw V3 physical chain schema is invalid") from error
    identity = ("matched_key", "scene_seed", "failure_seed", "sdf_sha256", "supervision_sha256")
    if any(getattr(chain, field) != record[field] for field in identity):
        raise ValueError("raw V3 physical chain identity differs from frozen TRAIN key")
    if (
        chain.final_task_success
        or chain.model_rollout
        or chain.teacher_used
        or chain.privileged_truth_policy_input
    ):
        raise ValueError("raw V3 chain violates final-false/non-model/Teacher/truth boundary")
    if len(chain.steps) != 8:
        raise ValueError("raw V3 physical chain must contain exactly eight steps")
    rgbd = raw.get("m2b_public_rgbd")
    captures = rgbd.get("captures") if isinstance(rgbd, Mapping) else None
    if not isinstance(captures, list):
        raise ValueError("raw V3 probe lacks the public RGB-D capture journal")
    task_spec = rgbd.get("task_spec") if isinstance(rgbd, Mapping) else None
    if not isinstance(task_spec, Mapping) or task_spec.get("simulator_entity_id_used") is not False:
        raise ValueError("raw V3 TaskSpec public binding is invalid")
    probe_root = raw_path.parent
    seen_observations: set[str] = set()
    seen_captures: set[str] = set()
    seen_receipts: set[str] = set()
    freshness = chain.failure_observed_at_ns
    destination: str | None = None
    candidate_sizes: list[int] = []
    for index, step in enumerate(chain.steps):
        if (
            step.decision_index != index
            or step.schema_version != "PathBlockedPhysicalStepEvidenceV3"
        ):
            raise ValueError(f"raw V3 step {index} index/schema mismatch")
        observation = step.observation
        expected_payload, expected_hash = recompute_candidate_payload_v3(observation)
        if observation.candidate_payload.model_dump(mode="json") != expected_payload:
            raise ValueError(f"raw V3 step {index} candidates are not host-recomputable")
        if observation.candidate_payload_sha256 != expected_hash:
            raise ValueError(f"raw V3 step {index} candidate hash mismatch")
        if (
            observation.observation_id in seen_observations
            or observation.capture_receipt_sha256 in seen_captures
        ):
            raise ValueError(f"raw V3 step {index} reuses observation/capture evidence")
        seen_observations.add(observation.observation_id)
        seen_captures.add(observation.capture_receipt_sha256)
        if observation.captured_at_ns <= freshness:
            raise ValueError(f"raw V3 step {index} observation is not fresh")
        candidate_sizes.append(len(observation.candidate_payload.candidates))
        candidate_by_id = {item.track_id: item for item in observation.candidate_payload.candidates}
        target = (
            step.public_blocker_track_id
            if index <= 4
            else step.public_task_target_track_id
            if index >= 6
            else None
        )
        if index <= 4:
            candidate = candidate_by_id.get(str(target))
            if candidate is None or candidate.role != "ROLE_MANIPULABLE_OTHER":
                raise ValueError(f"raw V3 step {index} blocker pointer is outside semantic K8")
            if step.public_task_target_track_id is not None:
                raise ValueError(f"raw V3 step {index} leaks task-target pointer")
        elif index >= 6:
            candidate = candidate_by_id.get(str(target))
            if candidate is None or candidate.role != "ROLE_TARGET_ATTRIBUTE_MATCH":
                raise ValueError(f"raw V3 step {index} task-target pointer is outside semantic K8")
            if step.public_blocker_track_id is not None:
                raise ValueError(f"raw V3 step {index} retains blocker pointer")
        elif (
            step.public_blocker_track_id is not None or step.public_task_target_track_id is not None
        ):
            raise ValueError("raw V3 REOBSERVE step has a pointer")
        if index in {2, 3}:
            if step.destination_cell_label != "BIN_CELL_3":
                raise ValueError("raw V3 MOVE/PLACE destination differs from frozen cell")
            destination = destination or step.destination_cell_label
            if step.destination_cell_label != destination:
                raise ValueError("raw V3 MOVE/PLACE destinations disagree")
        elif step.destination_cell_label is not None:
            raise ValueError(f"raw V3 step {index} has an inapplicable destination")
        rgb = _asset_path(probe_root, observation.rgb_uri)
        depth = _asset_path(probe_root, observation.depth_uri)
        if (
            sha256_file(rgb) != observation.rgb_sha256
            or sha256_file(depth) != observation.depth_sha256
        ):
            raise ValueError(f"raw V3 step {index} public RGB/depth asset hash mismatch")
        matched_captures = [
            item
            for item in captures
            if isinstance(item, Mapping)
            and item.get("timestamp_ns") == observation.captured_at_ns
            and item.get("rgb_uri") == observation.rgb_uri
            and item.get("depth_uri") == observation.depth_uri
            and item.get("rgb_sha256") == observation.rgb_sha256
            and item.get("depth_sha256") == observation.depth_sha256
        ]
        if (
            len(matched_captures) != 1
            or canonical_sha256(matched_captures[0]) != observation.capture_receipt_sha256
        ):
            raise ValueError(f"raw V3 step {index} capture journal/hash binding mismatch")
        if len(step.physical_receipts) != 1:
            raise ValueError(f"raw V3 step {index} must contain one physical receipt")
        receipt = step.physical_receipts[0]
        raw_steps = chain_value.get("steps") if isinstance(chain_value, Mapping) else None
        raw_step = raw_steps[index] if isinstance(raw_steps, list) else None
        raw_receipts = raw_step.get("physical_receipts") if isinstance(raw_step, Mapping) else None
        raw_receipt = (
            raw_receipts[0] if isinstance(raw_receipts, list) and len(raw_receipts) == 1 else None
        )
        if not isinstance(raw_receipt, Mapping):
            raise ValueError(f"raw V3 step {index} lacks its original receipt bytes")
        receipt_payload = dict(raw_receipt)
        receipt_sha = receipt_payload.pop("receipt_sha256", None)
        if receipt_sha != canonical_sha256(receipt_payload) or receipt_sha in seen_receipts:
            raise ValueError(f"raw V3 step {index} physical receipt hash/reuse failure")
        seen_receipts.add(receipt_sha)
        if receipt.executed_skill != EXPECTED_SKILLS[index] or not receipt.physically_executed:
            raise ValueError(f"raw V3 step {index} executed skill mismatch")
        frame, units, dimensions = EXPECTED_PROTOCOLS[index]
        if receipt.action_protocol.model_dump(mode="json") != {
            "schema_version": "PhysicalActionProtocolV2",
            "coordinate_frame": frame,
            "units": units,
            "dimensions": dimensions,
            "frequency_hz": 60.0,
            "normalization": "none",
        }:
            raise ValueError(f"raw V3 step {index} action protocol mismatch")
        gates = {
            "schema": receipt.schema_gate,
            "stale_track": receipt.stale_track_gate,
            "frame_unit": receipt.frame_unit_gate,
            "ik": receipt.ik_gate,
            "collision": receipt.collision_gate,
            "safety": receipt.safety_gate,
        }
        if (
            any(value != "PASS" for value in gates.values())
            or receipt.collision_or_safety_violation
        ):
            raise ValueError(f"raw V3 step {index} safety/non-controller gate did not pass")
        if index < 7 and receipt.controller_gate != "PASS":
            raise ValueError(f"raw V3 step {index} controller gate did not pass")
        if index == 7 and receipt.controller_gate != "REJECTED":
            raise ValueError("raw V3 final regrasp controller gate was not rejected")
        if (
            receipt.started_at_ns <= observation.captured_at_ns
            or receipt.completed_at_ns <= receipt.started_at_ns
        ):
            raise ValueError(f"raw V3 step {index} execution timestamps are invalid")
        freshness = receipt.completed_at_ns
    final = chain.steps[-1].physical_receipts[0]
    status = final.execution_measurements.get("status")
    if status not in {"CONTACT_GATE_REJECTED", "PREGRASP_IK_GATE_REJECTED"}:
        raise ValueError("raw V3 final regrasp has an unsupported rejection status")
    if final.execution_measurements.get("object_lift_m") != 0.0:
        raise ValueError("raw V3 final rejected regrasp unexpectedly lifted the target")
    classification = (
        RAW_FINAL_CONTACT if status == "CONTACT_GATE_REJECTED" else RAW_FINAL_PREGRASP_IK
    )
    return {
        "classification": classification,
        "raw_probe_status": "PASS",
        "chain_schema": "M2CPathBlockedProbeChainV3",
        "physical_chain_steps": 8,
        "step_0_through_6_all_gates_pass": True,
        "step_7_controller_gate": "REJECTED",
        "step_7_status": status,
        "final_task_success": False,
        "v3_candidates_host_recomputed": True,
        "all_required_pointers_inside_semantic_k8": True,
        "candidate_sizes": candidate_sizes,
        "public_assets_and_capture_journal_hash_verified": True,
        "physical_receipt_hashes_verified": True,
    }


def audit_attempt(
    batch: Path,
    *,
    records: Mapping[str, Mapping[str, Any]],
    project: Path,
) -> dict[str, Any]:
    attempt_id = batch.name
    root = _find_single_attempt_root(batch)
    tree = _regular_file_hashes(root)
    job_path = root / "collection-job-v3.json"
    job = _load_object(job_path, label="V3 collection job")
    key = job.get("matched_key")
    record = records.get(str(key))
    if record is None:
        raise ValueError(f"{attempt_id} is not a frozen V3 TRAIN key")
    commit = _validate_job(job, record, attempt_id=attempt_id, project=project)
    derived = root / "derived-path-blocked-probe.py"
    if sha256_file(derived) != DERIVED_PROBE_SHA256:
        raise ValueError(f"{attempt_id} derived executable SHA-256 mismatch")
    raw_path = root / "probe/actuation-probe.json"
    stage_console = root / "stage/console.log"
    probe_console = root / "probe/console.log"
    metrics_path = root / "stage/metrics.json"
    if raw_path.exists():
        _validate_stage_metrics(metrics_path, record)
        details = validate_raw_chain(
            raw_path, record=record, stage_path=root / "stage/m1b_physics_scene.usdc"
        )
    elif attempt_id == "batch03":
        if metrics_path.exists() or not stage_console.is_file():
            raise ValueError("exit-139 attempt has unexpected metrics/missing console")
        console = stage_console.read_text(encoding="utf-8")
        if (
            not console.rstrip().endswith(EXIT_139_SUFFIX)
            or "[Fatal] [carb.crashreporter-breakpad.plugin]" not in console
        ):
            raise ValueError("exit-139 attempt lacks its exact fatal terminal receipt")
        details = {
            "classification": INFRASTRUCTURE_EXIT_139,
            "stage_exit_code": 139,
            "raw_probe_present": False,
            "final_task_success": None,
        }
    elif attempt_id == "batch01-tzdata-failure":
        _validate_stage_metrics(metrics_path, record)
        console = probe_console.read_text(encoding="utf-8")
        if not console.rstrip().endswith(TZDATA_SUFFIX):
            raise ValueError("pre-Kit tzdata attempt lacks its exact terminal exception")
        details = {
            "classification": PRE_KIT_TZDATA_GUARD,
            "terminal_exception": TZDATA_SUFFIX,
            "raw_probe_present": False,
            "final_task_success": None,
        }
    else:
        raise ValueError(f"{attempt_id} has no raw V3 chain or recognized terminal failure")
    forbidden = {
        "collection-receipt-v3.json",
        "packaged-physical-chain-v3.json",
        "supervised-steps-v3.json",
    }
    if forbidden & {Path(relative).name for relative in tree}:
        raise ValueError(f"{attempt_id} contains a packaged/training artifact")
    return {
        "attempt_id": attempt_id,
        "evidence_relative_root": root.relative_to(batch.parent).as_posix(),
        "implementation_commit": commit,
        "classification": details.pop("classification"),
        "identity": {
            field: record[field]
            for field in (
                "matched_key",
                "scene_seed",
                "failure_seed",
                "sdf_sha256",
                "supervision_sha256",
            )
        },
        "classification_evidence": details,
        "evidence_file_sha256": tree,
        "evidence_tree": {
            "regular_file_count": len(tree),
            "canonical_path_sha256_map_digest": canonical_sha256(tree),
        },
        "scripted_collection_only": True,
        "training_sample_packaged": False,
        "training_sample_eligible": False,
        "model_owned": False,
        "model_rollout": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_q_b_evaluation": False,
        "counted_as_pure_model_success": False,
    }


def build_report(evidence_root: Path, *, project: Path) -> dict[str, Any]:
    evidence_root = evidence_root.resolve()
    observed_dirs = tuple(sorted(path.name for path in evidence_root.iterdir()))
    if observed_dirs != tuple(sorted(EXPECTED_ATTEMPT_DIRS)):
        raise ValueError("V3 audit requires exactly the nine frozen attempt directories")
    all_files = _regular_file_hashes(evidence_root)
    if len(all_files) != 415:
        raise ValueError("complete V3 evidence root must contain exactly 415 regular files")
    sources, records = _validate_sources(project)
    prereg, selected = _validate_prereg(project, records)
    implementations = {
        commit: _implementation_binding(project, commit)
        for commit in (PRE_TZDATA_FIX_COMMIT, SOURCE_COMMIT)
    }
    attempts = [
        audit_attempt(evidence_root / name, records=records, project=project)
        for name in EXPECTED_ATTEMPT_DIRS
    ]
    keys = [str(item["identity"]["matched_key"]) for item in attempts]
    scenes = [int(item["identity"]["scene_seed"]) for item in attempts]
    if len(set(keys)) != 8 or Counter(scenes) != Counter(
        {16012: 2, 16022: 1, 16025: 1, 16026: 1, 16063: 1, 16047: 1, 16066: 1, 16081: 1}
    ):
        raise ValueError("V3 attempts do not match the eight unique frozen TRAIN identities")
    selected_keys = {str(item["matched_key"]) for item in selected}
    observed_prereg = {
        str(item["identity"]["matched_key"])
        for item in attempts
        if item["attempt_id"].startswith("batch02-prereg-")
    }
    if observed_prereg != selected_keys or len(observed_prereg) != 3:
        raise ValueError("batch-02 observed attempts violate preregistered selection/stop rule")
    classifications = Counter(str(item["classification"]) for item in attempts)
    expected_classes = Counter(
        {
            RAW_FINAL_CONTACT: 5,
            RAW_FINAL_PREGRASP_IK: 2,
            INFRASTRUCTURE_EXIT_139: 1,
            PRE_KIT_TZDATA_GUARD: 1,
        }
    )
    if classifications != expected_classes:
        raise ValueError("V3 attempt failure-class counts differ from observed evidence")
    sdfs = sorted({str(records[key]["sdf_sha256"]) for key in set(keys)})
    manifest_sdfs = sorted({str(item["sdf_sha256"]) for item in records.values()})
    if sdfs != manifest_sdfs or len(sdfs) != 3:
        raise ValueError("observed V3 TRAIN keys do not cover all three frozen SDF identities")
    attempt_file_count = sum(int(item["evidence_tree"]["regular_file_count"]) for item in attempts)
    if attempt_file_count != len(all_files):
        raise ValueError("attempt inventories do not cover every evidence-root regular file")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES",
        "evidence_use": "SCRIPTED_V3_TRAIN_COLLECTION_AUDIT_ONLY_NOT_MODEL_OR_Q_B_EVALUATION",
        "finding": (
            "nine execution-attempt directories cover eight unique frozen V3 TRAIN keys and all "
            "three frozen SDF identities; seven raw eight-step scripted chains passed steps 0-6 "
            "but ended with a rejected step-7 regrasp and final_task_success=false, one stage "
            "terminated with exit 139, and the first scene-16012 probe stopped at the pre-Kit "
            "tzdata hard-freeze guard; therefore zero episodes are training-eligible"
        ),
        "source_bindings": sources,
        "batch02_preregistration_binding": prereg,
        "implementation_bindings": implementations,
        "evidence_root": str(evidence_root),
        "evidence_root_inventory": {
            "regular_file_count": len(all_files),
            "canonical_path_sha256_map_digest": canonical_sha256(all_files),
            "all_regular_files_byte_hashed": True,
        },
        "scope": {
            "frozen_v3_train_keys": 36,
            "execution_attempt_directories": 9,
            "unique_train_keys_attempted": 8,
            "unobserved_train_keys": 28,
            "inference_about_unobserved_train_keys": None,
            "unique_sdf_sha256_covered": 3,
            "sdf_sha256_covered": sdfs,
            "smoke_keys_used": 0,
            "v4_q_a_keys_used": 0,
            "s6_evaluation_keys_used": 0,
        },
        "observed_counts": {
            "raw_v3_eight_step_chains": 7,
            "raw_final_false_contact_gate_rejected": classifications[RAW_FINAL_CONTACT],
            "raw_final_false_pregrasp_ik_gate_rejected": classifications[RAW_FINAL_PREGRASP_IK],
            "infrastructure_stage_exit_139": classifications[INFRASTRUCTURE_EXIT_139],
            "pre_kit_tzdata_guard_failure": classifications[PRE_KIT_TZDATA_GUARD],
            "training_samples_packaged": 0,
            "training_samples_eligible": 0,
        },
        "execution_boundaries": {
            "scripted_public_physical_supervision_collection": True,
            "training_executed": False,
            "model_rollout_executed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "formal_q_b_evaluation_executed": False,
            "scripted_collection_counted_as_pure_model_success": False,
            "pure_model_success_episodes": None,
        },
        "attempts": attempts,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    counts = report["observed_counts"]
    rows = []
    for attempt in report["attempts"]:
        identity = attempt["identity"]
        rows.append(
            f"| `{attempt['attempt_id']}` | {identity['scene_seed']} | "
            f"`{str(identity['matched_key'])[:30]}…` | `{attempt['classification']}` | no |"
        )
    return "\n".join(
        [
            "# M2C S4 V3 TRAIN collection audit",
            "",
            f"Status: **{report['status']}**.",
            "",
            str(report["finding"]),
            "",
            "This is a byte-bound audit of scripted TRAIN collection only. It is not training, a "
            "model rollout, Q-B evaluation, or evidence of pure model success.",
            "",
            "## Counts",
            "",
            f"- Execution-attempt directories: {report['scope']['execution_attempt_directories']}",
            f"- Unique frozen TRAIN keys attempted: {report['scope']['unique_train_keys_attempted']}",
            f"- Raw V3 eight-step chains: {counts['raw_v3_eight_step_chains']}",
            f"- Eligible/packaged training samples: {counts['training_samples_eligible']} / {counts['training_samples_packaged']}",
            f"- Frozen SDF identities covered: {report['scope']['unique_sdf_sha256_covered']}",
            f"- Regular evidence files byte-hashed: {report['evidence_root_inventory']['regular_file_count']}",
            "",
            "## Attempts",
            "",
            "| Attempt | Scene | Frozen key | Observed terminal class | Eligible |",
            "| --- | ---: | --- | --- | --- |",
            *rows,
            "",
            "## Boundaries",
            "",
            "Training executed: false. Model rollout executed: false. Teacher used: false. "
            "Privileged truth used as policy input: false. Formal Q-B evaluation executed: false. "
            "`pure_model_success_episodes` is null because no model rollout was evaluated.",
            "",
            "Batch-02 selection was independently recomputed from the frozen manifest and the "
            "committed pre-registration; exactly the three selected keys were attempted once and "
            "the stop-after-three rule was observed.",
            "",
        ]
    )


def verify_expected_report(actual: Mapping[str, Any], expected_path: Path) -> None:
    expected = _load_object(expected_path, label="expected V3 collection audit")
    if actual != expected:
        raise ValueError("recomputed V3 collection audit differs from the frozen expected report")


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expected-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()
    report = build_report(args.evidence_root, project=args.project.resolve())
    if args.expected_json is not None:
        verify_expected_report(report, args.expected_json)
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    markdown = render_markdown(report)
    if args.output_json is not None:
        _write_new(args.output_json, encoded)
    if args.output_md is not None:
        _write_new(args.output_md, markdown)
    if args.output_json is None and args.output_md is None:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
