#!/usr/bin/env python3
"""Replay all three consumed Batch-10 attempts without upgrading evidence."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Mapping

from pydantic import ValidationError

from m2c.audit_s4_v4_batch04_permission_failure import (
    Batch04AuditError,
    _claim_core_is_valid,
    _inventory,
    canonical_sha256,
    json_object,
    read_regular_file_once,
    report_bytes,
    sha256_bytes,
)
from m2c.package_path_blocked_collection import project_frozen_manifests
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2CPathBlockedRawProbeChainV4,
    M2CV4RawPublicAssociationCaptureV2,
    build_path_blocked_supervised_dataset_v4,
    host_replay_probe_chain_v4,
    load_v4_training_manifest,
    package_probe_chain_v4,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG_RELATIVE = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-10-PREREG.json")
PREREG_FILE_SHA256 = "85413f02a50db24c1c95214213f9d22c1916a92295fd9e59ecb0aa5985417957"
PREREG_SHA256 = "c3f0b37120237482beb08175e25e89fb6e7ac11a05f447ff34efe48a18de86c8"
PREREG_COMMIT = "f5456d8a600fe015b31005e7f4af923719556220"
SOURCE_SNAPSHOT_COMMIT = "787b68bf03bc11f7d05539c5621d0736657da7ab"
SOURCE_SNAPSHOT_INVENTORY_SHA256 = (
    "013d90d1b6c432194c5554941b488fd10efba8133cf6b1a472530de0db5008ff"
)
PREDECESSOR_RECEIPT_SHA256 = "78683d4171fda3b12c5b39552f6b0a68adbfaaafa4c459c3c10d3a6ca3d59002"
CONTAINER_IMAGE_ID = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
RUNTIME_REGISTRY_SHA256 = "3572f80f1597b7f3bdffb1f8aad90d5baeb086b25c371b88511bc58444813359"
CLAIM_FILE_SHA256 = (
    "64de1575a6a64b1f86a4acbe887331cfe6c9c71110d272c267edf1cadb2b5d84",
    "464e59087ca38d77e5e71eea5329be454c2ad8b980fcb8a635a9cbf2828c536c",
    "35380e4645b3ee9dad80d66e0bfc8a9addfb40bed7102139a45305d4305146eb",
)
EXPECTED_DETECTION_COUNTS = (
    (7, 7, 6, 8, 9, 11, 10, 11),
    (7, 6, 7, 7, 8, 11, 11, 11),
    (7, 12, 10, 7, 8, 9, 10, 10),
)
EXPECTED_FINAL_STATUSES = (
    "PREGRASP_IK_GATE_REJECTED",
    "CONTACT_GATE_REJECTED",
    "CONTACT_GATE_REJECTED",
)
EXPECTED_CLASSIFICATIONS = (
    "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED",
    "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED",
    "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED",
)
EXPECTED_DATASET_EXCLUSIONS = (
    ("FINAL_TASK_NOT_SUCCESSFUL", "STEP_7:CONTROLLER_GATE_NOT_PASSING"),
    ("FINAL_TASK_NOT_SUCCESSFUL", "STEP_7:CONTROLLER_GATE_NOT_PASSING"),
    (
        "FINAL_TASK_NOT_SUCCESSFUL",
        "STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8",
        "STEP_7:CONTROLLER_GATE_NOT_PASSING",
    ),
)
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


class Batch10AuditError(Batch04AuditError):
    """Batch-10 bytes do not prove the bounded zero-eligible outcome."""


def _git_blob(*, project_root: Path, commit: str, relative_path: Path) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative_path.as_posix()}"],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise Batch10AuditError("Batch-10 preregistration Git blob is unavailable")
    return completed.stdout


def _require_false_boundaries(value: object, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if (
                key
                in {
                    "teacher_used",
                    "privileged_truth_policy_input",
                    "model_rollout",
                    "training_executed",
                    "evaluation_executed",
                    "formal_q_b_evaluation",
                }
                and nested is not False
            ):
                raise Batch10AuditError(f"forbidden boundary is not false: {path}.{key}")
            _require_false_boundaries(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _require_false_boundaries(nested, path=f"{path}[{index}]")


def _dataset_asset(probe_root: Path, uri: str) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise Batch10AuditError("raw capture asset is not a dataset URI")
    relative = PurePosixPath(uri.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        raise Batch10AuditError("raw capture asset escaped the probe root")
    resolved = (probe_root / Path(*relative.parts)).resolve(strict=True)
    if not resolved.is_relative_to(probe_root.resolve(strict=True)):
        raise Batch10AuditError("raw capture asset escaped the probe root")
    return resolved


def _validate_claim_and_job(
    *,
    root: Path,
    inventory: Mapping[str, str],
    prereg: Mapping[str, Any],
    identity: Mapping[str, Any],
    ordinal: int,
    previous_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, str]]:
    sequence = ordinal + 11
    key = str(identity["matched_key"])
    prefix = f"raw/train/{key}"
    relative = {
        "canonical_claim": f"ledger/claim-{sequence:08d}.json",
        "projected_claim": f"{prefix}/authorization/collection-claim-v4.json",
        "job": f"{prefix}/collection-job-v4.json",
        "derived_probe": f"{prefix}/derived-path-blocked-probe.py",
        "stage_console": f"{prefix}/stage/console.log",
        "stage_metrics": f"{prefix}/stage/metrics.json",
        "stage_usdc": f"{prefix}/stage/m1b_physics_scene.usdc",
        "probe_console": f"{prefix}/probe/console.log",
        "raw_probe": f"{prefix}/probe/actuation-probe.json",
    }
    try:
        claim_raw = read_regular_file_once(root / relative["canonical_claim"])
        projected_raw = read_regular_file_once(root / relative["projected_claim"])
        claim = json_object(claim_raw, label=f"Batch-10 claim {ordinal}")
        job = json_object(read_regular_file_once(root / relative["job"]), label="Batch-10 job")
    except FileNotFoundError as error:
        raise Batch10AuditError("Batch-10 claim or job evidence is missing") from error
    if sha256_bytes(claim_raw) != CLAIM_FILE_SHA256[ordinal] or claim_raw != projected_raw:
        raise Batch10AuditError("Batch-10 canonical and projected claim bytes differ")
    if not _claim_core_is_valid(claim):
        raise Batch10AuditError("Batch-10 claim semantic receipt hash is invalid")
    if (
        claim.get("schema_version") != "M2CS4V4CollectionConsumptionReceiptV1"
        or claim.get("batch_id") != "m2c-s4-v4-train-batch-10"
        or claim.get("ledger_namespace") != "M2C_S4_V4_COLLECTION_BATCH10"
        or claim.get("ledger_sequence") != sequence
        or claim.get("ordinal") != ordinal
        or claim.get("selected_key") != identity
        or claim.get("selected_key_sha256") != canonical_sha256(identity)
        or claim.get("previous_receipt_sha256") != previous_receipt_sha256
        or claim.get("event") != "CONSUMED_BEFORE_STAGE"
        or claim.get("prereg_file_sha256") != PREREG_FILE_SHA256
        or claim.get("prereg_sha256") != PREREG_SHA256
        or claim.get("prereg_introduced_commit") != PREREG_COMMIT
        or claim.get("committed_source_snapshot") != prereg["committed_source_snapshot"]
        or claim.get("container_image_id") != CONTAINER_IMAGE_ID
        or claim.get("source_sdf_sha256") != identity["sdf_sha256"]
        or claim.get("source_supervision_sha256") != identity["supervision_sha256"]
        or claim.get("source_urdf_sha256") != URDF_SHA256
        or claim.get("role") != "TRAIN"
        or claim.get("split") != "train"
    ):
        raise Batch10AuditError("Batch-10 claim identity or hash chain differs")
    authorization = job.get("collection_authorization")
    if (
        job.get("schema_version") != "M2CPathBlockedCollectionJobV4"
        or job.get("status") != "PREPARED_NOT_EXECUTED"
        or job.get("matched_key") != key
        or job.get("scene_seed") != identity["scene_seed"]
        or job.get("failure_seed") != identity["failure_seed"]
        or job.get("sdf_sha256") != identity["sdf_sha256"]
        or job.get("supervision_sha256") != identity["supervision_sha256"]
        or job.get("urdf_sha256") != URDF_SHA256
        or job.get("runtime_registry_sha256") != RUNTIME_REGISTRY_SHA256
        or job.get("committed_source_snapshot") != prereg["committed_source_snapshot"]
        or not isinstance(authorization, Mapping)
        or authorization.get("consumption_id") != claim.get("consumption_id")
        or authorization.get("consumption_receipt_sha256") != claim.get("receipt_sha256")
        or authorization.get("container_claim_projection_sha256") != CLAIM_FILE_SHA256[ordinal]
        or authorization.get("prereg_file_sha256") != PREREG_FILE_SHA256
        or authorization.get("prereg_sha256") != PREREG_SHA256
    ):
        raise Batch10AuditError("Batch-10 job does not bind the consumed claim")
    if inventory[relative["derived_probe"]] != claim.get("derived_probe_sha256"):
        raise Batch10AuditError("Batch-10 derived probe hash differs from its claim")
    _require_false_boundaries(claim)
    _require_false_boundaries(job)
    return claim, job, prefix, relative


def _validate_physical_attempt(
    *,
    root: Path,
    inventory: Mapping[str, str],
    identity: Mapping[str, Any],
    claim: Mapping[str, Any],
    prefix: str,
    relative: Mapping[str, str],
    expected_detection_counts: tuple[int, ...],
    expected_final_status: str,
    training_manifest: Any,
    s6_manifest: Any,
) -> dict[str, Any]:
    metrics = json_object(read_regular_file_once(root / relative["stage_metrics"]), label="metrics")
    raw_probe_bytes = read_regular_file_once(root / relative["raw_probe"])
    raw_probe = json_object(raw_probe_bytes, label="Batch-10 raw physical probe")
    stage_console = read_regular_file_once(root / relative["stage_console"])
    probe_console = read_regular_file_once(root / relative["probe_console"])
    if (
        metrics.get("status") != "PASS"
        or metrics.get("source_hashes")
        != {
            "panda_controlled.urdf": URDF_SHA256,
            f"scene-{identity['scene_seed']}.sdf": identity["sdf_sha256"],
            f"scene-{identity['scene_seed']}.supervision.json": identity["supervision_sha256"],
        }
        or metrics.get("qrm_closed_loop_smoke", {}).get("enabled") is not False
        or b"M1B_ISAAC_DATASET_PASS " not in stage_console
        or b"Simulation App Shutting Down" not in stage_console
        or b"Simulation App Shutting Down" not in probe_console
    ):
        raise Batch10AuditError("Batch-10 Isaac lifecycle or stage acceptance differs")
    clean_stage = metrics.get("clean_physics_stage")
    if (
        not isinstance(clean_stage, Mapping)
        or clean_stage.get("sha256") != inventory[relative["stage_usdc"]]
    ):
        raise Batch10AuditError("Batch-10 clean stage hash differs")
    authorization = raw_probe.get("m2c_v4_collection_authorization")
    chain_raw = raw_probe.get("m2c_path_blocked_physical_chain")
    captures = raw_probe.get("m2c_v4_raw_association_captures")
    if not isinstance(authorization, Mapping) or not isinstance(chain_raw, Mapping):
        raise Batch10AuditError("Batch-10 raw probe lacks authorization or physical chain")
    if not isinstance(captures, list) or len(captures) != 8:
        raise Batch10AuditError("Batch-10 raw probe does not contain eight captures")
    if (
        authorization.get("consumption_id") != claim.get("consumption_id")
        or authorization.get("consumption_receipt_sha256") != claim.get("receipt_sha256")
        or authorization.get("matched_key") != identity["matched_key"]
        or authorization.get("failure_seed") != identity["failure_seed"]
        or authorization.get("source_sdf_sha256") != identity["sdf_sha256"]
        or authorization.get("source_supervision_sha256") != identity["supervision_sha256"]
        or authorization.get("container_image_id") != CONTAINER_IMAGE_ID
        or chain_raw.get("collection_authorization_sha256") != canonical_sha256(authorization)
        or raw_probe.get("actuation_probe_source_sha256") != claim.get("derived_probe_sha256")
    ):
        raise Batch10AuditError("Batch-10 raw chain is not bound to the consumed claim")
    try:
        chain = M2CPathBlockedRawProbeChainV4.model_validate(chain_raw)
    except ValidationError as error:
        raise Batch10AuditError("Batch-10 raw physical chain schema is invalid") from error
    if (
        chain.scene_seed != identity["scene_seed"]
        or chain.failure_seed != identity["failure_seed"]
        or chain.matched_key != identity["matched_key"]
        or chain.sdf_sha256 != identity["sdf_sha256"]
        or chain.supervision_sha256 != identity["supervision_sha256"]
        or chain.final_task_success is not False
        or [step.decision_index for step in chain.steps] != list(range(8))
    ):
        raise Batch10AuditError("Batch-10 raw physical chain identity differs")
    probe_root = (root / prefix / "probe").resolve(strict=True)
    receipt_ids: list[str] = []
    for index, (raw_capture, expected_count, step) in enumerate(
        zip(captures, expected_detection_counts, chain.steps, strict=True)
    ):
        if not isinstance(raw_capture, Mapping):
            raise Batch10AuditError("Batch-10 raw public capture is not an object")
        try:
            capture = M2CV4RawPublicAssociationCaptureV2.model_validate(raw_capture)
        except ValidationError as error:
            raise Batch10AuditError("Batch-10 raw public capture schema is invalid") from error
        if len(capture.detections) != expected_count:
            raise Batch10AuditError("Batch-10 raw public detection count differs")
        if step.observation.capture_receipt_sha256 != canonical_sha256(raw_capture):
            raise Batch10AuditError("Batch-10 raw observation capture receipt differs")
        if (
            step.observation.association_capture_index != index
            or step.observation.captured_at_ns != capture.timestamp_ns
            or step.observation.rgb_sha256 != capture.rgb_sha256
            or step.observation.depth_sha256 != capture.depth_sha256
        ):
            raise Batch10AuditError("Batch-10 raw observation does not bind its capture")
        for kind in ("rgb", "depth"):
            asset = _dataset_asset(probe_root, str(raw_capture[f"{kind}_uri"]))
            if sha256_bytes(read_regular_file_once(asset)) != raw_capture[f"{kind}_sha256"]:
                raise Batch10AuditError("Batch-10 raw RGB-D asset hash differs")
        if len(step.physical_receipts) != 1:
            raise Batch10AuditError("Batch-10 physical step does not have one receipt")
        raw_receipt = chain_raw["steps"][index]["physical_receipts"][0]
        receipt = step.physical_receipts[0]
        if not isinstance(raw_receipt, Mapping):
            raise Batch10AuditError("Batch-10 raw physical receipt is not an object")
        core = {key: value for key, value in raw_receipt.items() if key != "receipt_sha256"}
        if (
            canonical_sha256(core) != receipt.receipt_sha256
            or receipt.executed_skill != EXPECTED_SKILLS[index]
            or receipt.physically_executed is not True
            or receipt.collision_or_safety_violation is not False
            or receipt.schema_gate != "PASS"
            or receipt.stale_track_gate != "PASS"
            or receipt.frame_unit_gate != "PASS"
            or receipt.ik_gate != "PASS"
            or receipt.collision_gate != "PASS"
            or receipt.safety_gate != "PASS"
            or receipt.controller_gate != ("REJECTED" if index == 7 else "PASS")
        ):
            raise Batch10AuditError("Batch-10 physical receipt or safety gates differ")
        receipt_ids.append(receipt.receipt_id)
    if len(set(receipt_ids)) != 8:
        raise Batch10AuditError("Batch-10 physical receipt IDs are not unique")
    terminal = chain.steps[7].physical_receipts[0]
    if terminal.execution_measurements.get("status") != expected_final_status:
        raise Batch10AuditError("Batch-10 terminal execution status differs")
    if raw_probe.get("status") != "PASS" or raw_probe.get("not_policy_rollout") is not True:
        raise Batch10AuditError("Batch-10 raw probe status or rollout boundary differs")
    _require_false_boundaries(raw_probe)

    training_key = next(
        item
        for item in training_manifest.training_keys
        if item.matched_key == identity["matched_key"]
    )
    replayed = host_replay_probe_chain_v4(
        chain_raw,
        captures,
        training_key=training_key,
        training_manifest=training_manifest,
        capture_source_implementation_sha256=str(raw_probe["actuation_probe_source_sha256"]),
    )
    packaged = package_probe_chain_v4(
        replayed.model_dump(mode="json"),
        training_manifest=training_manifest,
        s6_manifest=s6_manifest,
        runtime_registry_sha256=RUNTIME_REGISTRY_SHA256,
        source_evidence_uri="dataset://actuation-probe.json",
        source_evidence_sha256=sha256_bytes(raw_probe_bytes),
    )
    dataset = build_path_blocked_supervised_dataset_v4(
        packaged,
        training_manifest=training_manifest,
        s6_manifest=s6_manifest,
    )
    return {
        "raw_probe_sha256": sha256_bytes(raw_probe_bytes),
        "raw_chain_schema": chain.schema_version,
        "raw_chain_final_task_success": chain.final_task_success,
        "raw_capture_schema": "M2CV4RawPublicAssociationCaptureV2",
        "raw_capture_detection_counts": list(expected_detection_counts),
        "raw_detection_capacity": 32,
        "host_replay_passed": True,
        "offline_dataset_status": dataset.status,
        "offline_dataset_sample_count": len(dataset.samples),
        "offline_dataset_exclusion_reasons": dataset.validation.exclusion_reasons,
        "physical_skill_receipts": 8,
        "collision_or_safety_violations": 0,
        "step_0_through_6_all_gates_pass": True,
        "final_controller_gate": "REJECTED",
        "final_execution_status": expected_final_status,
    }


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    prereg_raw = read_regular_file_once(project_root / PREREG_RELATIVE)
    if sha256_bytes(prereg_raw) != PREREG_FILE_SHA256:
        raise Batch10AuditError("Batch-10 preregistration bytes changed")
    if (
        _git_blob(
            project_root=project_root,
            commit=PREREG_COMMIT,
            relative_path=PREREG_RELATIVE,
        )
        != prereg_raw
    ):
        raise Batch10AuditError("Batch-10 preregistration differs from its introduction blob")
    prereg = json_object(prereg_raw, label="Batch-10 preregistration")
    selected = prereg.get("selected_keys")
    if (
        prereg.get("prereg_sha256") != PREREG_SHA256
        or prereg.get("status") != "FROZEN_BEFORE_ANY_SELECTED_KEY_EXECUTION_OR_RESULT"
        or prereg.get("registered_before_selected_key_execution") is not True
        or prereg.get("selection_uses_outcomes") is not False
        or prereg.get("stop_after_selected_keys") != 3
        or prereg.get("retry_authorized") is not False
        or prereg.get("replacement_authorized") is not False
        or not isinstance(selected, list)
        or len(selected) != 3
        or prereg.get("committed_source_snapshot", {}).get("commit") != SOURCE_SNAPSHOT_COMMIT
        or prereg.get("committed_source_snapshot", {}).get("inventory_sha256")
        != SOURCE_SNAPSHOT_INVENTORY_SHA256
    ):
        raise Batch10AuditError("Batch-10 preregistration contract differs")
    inventory = _inventory(root)
    if len(inventory) != 168:
        raise Batch10AuditError("Batch-10 evidence inventory count differs")
    job_keys = {path.name for path in (root / "raw/train").iterdir() if path.is_dir()}
    if job_keys != {str(item["matched_key"]) for item in selected}:
        raise Batch10AuditError("Batch-10 evidence job set differs from selected keys")
    training_manifest = load_v4_training_manifest(
        project_root / "configs/m2c_s4_v4_training_keys.json"
    )
    _, _, _, s6_manifest = project_frozen_manifests(
        project_root / "configs/m2c_s4_training_keys.json",
        project_root / "configs/m2c_s6_evaluation_keys.json",
        project_root / "configs/qrm_runtime_mapping_v2.yaml",
    )
    attempts: list[dict[str, Any]] = []
    previous_receipt = PREDECESSOR_RECEIPT_SHA256
    all_receipt_ids: set[str] = set()
    for ordinal, identity in enumerate(selected):
        if not isinstance(identity, Mapping):
            raise Batch10AuditError("Batch-10 selected identity is malformed")
        claim, _job, prefix, relative = _validate_claim_and_job(
            root=root,
            inventory=inventory,
            prereg=prereg,
            identity=identity,
            ordinal=ordinal,
            previous_receipt_sha256=previous_receipt,
        )
        previous_receipt = str(claim["receipt_sha256"])
        job_inventory = {
            path: digest for path, digest in inventory.items() if path.startswith(f"{prefix}/")
        }
        if len(job_inventory) != 55:
            raise Batch10AuditError("Batch-10 per-job evidence inventory count differs")
        physical = _validate_physical_attempt(
            root=root,
            inventory=inventory,
            identity=identity,
            claim=claim,
            prefix=prefix,
            relative=relative,
            expected_detection_counts=EXPECTED_DETECTION_COUNTS[ordinal],
            expected_final_status=EXPECTED_FINAL_STATUSES[ordinal],
            training_manifest=training_manifest,
            s6_manifest=s6_manifest,
        )
        if (
            tuple(physical["offline_dataset_exclusion_reasons"])
            != EXPECTED_DATASET_EXCLUSIONS[ordinal]
        ):
            raise Batch10AuditError("Batch-10 offline dataset exclusion reasons differ")
        raw_probe = json_object(
            read_regular_file_once(root / relative["raw_probe"]), label="Batch-10 raw probe"
        )
        current_receipt_ids = {
            str(step["physical_receipts"][0]["receipt_id"])
            for step in raw_probe["m2c_path_blocked_physical_chain"]["steps"]
        }
        if all_receipt_ids & current_receipt_ids:
            raise Batch10AuditError("Batch-10 physical receipt ID is reused across attempts")
        all_receipt_ids.update(current_receipt_ids)
        attempts.append(
            {
                "attempt_id": f"batch10-{ordinal + 1:02d}",
                "identity": identity,
                "classification": EXPECTED_CLASSIFICATIONS[ordinal],
                "consumption_id": claim["consumption_id"],
                "consumed_at_ns": claim["consumed_at_ns"],
                "stage_acceptance_passed": True,
                "probe_process_invoked": True,
                "physical_action_executed": True,
                "training_sample_eligible": False,
                "training_sample_packaged": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "model_rollout": False,
                "formal_q_b_evaluation": False,
                "core_evidence_file_sha256": {
                    label: inventory[path] for label, path in sorted(relative.items())
                },
                "job_inventory": {
                    "regular_file_count": len(job_inventory),
                    "canonical_path_sha256_map_digest": canonical_sha256(job_inventory),
                },
                **physical,
            }
        )
    audit_path = Path(__file__).resolve()
    return {
        "schema_version": "M2CS4V4Batch10CollectionAuditV1",
        "status": "BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH10",
        "batch_preregistration": {
            "path": PREREG_RELATIVE.as_posix(),
            "sha256": PREREG_FILE_SHA256,
            "introduced_commit": PREREG_COMMIT,
            "prereg_sha256": PREREG_SHA256,
            "source_snapshot_commit": SOURCE_SNAPSHOT_COMMIT,
            "source_snapshot_inventory_sha256": SOURCE_SNAPSHOT_INVENTORY_SHA256,
        },
        "attempts": attempts,
        "observed_counts": {
            "consumed_unique_train_keys": 3,
            "stage_acceptance_passes": 3,
            "probe_process_invocations": 3,
            "raw_physical_chains": 3,
            "physical_skill_receipts": 24,
            "terminal_pregrasp_ik_gate_rejections": 1,
            "terminal_contact_gate_rejections": 2,
            "collision_or_safety_violations": 0,
            "host_replay_passes": 3,
            "training_samples_eligible": 0,
            "training_samples_packaged": 0,
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "total_file_bytes": sum((root / path).stat().st_size for path in inventory),
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
        },
        "failure_taxonomy": {
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
            "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
        },
        "audit_implementation": {
            "path": "scripts/m2c/audit_s4_v4_batch10_collection.py",
            "sha256": sha256_bytes(read_regular_file_once(audit_path)),
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_executed": False,
        "model_rollout_executed": False,
        "formal_q_b_evaluation_executed": False,
        "pure_model_success_episodes": None,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    return f"""# M2C S4 V4 Batch-10 collection audit

Status: `{report["status"]}`

The three outcome-blind preregistered TRAIN keys were consumed exactly once. All three stage
builders and all three physical probes completed, producing three strict eight-step V4 raw
chains and 24 physical skill receipts. Host replay passed for every chain under the ADR-0025
32-detection raw schema. No episode satisfied the unchanged final training predicate, so no
training sample was eligible or packaged.

## Observed outcomes

- scene 19126: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- scene 19133: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 19146: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`; offline replay also
  records `STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch10_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch10-complete \
  --expected-json reports/m2c-s4-v4-batch10-collection.json
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--expected-json", type=Path)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    report = build_report(evidence_root=args.evidence_root)
    encoded = report_bytes(report)
    if args.expected_json is not None and read_regular_file_once(args.expected_json) != encoded:
        raise SystemExit("Batch-10 audit differs from expected JSON")
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
