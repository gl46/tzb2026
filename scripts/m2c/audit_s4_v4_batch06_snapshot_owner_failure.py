#!/usr/bin/env python3
"""Replay the single consumed Batch-06 pre-Kit snapshot-owner failure."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
from typing import Any

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


ROOT = Path(__file__).resolve().parents[2]
PREREG_RELATIVE = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-06-PREREG.json")
PREREG_FILE_SHA256 = "72c022add19327ce886cd4996b69748711eee6f8202a68e120abdb4baefea600"
PREREG_COMMIT = "d4a69834baada1807f1831f5c1866378df732b06"
FIX_COMMIT = "e69819bd10c782067b5ad4ca7ae2a201f8e0e201"
FIX_SOURCE_SHA256 = "dd9ff4d9d29f6ca3917b8048e4f506064b304b9ad177e8a7210444a48a7bbb6c"
FAILURE_SUFFIX = (
    "xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1."
    "CollectionAuthorizationError: source snapshot root is not a real directory"
)


class Batch06AuditError(Batch04AuditError):
    """Batch-06 bytes do not prove the bounded pre-Kit failure."""


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    prereg_raw = read_regular_file_once(project_root / PREREG_RELATIVE)
    if sha256_bytes(prereg_raw) != PREREG_FILE_SHA256:
        raise Batch06AuditError("Batch-06 preregistration bytes changed")
    prereg = json_object(prereg_raw, label="Batch-06 preregistration")
    selected = prereg.get("selected_keys")
    if not isinstance(selected, list) or len(selected) != 3 or not isinstance(selected[0], dict):
        raise Batch06AuditError("Batch-06 selected-key contract is malformed")
    identity = selected[0]
    key = str(identity["matched_key"])
    prefix = f"raw/train/{key}"
    paths = {
        "canonical_claim": "ledger/claim-00000003.json",
        "projected_claim": f"{prefix}/authorization/collection-claim-v4.json",
        "job": f"{prefix}/collection-job-v4.json",
        "derived": f"{prefix}/derived-path-blocked-probe.py",
        "probe_console": f"{prefix}/probe/console.log",
        "stage_console": f"{prefix}/stage/console.log",
        "stage_metrics": f"{prefix}/stage/metrics.json",
    }
    inventory = _inventory(root)
    try:
        claim_raw = read_regular_file_once(root / paths["canonical_claim"])
        projected_raw = read_regular_file_once(root / paths["projected_claim"])
        claim = json_object(claim_raw, label="Batch-06 claim")
        job = json_object(read_regular_file_once(root / paths["job"]), label="Batch-06 job")
        metrics = json_object(
            read_regular_file_once(root / paths["stage_metrics"]),
            label="Batch-06 stage metrics",
        )
        derived = read_regular_file_once(root / paths["derived"]).decode("utf-8")
        probe_console = read_regular_file_once(root / paths["probe_console"]).decode("utf-8")
    except FileNotFoundError as error:
        raise Batch06AuditError("Batch-06 evidence file is missing") from error
    if claim_raw != projected_raw or not _claim_core_is_valid(claim):
        raise Batch06AuditError("projected claim is not the canonical semantic claim")
    if (
        claim.get("schema_version") != "M2CS4V4CollectionConsumptionReceiptV1"
        or claim.get("batch_id") != "m2c-s4-v4-train-batch-06"
        or claim.get("ledger_sequence") != 3
        or claim.get("ordinal") != 0
        or claim.get("selected_key") != identity
        or claim.get("event") != "CONSUMED_BEFORE_STAGE"
    ):
        raise Batch06AuditError("Batch-06 claim identity is invalid")
    authorization = job.get("collection_authorization")
    if (
        job.get("schema_version") != "M2CPathBlockedCollectionJobV4"
        or job.get("matched_key") != key
        or not isinstance(authorization, dict)
        or authorization.get("consumption_id") != claim.get("consumption_id")
        or authorization.get("consumption_receipt_sha256") != claim.get("receipt_sha256")
        or authorization.get("container_claim_projection_sha256") != sha256_bytes(projected_raw)
        or job.get("teacher_used") is not False
        or job.get("privileged_truth_policy_input") is not False
        or job.get("training_executed") is not False
        or job.get("evaluation_executed") is not False
    ):
        raise Batch06AuditError("Batch-06 job does not bind the consumed claim")
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
        raise Batch06AuditError("Batch-06 stage is not an exact accepted non-rollout stage")
    binding_index = derived.find("M2C_V4_COLLECTION_AUTHORIZATION =")
    kit_index = derived.find("from isaacsim import SimulationApp")
    if binding_index < 0 or kit_index < 0 or binding_index >= kit_index:
        raise Batch06AuditError("derived probe does not place authorization before Kit")
    if probe_console.count(FAILURE_SUFFIX) != 1 or "Simulation App Starting" in probe_console:
        raise Batch06AuditError("probe console is not the exact pre-Kit owner failure")
    probe_root = root / prefix / "probe"
    if {member.name for member in probe_root.iterdir()} != {"console.log"}:
        raise Batch06AuditError("Batch-06 probe emitted evidence beyond its pre-Kit console")
    if any(path.name == "actuation-probe.json" for path in root.rglob("*")):
        raise Batch06AuditError("Batch-06 unexpectedly emitted a physical probe receipt")
    audit_path = Path(__file__).resolve()
    fixed_path = "src/xh_agent/policy/qrm_lite/s4_v4_collection_authorization_v1.py"
    fixed_source = subprocess.run(
        ["git", "-C", str(project_root), "show", f"{FIX_COMMIT}:{fixed_path}"],
        check=True,
        capture_output=True,
    ).stdout
    if sha256_bytes(fixed_source) != FIX_SOURCE_SHA256:
        raise Batch06AuditError("snapshot-owner fix commit bytes are not frozen")
    return {
        "schema_version": "M2CS4V4Batch06SnapshotOwnerFailureAuditV1",
        "status": "BLOCKED_PRE_KIT_SOURCE_SNAPSHOT_OWNER_FALSE_REJECTION",
        "batch_preregistration": {
            "path": PREREG_RELATIVE.as_posix(),
            "sha256": PREREG_FILE_SHA256,
            "introduced_commit": PREREG_COMMIT,
            "prereg_sha256": prereg["prereg_sha256"],
        },
        "attempts": [
            {
                "attempt_id": "batch06-01",
                "identity": identity,
                "classification": "PRE_KIT_SOURCE_SNAPSHOT_OWNER_FALSE_REJECTION",
                "consumption_id": claim["consumption_id"],
                "consumed_at_ns": claim["consumed_at_ns"],
                "stage_acceptance_passed": True,
                "stage_simulation_app_started": True,
                "probe_process_invoked": True,
                "probe_simulation_app_started": False,
                "physical_action_executed": False,
                "training_sample_eligible": False,
                "training_sample_packaged": False,
                "evidence_file_sha256": {
                    label: inventory[relative] for label, relative in sorted(paths.items())
                },
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "model_rollout": False,
                "formal_q_b_evaluation": False,
            }
        ],
        "observed_counts": {
            "consumed_unique_train_keys": 1,
            "stage_acceptance_passes": 1,
            "stage_simulation_app_starts": 1,
            "probe_process_invocations": 1,
            "probe_simulation_app_starts": 0,
            "physical_actions": 0,
            "training_samples_eligible": 0,
            "training_samples_packaged": 0,
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
        },
        "root_cause": {
            "classification": "ROOT_OWNED_READ_ONLY_SNAPSHOT_REJECTED_BY_CONTAINER_UID_CHECK",
            "frozen_image_runtime_uid": 1234,
            "host_snapshot_owner_uid": 0,
            "snapshot_directory_mode": "0555",
            "snapshot_file_modes": ["0444", "0555"],
            "failure": FAILURE_SUFFIX,
        },
        "fix": {
            "commit": FIX_COMMIT,
            "path": fixed_path,
            "sha256": FIX_SOURCE_SHA256,
            "failed_key_retried": False,
        },
        "audit_implementation": {
            "path": "scripts/m2c/audit_s4_v4_batch06_snapshot_owner_failure.py",
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
        raise SystemExit("Batch-06 audit differs from expected JSON")
    if args.output is not None:
        descriptor = os.open(
            args.output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o444,
        )
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
