#!/usr/bin/env python3
"""Replay Batch-07 ordinal zero's pre-timeline proprioception failure."""

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
PREREG_RELATIVE = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-07-PREREG.json")
PREREG_FILE_SHA256 = "37dd546506cd34acffec373f2f3c806eb6a2796a0accbd236cdb2b26f703f7c6"
PREREG_COMMIT = "2d408efb8ca4ed36f83126841f26aa01bff9efe6"
FIX_COMMIT = "075e94e5408906b07778bb9fa78b4a346f95bd3f"
FIX_SOURCE_SHA256 = "5304dc7d675e0e7220953f927ae83ca994394ddccb6fe2eb35646f1121a235b0"
FAILURE_MESSAGE = (
    "Instance's physics tensor entity is not valid. "
    "Play the simulation/timeline to re-initialize it"
)


class Batch07AuditError(Batch04AuditError):
    """Batch-07 bytes do not prove the bounded pre-timeline failure."""


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    prereg_raw = read_regular_file_once(project_root / PREREG_RELATIVE)
    if sha256_bytes(prereg_raw) != PREREG_FILE_SHA256:
        raise Batch07AuditError("Batch-07 preregistration bytes changed")
    prereg = json_object(prereg_raw, label="Batch-07 preregistration")
    selected = prereg.get("selected_keys")
    if not isinstance(selected, list) or len(selected) != 3 or not isinstance(selected[0], dict):
        raise Batch07AuditError("Batch-07 selected-key contract is malformed")
    identity = selected[0]
    key = str(identity["matched_key"])
    prefix = f"raw/train/{key}"
    paths = {
        "canonical_claim": "ledger/claim-00000004.json",
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
        claim = json_object(claim_raw, label="Batch-07 claim")
        job = json_object(read_regular_file_once(root / paths["job"]), label="Batch-07 job")
        metrics = json_object(
            read_regular_file_once(root / paths["stage_metrics"]),
            label="Batch-07 stage metrics",
        )
        derived = read_regular_file_once(root / paths["derived"]).decode("utf-8")
        probe_console = read_regular_file_once(root / paths["probe_console"]).decode("utf-8")
    except FileNotFoundError as error:
        raise Batch07AuditError("Batch-07 evidence file is missing") from error
    if claim_raw != projected_raw or not _claim_core_is_valid(claim):
        raise Batch07AuditError("projected claim is not the canonical semantic claim")
    if (
        claim.get("schema_version") != "M2CS4V4CollectionConsumptionReceiptV1"
        or claim.get("batch_id") != "m2c-s4-v4-train-batch-07"
        or claim.get("ledger_sequence") != 4
        or claim.get("ordinal") != 0
        or claim.get("selected_key") != identity
        or claim.get("event") != "CONSUMED_BEFORE_STAGE"
    ):
        raise Batch07AuditError("Batch-07 claim identity is invalid")
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
        raise Batch07AuditError("Batch-07 job does not bind the consumed claim")
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
        raise Batch07AuditError("Batch-07 stage is not an exact accepted non-rollout stage")
    pre_timeline_sequence = (
        "    simulation_app.update()\n"
        "    _m2c_v4_record_proprioception_sample()\n"
        "    omni.timeline.get_timeline_interface().play()\n"
    )
    if derived.count(pre_timeline_sequence) != 1:
        raise Batch07AuditError("derived probe does not prove the pre-timeline call order")
    if (
        probe_console.count(f'"message": "{FAILURE_MESSAGE}"') != 1
        or probe_console.count("_m2c_v4_record_proprioception_sample()") < 1
        or "Simulation App Starting" not in probe_console
    ):
        raise Batch07AuditError("probe console is not the exact tensor-validity failure")
    probe_root = root / prefix / "probe"
    if {member.relative_to(probe_root).as_posix() for member in probe_root.rglob("*")} != {
        "console.log",
        "m2b_public_rgbd",
        "m2b_public_rgbd/depth",
        "m2b_public_rgbd/rgb",
    } or {member.name for member in probe_root.rglob("*") if member.is_file()} != {"console.log"}:
        raise Batch07AuditError("Batch-07 probe emitted evidence beyond empty capture directories")
    if any(path.name == "actuation-probe.json" for path in root.rglob("*")):
        raise Batch07AuditError("Batch-07 unexpectedly emitted a physical probe receipt")
    fixed_path = "scripts/m2c/derive_model_owned_chain_probe.py"
    fixed_source = subprocess.run(
        ["git", "-C", str(project_root), "show", f"{FIX_COMMIT}:{fixed_path}"],
        check=True,
        capture_output=True,
    ).stdout
    if sha256_bytes(fixed_source) != FIX_SOURCE_SHA256:
        raise Batch07AuditError("pre-timeline recorder fix bytes are not frozen")
    audit_path = Path(__file__).resolve()
    return {
        "schema_version": "M2CS4V4Batch07PreTimelineProprioFailureAuditV1",
        "status": "BLOCKED_PRE_TIMELINE_PROPRIOCEPTION_READ",
        "batch_preregistration": {
            "path": PREREG_RELATIVE.as_posix(),
            "sha256": PREREG_FILE_SHA256,
            "introduced_commit": PREREG_COMMIT,
            "prereg_sha256": prereg["prereg_sha256"],
        },
        "attempts": [
            {
                "attempt_id": "batch07-01",
                "identity": identity,
                "classification": "PRE_TIMELINE_PHYSICS_TENSOR_READ",
                "consumption_id": claim["consumption_id"],
                "consumed_at_ns": claim["consumed_at_ns"],
                "stage_acceptance_passed": True,
                "stage_simulation_app_started": True,
                "probe_process_invoked": True,
                "probe_simulation_app_started": True,
                "probe_timeline_started": False,
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
            "probe_simulation_app_starts": 1,
            "probe_timeline_starts": 0,
            "physical_actions": 0,
            "training_samples_eligible": 0,
            "training_samples_packaged": 0,
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
        },
        "root_cause": {
            "classification": "PUBLIC_PROPRIOCEPTION_QUERIED_BEFORE_PHYSICS_TENSOR_VALID",
            "failure": FAILURE_MESSAGE,
            "failed_call_precedes_timeline_play": True,
            "actuation_receipt_emitted": False,
        },
        "fix": {
            "commit": FIX_COMMIT,
            "path": fixed_path,
            "sha256": FIX_SOURCE_SHA256,
            "failed_key_retried": False,
        },
        "audit_implementation": {
            "path": "scripts/m2c/audit_s4_v4_batch07_pre_timeline_proprio_failure.py",
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
        raise SystemExit("Batch-07 audit differs from expected JSON")
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
                    raise Batch07AuditError("short write publishing Batch-07 audit")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
