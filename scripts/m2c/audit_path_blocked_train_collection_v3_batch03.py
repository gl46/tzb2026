#!/usr/bin/env python3
"""Strict offline audit for the pre-registered M2C S4 V3 TRAIN batch 03.

This verifier hashes every regular evidence file and reconstructs the public
K8 observations, capture journal, physical receipts, gates, and terminal
predicate decision.  It does not package training rows, train or run a model,
or execute a Q-B evaluation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from pydantic import ValidationError

from m2c import audit_path_blocked_train_collection_v3 as cumulative
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    M2CPathBlockedProbeChainV3,
    recompute_candidate_payload_v3,
)


SCHEMA_VERSION = "M2CS4V3TrainCollectionBatch03AuditV1"
PREREG_PATH = "docs/decisions/M2C-S4-V3-TRAIN-COLLECTION-BATCH-03-PREREG.md"
PREREG_SHA256 = "b5bb5f72a85d693f7fff7e8fa48007d905b209bccdcef7f92a7aed6c456a0deb"
PREREG_INTRODUCED_COMMIT = "1e768c023302b2ba9c85bf0badf07cadb8b1e7ee"
PREREG_SOURCE_COMMIT = "373c9ddc18e64c856964f362d87b5a68f5d2ba0b"
AUTHORIZED_RUNTIME_COMMIT = "60b9578f3a20aab434d3bcb8d03e63c21ea09f01"
CUMULATIVE_AUDIT_PATH = "reports/m2c-s4-v3-path-blocked-train-collection.json"
CUMULATIVE_AUDIT_SHA256 = "c505ec6517d7a766768f72cd14fc49d1919cff234dc2d8fbee1877104b41480d"
CUMULATIVE_AUDITOR_PATH = "scripts/m2c/audit_path_blocked_train_collection_v3.py"
CUMULATIVE_AUDITOR_SHA256 = "f2ef6a2bd438d9618ba59afc733c3e6e8ad1e8a548fbf240748ca0e57eac9eae"

EXPECTED_ATTEMPT_DIRS = ("batch03-01", "batch03-02", "batch03-03")
EXPECTED_ATTEMPT_FILE_COUNTS = {"batch03-01": 56, "batch03-02": 54, "batch03-03": 54}
EXPECTED_SCENES = (16073, 16085, 16102)
PRIOR_SCENES = (16012, 16022, 16025, 16026, 16047, 16063, 16066, 16081)
RUNTIME_UNCHANGED_PATHS = (
    "src/xh_agent/policy/qrm_lite/public_tracks_v3.py",
    "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py",
    "scripts/m2c/derive_model_owned_chain_probe.py",
    "scripts/m2c/materialize_s4_s6_scenes.py",
    "scripts/m2c/run_path_blocked_collection_worker.py",
    "scripts/m2c/package_path_blocked_collection.py",
)

RAW_LIFTED_PUBLIC_REJECT = "RAW_V3_REGRASP_LIFTED_PUBLIC_PREDICATE_REJECTED"
RAW_CONTACT_REJECT = "RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED"
RAW_PREGRASP_REJECT = "RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED"
REQUIRED_PUBLIC_SUCCESS_PREDICATES = {"grasped=true", "lifted=true"}


def _git_file_exists(project: Path, commit: str, relative: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{relative}"],
        cwd=project,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _prereg_payload(path: Path) -> dict[str, Any]:
    match = re.search(r"```json\n(.*?)\n```", path.read_text(encoding="utf-8"), re.DOTALL)
    if match is None:
        raise ValueError("batch-03 preregistration lacks its JSON payload")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("batch-03 preregistration JSON must be an object")
    return value


def _validate_preregistration(
    project: Path, records: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = project / PREREG_PATH
    if cumulative.sha256_file(path) != PREREG_SHA256:
        raise ValueError("batch-03 preregistration SHA-256 mismatch")
    resolved = str(
        cumulative._git(project, "rev-parse", f"{PREREG_INTRODUCED_COMMIT}^{{commit}}")
    ).strip()
    if resolved != PREREG_INTRODUCED_COMMIT:
        raise ValueError("batch-03 introduced commit does not resolve exactly")
    introduced_bytes = cumulative._git_file(project, PREREG_INTRODUCED_COMMIT, PREREG_PATH)
    if hashlib.sha256(introduced_bytes).hexdigest() != PREREG_SHA256:
        raise ValueError("batch-03 preregistration differs from introduced commit bytes")
    parent = f"{PREREG_INTRODUCED_COMMIT}^"
    if _git_file_exists(project, parent, PREREG_PATH):
        raise ValueError("batch-03 preregistration was not introduced by the bound commit")

    payload = _prereg_payload(path)
    exact = {
        "schema_version": "M2CS4V3TrainCollectionBatch03PreregV1",
        "registered_after_observed_unique_train_keys": 8,
        "registered_before_any_selected_key_result": True,
        "selected_key_result_observed_before_registration": False,
        "preregistration_source_commit": PREREG_SOURCE_COMMIT,
        "authorized_runtime_commit": AUTHORIZED_RUNTIME_COMMIT,
        "selection_rule": "manifest_order_first_unattempted_per_sdf_v1",
        "selection_inputs": ["manifest_order", "attempted_key_identity", "sdf_sha256"],
        "selection_uses_attempt_outcomes": False,
        "maximum_selected_keys": 3,
        "stop_after_selected_keys": 3,
        "attempt_each_selected_key_at_most_once": True,
        "retry_authorized": False,
        "replacement_authorized": False,
        "collection_executed_by_preregistration": False,
        "runtime_changed_by_preregistration": False,
    }
    for field, wanted in exact.items():
        if payload.get(field) != wanted:
            raise ValueError(f"batch-03 preregistration has invalid {field}")
    if payload.get("attempted_scene_seed_exclusions") != list(PRIOR_SCENES):
        raise ValueError("batch-03 preregistration prior identity exclusions changed")
    if payload.get("scope") != {
        "role": "TRAIN",
        "split": "train",
        "scripted_public_physical_supervision_collection": True,
        "teacher_used": False,
        "model_rollout": False,
        "training_execution": False,
        "q_b_evaluation": False,
        "privileged_truth_policy_input": False,
    }:
        raise ValueError("batch-03 preregistration scope changed")

    manifest_binding = payload.get("manifest")
    if manifest_binding != {
        "path": cumulative.MANIFEST_PATH,
        "file_sha256": cumulative.MANIFEST_FILE_SHA256,
        "embedded_manifest_sha256": cumulative.MANIFEST_CONTENT_SHA256,
    }:
        raise ValueError("batch-03 preregistration manifest binding changed")
    manifest_bytes = cumulative._git_file(project, PREREG_SOURCE_COMMIT, cumulative.MANIFEST_PATH)
    if hashlib.sha256(manifest_bytes).hexdigest() != cumulative.MANIFEST_FILE_SHA256:
        raise ValueError("pre-registration source manifest bytes changed")
    manifest = json.loads(manifest_bytes)
    if manifest.get("manifest_sha256") != cumulative.MANIFEST_CONTENT_SHA256:
        raise ValueError("pre-registration source manifest content hash changed")

    audit_binding = payload.get("attempt_identity_audit")
    if audit_binding != {
        "path": CUMULATIVE_AUDIT_PATH,
        "file_sha256": CUMULATIVE_AUDIT_SHA256,
        "schema_version": cumulative.SCHEMA_VERSION,
        "unique_train_keys_attempted": 8,
    }:
        raise ValueError("batch-03 preregistration prior-audit binding changed")
    prior_bytes = cumulative._git_file(project, PREREG_SOURCE_COMMIT, CUMULATIVE_AUDIT_PATH)
    if hashlib.sha256(prior_bytes).hexdigest() != CUMULATIVE_AUDIT_SHA256:
        raise ValueError("pre-registration source prior-audit bytes changed")
    if cumulative.sha256_file(project / CUMULATIVE_AUDIT_PATH) != CUMULATIVE_AUDIT_SHA256:
        raise ValueError("frozen cumulative V3 audit changed after preregistration")
    prior = json.loads(prior_bytes)
    if prior.get("schema_version") != cumulative.SCHEMA_VERSION:
        raise ValueError("prior cumulative V3 audit schema changed")
    prior_attempts = prior.get("attempts")
    if not isinstance(prior_attempts, list):
        raise ValueError("prior cumulative V3 audit lacks attempts")
    prior_scenes = {int(item["identity"]["scene_seed"]) for item in prior_attempts}
    prior_keys = {str(item["identity"]["matched_key"]) for item in prior_attempts}
    if prior_scenes != set(PRIOR_SCENES) or len(prior_keys) != 8:
        raise ValueError("prior cumulative V3 audit identity set changed")

    selected: list[dict[str, Any]] = []
    selected_sdfs: set[str] = set()
    identity_fields = (
        "scene_seed",
        "failure_seed",
        "matched_key",
        "sdf_sha256",
        "supervision_sha256",
    )
    for record in manifest.get("training_keys", []):
        if int(record["scene_seed"]) in prior_scenes:
            continue
        sdf_sha256 = str(record["sdf_sha256"])
        if sdf_sha256 in selected_sdfs:
            continue
        selected.append({field: record[field] for field in identity_fields})
        selected_sdfs.add(sdf_sha256)
        if len(selected) == 3:
            break
    if payload.get("selected_keys") != selected:
        raise ValueError("batch-03 selected keys do not outcome-blindly recompute")
    if tuple(int(item["scene_seed"]) for item in selected) != EXPECTED_SCENES:
        raise ValueError("batch-03 preregistration selected unexpected scenes")
    if {str(item["matched_key"]) for item in selected} & prior_keys:
        raise ValueError("batch-03 preregistration selected a previously attempted key")
    for selected_record in selected:
        current = records.get(str(selected_record["matched_key"]))
        if current is None or any(
            current[field] != selected_record[field] for field in identity_fields
        ):
            raise ValueError("current frozen manifest identity differs from preregistration")

    for relative in RUNTIME_UNCHANGED_PATHS:
        runtime_bytes = cumulative._git_file(project, AUTHORIZED_RUNTIME_COMMIT, relative)
        if cumulative._git_file(project, PREREG_SOURCE_COMMIT, relative) != runtime_bytes:
            raise ValueError(f"runtime changed before preregistration: {relative}")
        # This is a historical evidence replay. The executed bytes are bound
        # by the preregistered commit and each attempt's source hash; later
        # fail-closed hardening must not retroactively invalidate them.
    return (
        {
            "path": PREREG_PATH,
            "file_sha256": PREREG_SHA256,
            "introduced_commit": PREREG_INTRODUCED_COMMIT,
            "introduced_by_bound_commit": True,
            "preregistration_source_commit": PREREG_SOURCE_COMMIT,
            "authorized_runtime_commit": AUTHORIZED_RUNTIME_COMMIT,
            "prior_cumulative_audit": audit_binding,
            "selection_recomputed_without_outcomes": True,
            "selected_scene_seeds": list(EXPECTED_SCENES),
            "selected_matched_keys": [str(item["matched_key"]) for item in selected],
            "attempt_each_at_most_once": True,
            "retry_or_replacement_authorized": False,
        },
        selected,
    )


def _validate_capture_journal(
    raw: Mapping[str, Any], *, probe_root: Path
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    rgbd = raw.get("m2b_public_rgbd")
    captures = rgbd.get("captures") if isinstance(rgbd, Mapping) else None
    if not isinstance(captures, list) or not captures:
        raise ValueError("raw V3 probe lacks a non-empty public capture journal")
    task_spec = rgbd.get("task_spec") if isinstance(rgbd, Mapping) else None
    if not isinstance(task_spec, Mapping) or task_spec.get("simulator_entity_id_used") is not False:
        raise ValueError("raw V3 public TaskSpec binding is invalid")
    labels: dict[str, Mapping[str, Any]] = {}
    seen_timestamps: set[int] = set()
    seen_uris: set[str] = set()
    previous_timestamp = 0
    for index, capture in enumerate(captures):
        if not isinstance(capture, Mapping):
            raise ValueError(f"public capture journal entry {index} is not an object")
        label = capture.get("label")
        timestamp = capture.get("timestamp_ns")
        rgb_uri = capture.get("rgb_uri")
        depth_uri = capture.get("depth_uri")
        if not isinstance(label, str) or not label or label in labels:
            raise ValueError("public capture labels must be non-empty and unique")
        if not isinstance(timestamp, int) or timestamp <= previous_timestamp:
            raise ValueError("public capture timestamps must be strictly increasing")
        if timestamp in seen_timestamps:
            raise ValueError("public capture timestamp is reused")
        if not isinstance(rgb_uri, str) or not isinstance(depth_uri, str):
            raise ValueError("public capture asset URI is missing")
        if rgb_uri in seen_uris or depth_uri in seen_uris:
            raise ValueError("public capture asset URI is reused")
        rgb_path = cumulative._asset_path(probe_root, rgb_uri)
        depth_path = cumulative._asset_path(probe_root, depth_uri)
        if cumulative.sha256_file(rgb_path) != capture.get("rgb_sha256") or cumulative.sha256_file(
            depth_path
        ) != capture.get("depth_sha256"):
            raise ValueError(f"public capture journal asset hash mismatch: {label}")
        labels[label] = capture
        seen_timestamps.add(timestamp)
        seen_uris.update((rgb_uri, depth_uri))
        previous_timestamp = timestamp
    return captures, labels


def _validate_raw_chain(
    raw_path: Path, *, record: Mapping[str, Any], stage_path: Path
) -> dict[str, Any]:
    raw = cumulative._load_object(raw_path, label="batch-03 raw V3 actuation probe")
    if raw.get("schema_version") != "IsaacM1BActuationProbeV1" or raw.get("status") != "PASS":
        raise ValueError("batch-03 raw probe must be an IsaacM1BActuationProbeV1 PASS")
    if raw.get("not_policy_rollout") is not True:
        raise ValueError("batch-03 raw probe must state not_policy_rollout=true")
    if raw.get("actuation_probe_source_sha256") != cumulative.DERIVED_PROBE_SHA256:
        raise ValueError("batch-03 derived probe source SHA-256 mismatch")
    expected_sources = {
        "m1b_physics_scene.usdc": cumulative.sha256_file(stage_path),
        "panda_controlled.urdf": cumulative.URDF_SHA256,
        f"scene-{record['scene_seed']}.sdf": record["sdf_sha256"],
        f"scene-{record['scene_seed']}.supervision.json": record["supervision_sha256"],
    }
    if raw.get("source_hashes") != expected_sources:
        raise ValueError("batch-03 raw source hashes differ from frozen/actual bytes")
    chain_value = raw.get("m2c_path_blocked_physical_chain")
    try:
        chain = M2CPathBlockedProbeChainV3.model_validate(chain_value)
    except ValidationError as error:
        raise ValueError("batch-03 raw V3 physical chain schema is invalid") from error
    identity_fields = (
        "matched_key",
        "scene_seed",
        "failure_seed",
        "sdf_sha256",
        "supervision_sha256",
    )
    if any(getattr(chain, field) != record[field] for field in identity_fields):
        raise ValueError("batch-03 raw identity differs from frozen TRAIN key")
    if chain.final_task_success:
        raise ValueError("batch-03 evidence unexpectedly claims final task success")
    if chain.model_rollout or chain.teacher_used or chain.privileged_truth_policy_input:
        raise ValueError("batch-03 raw chain violates model/Teacher/truth boundary")
    if len(chain.steps) != 8:
        raise ValueError("batch-03 raw chain must contain exactly eight steps")

    probe_root = raw_path.parent
    captures, capture_by_label = _validate_capture_journal(raw, probe_root=probe_root)
    seen_observations: set[str] = set()
    seen_capture_hashes: set[str] = set()
    seen_receipt_ids: set[str] = set()
    seen_receipt_hashes: set[str] = set()
    seen_receipt_uris: set[str] = set()
    freshness = chain.failure_observed_at_ns
    destination: str | None = None
    candidate_sizes: list[int] = []
    raw_steps = chain_value.get("steps") if isinstance(chain_value, Mapping) else None
    for index, step in enumerate(chain.steps):
        if (
            step.decision_index != index
            or step.schema_version != "PathBlockedPhysicalStepEvidenceV3"
        ):
            raise ValueError(f"batch-03 step {index} index/schema mismatch")
        observation = step.observation
        expected_payload, expected_hash = recompute_candidate_payload_v3(observation)
        if observation.candidate_payload.model_dump(mode="json") != expected_payload:
            raise ValueError(f"batch-03 step {index} candidates are not host-recomputable")
        if observation.candidate_payload_sha256 != expected_hash:
            raise ValueError(f"batch-03 step {index} candidate hash mismatch")
        if observation.candidate_payload.candidate_count_bound != 8:
            raise ValueError(f"batch-03 step {index} is not bound to semantic K8")
        if observation.observation_id in seen_observations:
            raise ValueError(f"batch-03 step {index} reuses an observation")
        if observation.capture_receipt_sha256 in seen_capture_hashes:
            raise ValueError(f"batch-03 step {index} reuses a capture receipt")
        if observation.captured_at_ns <= freshness:
            raise ValueError(f"batch-03 step {index} public observation is not fresh")
        seen_observations.add(observation.observation_id)
        seen_capture_hashes.add(observation.capture_receipt_sha256)
        candidate_sizes.append(len(observation.candidate_payload.candidates))
        candidates = {item.track_id: item for item in observation.candidate_payload.candidates}
        pointer = (
            step.public_blocker_track_id
            if index <= 4
            else step.public_task_target_track_id
            if index >= 6
            else None
        )
        if index <= 4:
            candidate = candidates.get(str(pointer))
            if candidate is None or candidate.role != "ROLE_MANIPULABLE_OTHER":
                raise ValueError(f"batch-03 step {index} blocker pointer is outside semantic K8")
            if step.public_task_target_track_id is not None:
                raise ValueError(f"batch-03 step {index} leaks the task-target pointer")
        elif index >= 6:
            candidate = candidates.get(str(pointer))
            if candidate is None or candidate.role != "ROLE_TARGET_ATTRIBUTE_MATCH":
                raise ValueError(f"batch-03 step {index} target pointer is outside semantic K8")
            if step.public_blocker_track_id is not None:
                raise ValueError(f"batch-03 step {index} retains the blocker pointer")
        elif (
            step.public_blocker_track_id is not None or step.public_task_target_track_id is not None
        ):
            raise ValueError("batch-03 REOBSERVE step has a pointer")
        if index in {2, 3}:
            if step.destination_cell_label != "BIN_CELL_3":
                raise ValueError("batch-03 MOVE/PLACE destination differs from frozen cell")
            destination = destination or step.destination_cell_label
            if step.destination_cell_label != destination:
                raise ValueError("batch-03 MOVE/PLACE destinations disagree")
        elif step.destination_cell_label is not None:
            raise ValueError(f"batch-03 step {index} has an inapplicable destination")

        rgb = cumulative._asset_path(probe_root, observation.rgb_uri)
        depth = cumulative._asset_path(probe_root, observation.depth_uri)
        if (
            cumulative.sha256_file(rgb) != observation.rgb_sha256
            or cumulative.sha256_file(depth) != observation.depth_sha256
        ):
            raise ValueError(f"batch-03 step {index} public asset hash mismatch")
        matching_captures = [
            capture
            for capture in captures
            if capture.get("timestamp_ns") == observation.captured_at_ns
            and capture.get("rgb_uri") == observation.rgb_uri
            and capture.get("depth_uri") == observation.depth_uri
            and capture.get("rgb_sha256") == observation.rgb_sha256
            and capture.get("depth_sha256") == observation.depth_sha256
        ]
        if (
            len(matching_captures) != 1
            or cumulative.canonical_sha256(matching_captures[0])
            != observation.capture_receipt_sha256
        ):
            raise ValueError(f"batch-03 step {index} capture journal/hash binding mismatch")
        if len(step.physical_receipts) != 1:
            raise ValueError(f"batch-03 step {index} must contain one physical receipt")
        raw_step = raw_steps[index] if isinstance(raw_steps, list) else None
        raw_receipts = raw_step.get("physical_receipts") if isinstance(raw_step, Mapping) else None
        raw_receipt = (
            raw_receipts[0] if isinstance(raw_receipts, list) and len(raw_receipts) == 1 else None
        )
        if not isinstance(raw_receipt, Mapping):
            raise ValueError(f"batch-03 step {index} lacks original receipt bytes")
        receipt_payload = dict(raw_receipt)
        receipt_sha = receipt_payload.pop("receipt_sha256", None)
        if receipt_sha != cumulative.canonical_sha256(receipt_payload):
            raise ValueError(f"batch-03 step {index} physical receipt hash mismatch")
        receipt = step.physical_receipts[0]
        expected_receipt_id = f"{chain.matched_key}-physical-{index}"
        expected_receipt_uri = (
            f"dataset://m2c_path_blocked/physical/{chain.matched_key}/{index}.json"
        )
        if receipt.receipt_id != expected_receipt_id or receipt.receipt_uri != expected_receipt_uri:
            raise ValueError(f"batch-03 step {index} receipt identity/URI mismatch")
        if (
            receipt.receipt_id in seen_receipt_ids
            or receipt_sha in seen_receipt_hashes
            or receipt.receipt_uri in seen_receipt_uris
        ):
            raise ValueError(f"batch-03 step {index} reuses physical receipt evidence")
        seen_receipt_ids.add(receipt.receipt_id)
        seen_receipt_hashes.add(str(receipt_sha))
        seen_receipt_uris.add(receipt.receipt_uri)
        if (
            receipt.executed_skill != cumulative.EXPECTED_SKILLS[index]
            or not receipt.physically_executed
        ):
            raise ValueError(f"batch-03 step {index} executed skill mismatch")
        frame, units, dimensions = cumulative.EXPECTED_PROTOCOLS[index]
        if receipt.action_protocol.model_dump(mode="json") != {
            "schema_version": "PhysicalActionProtocolV2",
            "coordinate_frame": frame,
            "units": units,
            "dimensions": dimensions,
            "frequency_hz": 60.0,
            "normalization": "none",
        }:
            raise ValueError(f"batch-03 step {index} action protocol mismatch")
        gates = (
            receipt.schema_gate,
            receipt.stale_track_gate,
            receipt.frame_unit_gate,
            receipt.ik_gate,
            receipt.collision_gate,
            receipt.safety_gate,
        )
        if any(gate != "PASS" for gate in gates) or receipt.collision_or_safety_violation:
            raise ValueError(f"batch-03 step {index} safety/non-controller gate did not pass")
        if index < 7 and receipt.controller_gate != "PASS":
            raise ValueError(f"batch-03 step {index} controller gate did not pass")
        if (
            receipt.started_at_ns <= observation.captured_at_ns
            or receipt.completed_at_ns <= receipt.started_at_ns
        ):
            raise ValueError(f"batch-03 step {index} execution timestamps are invalid")
        freshness = receipt.completed_at_ns

    scene = int(chain.scene_seed)
    final_step = chain.steps[7]
    final_receipt = final_step.physical_receipts[0]
    final_status = final_receipt.execution_measurements.get("status")
    wrong = raw.get("m2b_recovery", {}).get("wrong_object")
    if not isinstance(wrong, Mapping):
        raise ValueError("batch-03 raw probe lacks wrong-object recovery evidence")
    if wrong.get("sequence") != ["SAFE_PLACE_NON_TARGET", "REASSOCIATE_TARGET", "REGRASP"]:
        raise ValueError("batch-03 wrong-object recovery sequence changed")
    if (
        wrong.get("safe_place_non_target_passed") is not True
        or wrong.get("reassociate_target_executed") is not True
        or wrong.get("reassociation_rejection") is not None
        or wrong.get("reassociated_target_track_id") != final_step.public_task_target_track_id
    ):
        raise ValueError("batch-03 public recovery linkage changed")
    if (
        wrong.get("training_eligible") is not False
        or wrong.get("regrasp_target_executed") is not False
    ):
        raise ValueError("batch-03 failed recovery was incorrectly promoted")
    regrasp_execution = wrong.get("regrasp_execution")
    if not isinstance(regrasp_execution, Mapping):
        raise ValueError("batch-03 lacks regrasp execution evidence")
    if regrasp_execution.get("status") != final_status:
        raise ValueError("batch-03 final receipt/recovery execution linkage mismatch")

    if scene == 16073:
        if final_receipt.controller_gate != "PASS" or final_status != "LIFTED":
            raise ValueError("scene 16073 must retain its observed LIFTED controller result")
        if regrasp_execution.get("object_lift_m") != final_receipt.execution_measurements.get(
            "object_lift_m"
        ):
            raise ValueError("scene 16073 lift measurement/receipt linkage mismatch")
        lift_m = final_receipt.execution_measurements.get("object_lift_m")
        if not isinstance(lift_m, (int, float)) or not math.isfinite(lift_m) or lift_m <= 0.0:
            raise ValueError("scene 16073 LIFTED receipt lacks finite positive public lift")
        predicate = wrong.get("public_regrasp_predicates")
        if not isinstance(predicate, Mapping):
            raise ValueError("scene 16073 lacks its public post-regrasp predicate result")
        if (
            predicate.get("schema_version") != "PublicFailurePredicateResultV2"
            or predicate.get("source") != "PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION"
            or predicate.get("simulator_truth_used") is not False
            or predicate.get("task_target_track_id") != final_step.public_task_target_track_id
            or predicate.get("carried_public_track_id") is not None
            or predicate.get("predicates") != []
        ):
            raise ValueError("scene 16073 frozen public predicate rejection changed")
        measurements = predicate.get("measurements_m")
        if not isinstance(measurements, Mapping):
            raise ValueError("scene 16073 public predicate lacks measurements")
        for field in ("hand_vertical_lift_m", "target_hand_xy_error_m"):
            value = measurements.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"scene 16073 public predicate has invalid {field}")
        after = capture_by_label.get("wrong_object_target_after_regrasp")
        if (
            after is None
            or after.get("timestamp_ns") <= final_step.observation.captured_at_ns
            or after.get("timestamp_ns") >= final_receipt.completed_at_ns
            or capture_by_label.get("m2c_step_07_regrasp") is None
        ):
            raise ValueError("scene 16073 post-regrasp capture/final receipt linkage is invalid")
        if REQUIRED_PUBLIC_SUCCESS_PREDICATES.issubset(set(predicate["predicates"])):
            raise ValueError("scene 16073 public predicate unexpectedly accepts success")
        if wrong.get("public_reobserve_status") != "CAPTURED_PENDING_TARGET_REGRASP":
            raise ValueError("scene 16073 public recovery status changed")
        classification = RAW_LIFTED_PUBLIC_REJECT
        public_predicate_accepted = False
    elif scene in {16085, 16102}:
        expected = {
            16085: ("CONTACT_GATE_REJECTED", RAW_CONTACT_REJECT),
            16102: ("PREGRASP_IK_GATE_REJECTED", RAW_PREGRASP_REJECT),
        }[scene]
        if final_receipt.controller_gate != "REJECTED" or final_status != expected[0]:
            raise ValueError(f"scene {scene} final controller rejection changed")
        if regrasp_execution.get("object_lift_m") is not None:
            raise ValueError(f"scene {scene} rejection unexpectedly reports recovery lift")
        if final_receipt.execution_measurements.get("object_lift_m") != 0.0:
            raise ValueError(f"scene {scene} rejected regrasp unexpectedly lifted")
        if wrong.get("public_regrasp_predicates") is not None:
            raise ValueError(f"scene {scene} unexpectedly contains a post-regrasp predicate")
        if "wrong_object_target_after_regrasp" in capture_by_label:
            raise ValueError(f"scene {scene} unexpectedly contains a post-regrasp capture")
        classification = expected[1]
        public_predicate_accepted = None
    else:
        raise ValueError("batch-03 contains an unregistered scene")

    return {
        "classification": classification,
        "raw_probe_status": "PASS",
        "chain_schema": "M2CPathBlockedProbeChainV3",
        "physical_chain_steps": 8,
        "step_0_through_6_all_gates_pass": True,
        "step_7_controller_gate": final_receipt.controller_gate,
        "step_7_status": final_status,
        "step_7_object_lift_m": final_receipt.execution_measurements.get("object_lift_m"),
        "public_success_predicate_required": sorted(REQUIRED_PUBLIC_SUCCESS_PREDICATES),
        "public_success_predicate_accepted": public_predicate_accepted,
        "final_task_success": False,
        "v3_candidates_host_recomputed": True,
        "candidate_count_bound": 8,
        "all_required_pointers_inside_semantic_k8": True,
        "candidate_sizes": candidate_sizes,
        "public_capture_journal_entries": len(captures),
        "all_capture_journal_assets_hash_verified": True,
        "physical_receipt_hashes_and_linkage_verified": True,
        "collision_or_safety_violations": 0,
    }


def _audit_attempt(
    batch: Path,
    *,
    records: Mapping[str, Mapping[str, Any]],
    project: Path,
) -> dict[str, Any]:
    attempt_id = batch.name
    attempt_files = cumulative._regular_file_hashes(batch)
    expected_count = EXPECTED_ATTEMPT_FILE_COUNTS[attempt_id]
    if len(attempt_files) != expected_count:
        raise ValueError(f"{attempt_id} must contain exactly {expected_count} regular files")
    root = cumulative._find_single_attempt_root(batch)
    job = cumulative._load_object(root / "collection-job-v3.json", label="batch-03 job")
    record = records.get(str(job.get("matched_key")))
    if record is None:
        raise ValueError(f"{attempt_id} is not a frozen V3 TRAIN key")
    commit = cumulative._validate_job(job, record, attempt_id=attempt_id, project=project)
    if commit != AUTHORIZED_RUNTIME_COMMIT:
        raise ValueError(f"{attempt_id} does not bind the authorized runtime commit")
    derived = root / "derived-path-blocked-probe.py"
    if cumulative.sha256_file(derived) != cumulative.DERIVED_PROBE_SHA256:
        raise ValueError(f"{attempt_id} derived probe SHA-256 mismatch")
    cumulative._validate_stage_metrics(root / "stage/metrics.json", record)
    details = _validate_raw_chain(
        root / "probe/actuation-probe.json",
        record=record,
        stage_path=root / "stage/m1b_physics_scene.usdc",
    )
    forbidden = {
        "collection-receipt-v3.json",
        "packaged-physical-chain-v3.json",
        "supervised-steps-v3.json",
    }
    if forbidden & {Path(relative).name for relative in attempt_files}:
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
        "evidence_file_sha256": attempt_files,
        "evidence_tree": {
            "regular_file_count": len(attempt_files),
            "canonical_path_sha256_map_digest": cumulative.canonical_sha256(attempt_files),
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
    if observed_dirs != EXPECTED_ATTEMPT_DIRS:
        raise ValueError("batch-03 audit requires exactly its three frozen attempt directories")
    all_files = cumulative._regular_file_hashes(evidence_root)
    if len(all_files) != 164:
        raise ValueError("complete batch-03 evidence root must contain exactly 164 regular files")
    if cumulative.sha256_file(project / CUMULATIVE_AUDITOR_PATH) != CUMULATIVE_AUDITOR_SHA256:
        raise ValueError("byte-bound cumulative audit helper changed")
    sources, records = cumulative._validate_sources(project)
    preregistration, selected = _validate_preregistration(project, records)
    attempts = [
        _audit_attempt(evidence_root / attempt_id, records=records, project=project)
        for attempt_id in EXPECTED_ATTEMPT_DIRS
    ]
    observed_keys = [str(item["identity"]["matched_key"]) for item in attempts]
    observed_scenes = [int(item["identity"]["scene_seed"]) for item in attempts]
    selected_keys = [str(item["matched_key"]) for item in selected]
    if observed_keys != selected_keys or tuple(observed_scenes) != EXPECTED_SCENES:
        raise ValueError("batch-03 attempts differ from preregistered key order")
    if len(set(observed_keys)) != 3 or len(set(observed_scenes)) != 3:
        raise ValueError("batch-03 retried or duplicated a selected identity")
    classifications = Counter(str(item["classification"]) for item in attempts)
    if classifications != Counter(
        {RAW_LIFTED_PUBLIC_REJECT: 1, RAW_CONTACT_REJECT: 1, RAW_PREGRASP_REJECT: 1}
    ):
        raise ValueError("batch-03 terminal classifications differ from observed evidence")
    sdfs = [str(item["identity"]["sdf_sha256"]) for item in attempts]
    if len(set(sdfs)) != 3:
        raise ValueError("batch-03 does not cover three distinct preregistered SDF identities")
    if sum(int(item["evidence_tree"]["regular_file_count"]) for item in attempts) != len(all_files):
        raise ValueError("batch-03 attempt inventories do not cover every regular file")
    sources["batch03_preregistration"] = preregistration
    sources["cumulative_v3_auditor_helper"] = {
        "path": CUMULATIVE_AUDITOR_PATH,
        "file_sha256": CUMULATIVE_AUDITOR_SHA256,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES_BATCH03",
        "evidence_use": "SCRIPTED_V3_TRAIN_COLLECTION_AUDIT_ONLY_NOT_MODEL_OR_Q_B_EVALUATION",
        "finding": (
            "the three preregistered TRAIN keys were each attempted exactly once without retry; "
            "all produced byte-verified eight-step V3 K8 scripted chains with steps 0-6 passing. "
            "Scene 16073 physically reported LIFTED but the unchanged public predicate rejected "
            "success, scene 16085 ended at the contact gate, and scene 16102 ended at the "
            "pregrasp IK gate. No result is promoted to an eligible training sample."
        ),
        "source_bindings": sources,
        "implementation_binding": cumulative._implementation_binding(
            project, AUTHORIZED_RUNTIME_COMMIT
        ),
        "evidence_root": str(evidence_root),
        "evidence_root_inventory": {
            "regular_file_count": len(all_files),
            "canonical_path_sha256_map_digest": cumulative.canonical_sha256(all_files),
            "all_regular_files_byte_hashed": True,
        },
        "scope": {
            "frozen_v3_train_keys": 36,
            "prior_unique_train_keys_attempted": 8,
            "batch03_execution_attempt_directories": 3,
            "batch03_unique_train_keys_attempted": 3,
            "batch03_retry_attempts": 0,
            "batch03_replacement_attempts": 0,
            "batch03_unique_sdf_sha256_covered": 3,
            "batch03_sdf_sha256_covered": sdfs,
            "inference_about_unobserved_train_keys": None,
            "smoke_keys_used": 0,
            "v4_q_a_keys_used": 0,
            "s6_evaluation_keys_used": 0,
        },
        "observed_counts": {
            "raw_v3_eight_step_chains": 3,
            "raw_lifted_but_public_predicate_rejected": 1,
            "raw_final_false_contact_gate_rejected": 1,
            "raw_final_false_pregrasp_ik_gate_rejected": 1,
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
            "success_predicate_or_gate_definition_changed": False,
            "eligible_result_promoted_from_public_predicate_rejection": False,
        },
        "extrapolation": {
            "claims_about_unobserved_keys": None,
            "claims_about_model_performance": None,
            "claims_about_q_b_performance": None,
        },
        "attempts": attempts,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    rows = []
    for attempt in report["attempts"]:
        identity = attempt["identity"]
        evidence = attempt["classification_evidence"]
        rows.append(
            f"| `{attempt['attempt_id']}` | {identity['scene_seed']} | "
            f"`{str(identity['matched_key'])[:30]}…` | `{evidence['step_7_status']}` | "
            f"`{attempt['classification']}` | no |"
        )
    return "\n".join(
        [
            "# M2C S4 V3 TRAIN collection batch 03 audit",
            "",
            f"Status: **{report['status']}**.",
            "",
            str(report["finding"]),
            "",
            "This is a byte-bound audit of scripted TRAIN collection only. It is not training, "
            "a model rollout, Q-B evaluation, or evidence of pure model success.",
            "",
            "## Counts",
            "",
            "- Pre-registered keys attempted once: 3 / 3",
            "- Retry or replacement attempts: 0",
            "- Raw V3 eight-step K8 chains: 3",
            "- Eligible/packaged training samples: 0 / 0",
            "- Distinct frozen SDF identities covered: 3",
            f"- Regular evidence files byte-hashed: {report['evidence_root_inventory']['regular_file_count']}",
            "",
            "## Attempts",
            "",
            "| Attempt | Scene | Frozen key | Step-7 physical status | Classification | Eligible |",
            "| --- | ---: | --- | --- | --- | --- |",
            *rows,
            "",
            "Scene 16073 is deliberately not called successful: its physical receipt says "
            "`LIFTED`, but the frozen public result has no carried public track and no "
            "`grasped=true` / `lifted=true` predicates. The unchanged public acceptance rule "
            "therefore keeps `final_task_success=false` and the sample ineligible.",
            "",
            "## Boundaries",
            "",
            "Training executed: false. Model rollout executed: false. Teacher used: false. "
            "Privileged truth used as policy input: false. Formal Q-B evaluation executed: "
            "false. `pure_model_success_episodes` is null. No claim is made about unobserved "
            "TRAIN keys or model/Q-B performance.",
            "",
        ]
    )


def verify_expected_report(actual: Mapping[str, Any], expected_path: Path) -> None:
    expected = cumulative._load_object(expected_path, label="expected batch-03 audit")
    if actual != expected:
        raise ValueError("recomputed batch-03 audit differs from frozen expected report")


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
