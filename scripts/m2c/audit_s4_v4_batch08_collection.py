#!/usr/bin/env python3
"""Replay all three consumed Batch-08 attempts without upgrading evidence."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
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
from xh_agent.perception.public_track_associator_v2 import (
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2CPathBlockedRawProbeChainV4,
    M2CV4RawPublicAssociationCaptureV1,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG_RELATIVE = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-08-PREREG.json")
PREREG_FILE_SHA256 = "7cbfaf50519957a213a71eb740116cbe1e85df822dd9dfb7d53def9b26e0d827"
PREREG_COMMIT = "b90d573e2cbd977c13e96fb97365a66efc235eb9"
COLLECTION_CONTRACT_PATH = "src/xh_agent/policy/qrm_lite/path_blocked_collection_v4.py"
COLLECTION_CONTRACT_SHA256 = "1bb916b375e9ac3336911a11e96d11506709b285ac74d8f7579a8cfb5bccd887"
EXPECTED_DETECTION_COUNTS = [7, 13, 11, 7, 8, 9, 10, 10]
EXPECTED_SKILLS = [
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
]


class Batch08AuditError(Batch04AuditError):
    """Batch-08 bytes do not prove the bounded mixed outcome."""


def _require_false_boundary(value: object, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {"teacher_used", "privileged_truth_policy_input", "model_rollout"}:
                if nested is not False:
                    raise Batch08AuditError(f"forbidden boundary is not false: {path}.{key}")
            _require_false_boundary(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _require_false_boundary(nested, path=f"{path}[{index}]")


def _dataset_asset(probe_root: Path, uri: str) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise Batch08AuditError("raw capture asset is not a dataset URI")
    relative = PurePosixPath(uri.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        raise Batch08AuditError("raw capture asset escaped the probe root")
    resolved = (probe_root / Path(*relative.parts)).resolve(strict=True)
    if not resolved.is_relative_to(probe_root.resolve(strict=True)):
        raise Batch08AuditError("raw capture asset escaped the probe root")
    return resolved


def _validate_raw_capture_without_capacity(
    raw: Mapping[str, Any],
    *,
    expected_count: int,
    probe_root: Path,
) -> None:
    detections = raw.get("detections")
    samples = raw.get("proprioception_interval")
    if not isinstance(detections, list) or len(detections) != expected_count:
        raise Batch08AuditError("raw public detection count changed")
    if not isinstance(samples, list) or not samples:
        raise Batch08AuditError("raw public proprioception journal is absent")
    try:
        for detection in detections:
            PublicRGBDDetectionV2.model_validate(detection)
        for sample in samples:
            PublicRobotProprioceptionV2.model_validate(sample)
        # Validate every field and cross-field invariant other than the disputed
        # raw-detection capacity.  Empty detections are legal for this model.
        M2CV4RawPublicAssociationCaptureV1.model_validate({**raw, "detections": []})
    except ValidationError as error:
        raise Batch08AuditError("raw public capture failed a non-capacity contract") from error
    for kind in ("rgb", "depth"):
        uri = raw.get(f"{kind}_uri")
        digest = raw.get(f"{kind}_sha256")
        if not isinstance(uri, str) or not isinstance(digest, str):
            raise Batch08AuditError("raw capture lacks an RGB-D asset binding")
        if sha256_bytes(read_regular_file_once(_dataset_asset(probe_root, uri))) != digest:
            raise Batch08AuditError("raw capture RGB-D asset hash differs")


def _capacity_rejection(raw: Mapping[str, Any], *, expected_count: int) -> dict[str, Any]:
    try:
        M2CV4RawPublicAssociationCaptureV1.model_validate(raw)
    except ValidationError as error:
        errors = error.errors(include_url=False, include_input=False)
        if len(errors) != 1:
            raise Batch08AuditError(
                "capacity rejection has unexpected validation errors"
            ) from error
        item = errors[0]
        if (
            item.get("type") != "too_long"
            or tuple(item.get("loc", ())) != ("detections",)
            or item.get("ctx")
            != {"field_type": "List", "max_length": 8, "actual_length": expected_count}
        ):
            raise Batch08AuditError("capture was rejected for a reason other than max_length=8")
        return {
            "capture_index": -1,
            "actual_detection_count": expected_count,
            "schema_max_detection_count": 8,
            "validation_error_type": "too_long",
        }
    raise Batch08AuditError("over-capacity raw capture unexpectedly passed the frozen schema")


def _validate_claim_and_job(
    *,
    root: Path,
    inventory: Mapping[str, str],
    identity: Mapping[str, Any],
    ordinal: int,
    previous_receipt_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, str]]:
    sequence = ordinal + 5
    key = str(identity["matched_key"])
    prefix = f"raw/train/{key}"
    relative = {
        "canonical_claim": f"ledger/claim-{sequence:08d}.json",
        "projected_claim": f"{prefix}/authorization/collection-claim-v4.json",
        "job": f"{prefix}/collection-job-v4.json",
        "derived_probe": f"{prefix}/derived-path-blocked-probe.py",
        "stage_console": f"{prefix}/stage/console.log",
        "stage_usdc": f"{prefix}/stage/m1b_physics_scene.usdc",
    }
    try:
        claim_raw = read_regular_file_once(root / relative["canonical_claim"])
        projected_raw = read_regular_file_once(root / relative["projected_claim"])
        claim = json_object(claim_raw, label=f"Batch-08 claim {ordinal}")
        job = json_object(read_regular_file_once(root / relative["job"]), label="Batch-08 job")
    except FileNotFoundError as error:
        raise Batch08AuditError("Batch-08 claim or job evidence is missing") from error
    if claim_raw != projected_raw or not _claim_core_is_valid(claim):
        raise Batch08AuditError("Batch-08 projected claim differs from the canonical claim")
    if (
        claim.get("schema_version") != "M2CS4V4CollectionConsumptionReceiptV1"
        or claim.get("batch_id") != "m2c-s4-v4-train-batch-08"
        or claim.get("ledger_sequence") != sequence
        or claim.get("ordinal") != ordinal
        or claim.get("selected_key") != identity
        or claim.get("previous_receipt_sha256") != previous_receipt_sha256
        or claim.get("event") != "CONSUMED_BEFORE_STAGE"
    ):
        raise Batch08AuditError("Batch-08 claim identity or hash chain differs")
    authorization = job.get("collection_authorization")
    if (
        job.get("schema_version") != "M2CPathBlockedCollectionJobV4"
        or job.get("matched_key") != key
        or job.get("scene_seed") != identity["scene_seed"]
        or job.get("failure_seed") != identity["failure_seed"]
        or not isinstance(authorization, Mapping)
        or authorization.get("consumption_id") != claim.get("consumption_id")
        or authorization.get("consumption_receipt_sha256") != claim.get("receipt_sha256")
        or authorization.get("container_claim_projection_sha256") != sha256_bytes(projected_raw)
        or job.get("teacher_used") is not False
        or job.get("privileged_truth_policy_input") is not False
        or job.get("training_executed") is not False
        or job.get("evaluation_executed") is not False
    ):
        raise Batch08AuditError("Batch-08 job does not bind the consumed claim")
    if inventory[relative["derived_probe"]] != claim.get("derived_probe_sha256"):
        raise Batch08AuditError("Batch-08 derived probe hash differs from its claim")
    return claim, job, prefix, relative


def _validate_physical_attempt(
    *,
    root: Path,
    inventory: Mapping[str, str],
    identity: Mapping[str, Any],
    claim: Mapping[str, Any],
    prefix: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    relative = {
        "stage_metrics": f"{prefix}/stage/metrics.json",
        "probe_console": f"{prefix}/probe/console.log",
        "raw_probe": f"{prefix}/probe/actuation-probe.json",
    }
    try:
        metrics = json_object(
            read_regular_file_once(root / relative["stage_metrics"]), label="metrics"
        )
        raw_probe_bytes = read_regular_file_once(root / relative["raw_probe"])
        raw_probe = json_object(raw_probe_bytes, label="Batch-08 raw physical probe")
    except FileNotFoundError as error:
        raise Batch08AuditError("Batch-08 physical attempt evidence is missing") from error
    if (
        metrics.get("status") != "PASS"
        or metrics.get("source_hashes")
        != {
            "panda_controlled.urdf": claim["source_urdf_sha256"],
            f"scene-{identity['scene_seed']}.sdf": identity["sdf_sha256"],
            f"scene-{identity['scene_seed']}.supervision.json": identity["supervision_sha256"],
        }
        or metrics.get("qrm_closed_loop_smoke", {}).get("enabled") is not False
    ):
        raise Batch08AuditError("Batch-08 accepted stage contract differs")
    authorization = raw_probe.get("m2c_v4_collection_authorization")
    chain_raw = raw_probe.get("m2c_path_blocked_physical_chain")
    captures = raw_probe.get("m2c_v4_raw_association_captures")
    if not isinstance(authorization, Mapping) or not isinstance(chain_raw, Mapping):
        raise Batch08AuditError("Batch-08 raw probe lacks authorization or physical chain")
    if not isinstance(captures, list) or len(captures) != 8:
        raise Batch08AuditError("Batch-08 raw probe does not contain eight captures")
    if (
        authorization.get("consumption_id") != claim.get("consumption_id")
        or authorization.get("consumption_receipt_sha256") != claim.get("receipt_sha256")
        or authorization.get("matched_key") != identity["matched_key"]
        or authorization.get("failure_seed") != identity["failure_seed"]
        or authorization.get("source_sdf_sha256") != identity["sdf_sha256"]
        or authorization.get("source_supervision_sha256") != identity["supervision_sha256"]
        or authorization.get("teacher_used") is not False
        or authorization.get("privileged_truth_policy_input") is not False
        or chain_raw.get("collection_authorization_sha256") != canonical_sha256(authorization)
    ):
        raise Batch08AuditError("Batch-08 raw chain is not bound to the consumed claim")
    try:
        chain = M2CPathBlockedRawProbeChainV4.model_validate(chain_raw)
    except ValidationError as error:
        raise Batch08AuditError("Batch-08 raw physical chain schema is invalid") from error
    if (
        chain.scene_seed != identity["scene_seed"]
        or chain.failure_seed != identity["failure_seed"]
        or chain.matched_key != identity["matched_key"]
        or chain.sdf_sha256 != identity["sdf_sha256"]
        or chain.supervision_sha256 != identity["supervision_sha256"]
        or chain.final_task_success is not False
        or [step.decision_index for step in chain.steps] != list(range(8))
    ):
        raise Batch08AuditError("Batch-08 raw physical chain identity differs")
    _require_false_boundary(raw_probe)
    probe_root = (root / prefix / "probe").resolve(strict=True)
    capacity_rejections: list[dict[str, Any]] = []
    for index, (raw_capture, expected_count, step) in enumerate(
        zip(captures, EXPECTED_DETECTION_COUNTS, chain.steps, strict=True)
    ):
        if not isinstance(raw_capture, Mapping):
            raise Batch08AuditError("Batch-08 raw public capture is not an object")
        _validate_raw_capture_without_capacity(
            raw_capture,
            expected_count=expected_count,
            probe_root=probe_root,
        )
        if step.observation.capture_receipt_sha256 != canonical_sha256(raw_capture):
            raise Batch08AuditError("Batch-08 raw observation capture receipt differs")
        if (
            step.observation.association_capture_index != index
            or step.observation.captured_at_ns != raw_capture["timestamp_ns"]
            or step.observation.rgb_sha256 != raw_capture["rgb_sha256"]
            or step.observation.depth_sha256 != raw_capture["depth_sha256"]
        ):
            raise Batch08AuditError("Batch-08 raw observation does not bind its capture")
        if expected_count > 8:
            rejection = _capacity_rejection(raw_capture, expected_count=expected_count)
            rejection["capture_index"] = index
            capacity_rejections.append(rejection)
        else:
            try:
                M2CV4RawPublicAssociationCaptureV1.model_validate(raw_capture)
            except ValidationError as error:
                raise Batch08AuditError("in-capacity raw capture unexpectedly failed") from error
        if len(step.physical_receipts) != 1:
            raise Batch08AuditError("Batch-08 physical step does not have one receipt")
        raw_receipt = chain_raw["steps"][index]["physical_receipts"][0]
        if not isinstance(raw_receipt, Mapping):
            raise Batch08AuditError("Batch-08 raw physical receipt is not an object")
        core = {key: value for key, value in raw_receipt.items() if key != "receipt_sha256"}
        receipt = step.physical_receipts[0]
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
            raise Batch08AuditError("Batch-08 physical receipt or safety gates differ")
    if [item["capture_index"] for item in capacity_rejections] != [1, 2, 5, 6, 7]:
        raise Batch08AuditError("Batch-08 capacity rejection indices differ")
    if raw_probe.get("status") != "PASS" or raw_probe.get("not_policy_rollout") is not True:
        raise Batch08AuditError("Batch-08 raw probe status or rollout boundary differs")
    return {
        "raw_probe_sha256": sha256_bytes(raw_probe_bytes),
        "raw_chain_schema": chain.schema_version,
        "raw_chain_final_task_success": chain.final_task_success,
        "raw_capture_detection_counts": EXPECTED_DETECTION_COUNTS,
        "schema_capacity_rejections": capacity_rejections,
        "physical_skill_receipts": 8,
        "collision_or_safety_violations": 0,
        "final_controller_gate": "REJECTED",
        "final_execution_status": "CONTACT_GATE_REJECTED",
    }, relative


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    prereg_raw = read_regular_file_once(project_root / PREREG_RELATIVE)
    if sha256_bytes(prereg_raw) != PREREG_FILE_SHA256:
        raise Batch08AuditError("Batch-08 preregistration bytes changed")
    prereg = json_object(prereg_raw, label="Batch-08 preregistration")
    selected = prereg.get("selected_keys")
    if not isinstance(selected, list) or len(selected) != 3:
        raise Batch08AuditError("Batch-08 preregistration does not select exactly three keys")
    contract_bytes = read_regular_file_once(project_root / COLLECTION_CONTRACT_PATH)
    if sha256_bytes(contract_bytes) != COLLECTION_CONTRACT_SHA256:
        raise Batch08AuditError("Batch-08 collection contract bytes changed")
    if contract_bytes.count(b"detections: list[PublicRGBDDetectionV2] = Field(max_length=8)") != 1:
        raise Batch08AuditError("Batch-08 collection contract no longer has its exact raw bound")
    inventory = _inventory(root)
    predecessor = json_object(
        read_regular_file_once(root / "ledger/claim-00000004.json"),
        label="Batch-08 predecessor claim",
    )
    if not _claim_core_is_valid(predecessor) or predecessor.get("ledger_sequence") != 4:
        raise Batch08AuditError("Batch-08 predecessor claim is invalid")
    previous_receipt = str(predecessor["receipt_sha256"])
    attempts: list[dict[str, Any]] = []
    for ordinal, identity in enumerate(selected):
        if not isinstance(identity, Mapping):
            raise Batch08AuditError("Batch-08 selected identity is malformed")
        claim, _job, prefix, paths = _validate_claim_and_job(
            root=root,
            inventory=inventory,
            identity=identity,
            ordinal=ordinal,
            previous_receipt_sha256=previous_receipt,
        )
        previous_receipt = str(claim["receipt_sha256"])
        console = read_regular_file_once(root / paths["stage_console"]).decode("utf-8")
        attempt: dict[str, Any] = {
            "attempt_id": f"batch08-{ordinal + 1:02d}",
            "identity": identity,
            "consumption_id": claim["consumption_id"],
            "consumed_at_ns": claim["consumed_at_ns"],
            "stage_simulation_app_started": "Simulation App Starting" in console,
            "training_sample_eligible": False,
            "training_sample_packaged": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "model_rollout": False,
            "formal_q_b_evaluation": False,
        }
        if ordinal < 2:
            if (
                "Simulation App Startup Complete" not in console
                or not (
                    "Segmentation fault" in console
                    or "terminating this process with exit code 139" in console
                )
                or (root / prefix / "stage/metrics.json").exists()
                or any((root / prefix / "probe").rglob("*"))
            ):
                raise Batch08AuditError("Batch-08 stage crash evidence differs")
            attempt.update(
                {
                    "classification": "ISAAC_STAGE_PROCESS_EXIT_139",
                    "stage_acceptance_passed": False,
                    "probe_process_invoked": False,
                    "physical_action_executed": False,
                    "evidence_file_sha256": {
                        label: inventory[relative] for label, relative in sorted(paths.items())
                    },
                }
            )
        else:
            physical, extra_paths = _validate_physical_attempt(
                root=root,
                inventory=inventory,
                identity=identity,
                claim=claim,
                prefix=prefix,
            )
            paths.update(extra_paths)
            attempt.update(
                {
                    "classification": "RAW_CHAIN_COMPLETE_HOST_SCHEMA_CAPACITY_REJECTED",
                    "stage_acceptance_passed": True,
                    "probe_process_invoked": True,
                    "probe_simulation_app_started": True,
                    "physical_action_executed": True,
                    "host_replay_passed": False,
                    "evidence_file_sha256": {
                        label: inventory[relative] for label, relative in sorted(paths.items())
                    },
                    **physical,
                }
            )
        attempts.append(attempt)
    if any(path.name.startswith("m2c-s4-v4-train-") for path in root.glob("packaged/*")):
        raise Batch08AuditError("Batch-08 evidence contains a packaged training sample")
    audit_path = Path(__file__).resolve()
    return {
        "schema_version": "M2CS4V4Batch08CollectionAuditV1",
        "status": "BLOCKED_RAW_DETECTION_CAPACITY_SCHEMA_DECISION_REQUIRED",
        "batch_preregistration": {
            "path": PREREG_RELATIVE.as_posix(),
            "sha256": PREREG_FILE_SHA256,
            "introduced_commit": PREREG_COMMIT,
            "prereg_sha256": prereg["prereg_sha256"],
        },
        "attempts": attempts,
        "observed_counts": {
            "consumed_unique_train_keys": 3,
            "stage_process_exit_139": 2,
            "stage_acceptance_passes": 1,
            "probe_process_invocations": 1,
            "raw_physical_chains": 1,
            "physical_skill_receipts": 8,
            "collision_or_safety_violations": 0,
            "host_replay_passes": 0,
            "training_samples_eligible": 0,
            "training_samples_packaged": 0,
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
        },
        "root_cause": {
            "classification": "RAW_PUBLIC_DETECTION_COUNT_EXCEEDS_FROZEN_SCHEMA_BOUND",
            "collection_contract_path": COLLECTION_CONTRACT_PATH,
            "collection_contract_sha256": COLLECTION_CONTRACT_SHA256,
            "final_candidate_count_bound_changed": False,
            "raw_capture_detection_counts": EXPECTED_DETECTION_COUNTS,
            "schema_max_raw_detections": 8,
            "first_rejected_capture_index": 1,
            "first_rejected_actual_detection_count": 13,
            "permission_failure": False,
            "requires_human_schema_gate_decision": True,
        },
        "audit_implementation": {
            "path": "scripts/m2c/audit_s4_v4_batch08_collection.py",
            "sha256": sha256_bytes(read_regular_file_once(audit_path)),
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_executed": False,
        "formal_q_b_evaluation_executed": False,
        "pure_model_success_episodes": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    encoded = report_bytes(build_report(evidence_root=args.evidence_root))
    if args.expected_json is not None and read_regular_file_once(args.expected_json) != encoded:
        raise SystemExit("Batch-08 audit differs from expected JSON")
    if args.output is not None:
        descriptor = os.open(
            args.output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o444,
        )
        try:
            offset = 0
            while offset < len(encoded):
                written = os.write(descriptor, encoded[offset:])
                if written <= 0:
                    raise Batch08AuditError("short write publishing Batch-08 audit")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
