#!/usr/bin/env python3
"""Replay the consumed Batch-04 V4 permission-failure evidence.

This auditor records an infrastructure failure before probe launch.  It never
upgrades the attempts into physical evidence or training samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PREREG_RELATIVE = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-04-PREREG.json")
PREREG_FILE_SHA256 = "38af63f0b9b5db7ff47b44f04fded448c912fc9a99391be8042c1597e25ebed7"
PREREG_COMMIT = "2d00f9148eb3bbb96c169e4604835a8bf1aff0c7"
PERMISSION_FAILURE = (
    "M1B_ISAAC_DATASET_FAIL PermissionError: [Errno 13] Permission denied: "
    "'/workspace/output/policy_rgbd/rgb'"
)
PERMISSION_FIX_COMMIT = "f4f135aec11dc9131db1c030889ee35560f8f876"


class Batch04AuditError(RuntimeError):
    """Batch-04 bytes do not prove the bounded infrastructure failure."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise Batch04AuditError(f"evidence is not a single regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise Batch04AuditError(f"evidence changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Batch04AuditError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise Batch04AuditError(f"{label} is not an object")
    return value


def _inventory(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for member in sorted(root.rglob("*")):
        info = member.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise Batch04AuditError("evidence tree contains a symlink")
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise Batch04AuditError("evidence tree contains a multiply-linked file")
            relative = member.relative_to(root).as_posix()
            result[relative] = sha256_bytes(read_regular_file_once(member))
        elif not stat.S_ISDIR(info.st_mode):
            raise Batch04AuditError("evidence tree contains a special file")
    return result


def _claim_core_is_valid(claim: dict[str, Any]) -> bool:
    core = dict(claim)
    claimed = core.pop("receipt_sha256", None)
    return isinstance(claimed, str) and canonical_sha256(core) == claimed


def _permission_failure_count(console: bytes) -> int:
    return console.decode("utf-8", errors="strict").count(PERMISSION_FAILURE)


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    evidence_root = evidence_root.resolve(strict=True)
    prereg_path = project_root / PREREG_RELATIVE
    prereg_raw = read_regular_file_once(prereg_path)
    if sha256_bytes(prereg_raw) != PREREG_FILE_SHA256:
        raise Batch04AuditError("Batch-04 preregistration bytes changed")
    prereg = json_object(prereg_raw, label="Batch-04 preregistration")
    selected = prereg.get("selected_keys")
    if not isinstance(selected, list) or len(selected) != 3:
        raise Batch04AuditError("Batch-04 preregistration does not select exactly three keys")

    inventory = _inventory(evidence_root)
    expected_files: set[str] = set()
    attempts: list[dict[str, Any]] = []
    previous_receipt: str | None = None
    for ordinal, identity in enumerate(selected):
        if not isinstance(identity, dict):
            raise Batch04AuditError("selected Batch-04 identity is malformed")
        key = str(identity["matched_key"])
        claim_relative = f"ledger/claim-{ordinal:08d}.json"
        job_prefix = f"raw/train/{key}"
        job_relative = f"{job_prefix}/collection-job-v4.json"
        derived_relative = f"{job_prefix}/derived-path-blocked-probe.py"
        console_relative = f"{job_prefix}/stage/console.log"
        expected_files.update({claim_relative, job_relative, derived_relative, console_relative})
        try:
            claim = json_object(
                read_regular_file_once(evidence_root / claim_relative),
                label=f"claim {ordinal}",
            )
            job = json_object(
                read_regular_file_once(evidence_root / job_relative),
                label=f"job {ordinal}",
            )
            console = read_regular_file_once(evidence_root / console_relative)
        except FileNotFoundError as error:
            raise Batch04AuditError("Batch-04 evidence file is missing") from error
        if not _claim_core_is_valid(claim):
            raise Batch04AuditError("claim semantic receipt hash is invalid")
        if (
            claim.get("schema_version") != "M2CS4V4CollectionConsumptionReceiptV1"
            or claim.get("batch_id") != "m2c-s4-v4-train-batch-04"
            or claim.get("ledger_sequence") != ordinal
            or claim.get("ordinal") != ordinal
            or claim.get("selected_key") != identity
            or claim.get("previous_receipt_sha256") != previous_receipt
            or claim.get("event") != "CONSUMED_BEFORE_STAGE"
        ):
            raise Batch04AuditError("claim identity or hash chain is invalid")
        previous_receipt = str(claim["receipt_sha256"])
        authorization = job.get("collection_authorization")
        if (
            job.get("schema_version") != "M2CPathBlockedCollectionJobV4"
            or job.get("status") != "PREPARED_NOT_EXECUTED"
            or job.get("matched_key") != key
            or int(job.get("scene_seed", -1)) != int(identity["scene_seed"])
            or int(job.get("failure_seed", -1)) != int(identity["failure_seed"])
            or not isinstance(authorization, dict)
            or authorization.get("consumption_id") != claim.get("consumption_id")
            or authorization.get("consumption_receipt_sha256") != claim.get("receipt_sha256")
            or job.get("teacher_used") is not False
            or job.get("privileged_truth_policy_input") is not False
            or job.get("training_executed") is not False
            or job.get("evaluation_executed") is not False
        ):
            raise Batch04AuditError("job receipt does not bind the consumed claim")
        if inventory[derived_relative] != claim.get("derived_probe_sha256"):
            raise Batch04AuditError("derived probe does not bind the consumed claim")
        probe_directory = evidence_root / job_prefix / "probe"
        if not probe_directory.is_dir() or any(probe_directory.iterdir()):
            raise Batch04AuditError("Batch-04 probe directory is not empty")
        if _permission_failure_count(console) != 1:
            raise Batch04AuditError("stage console lacks the exact permission failure")
        attempts.append(
            {
                "attempt_id": f"batch04-{ordinal + 1:02d}",
                "identity": identity,
                "classification": "PRE_KIT_STAGE_OUTPUT_PERMISSION_FAILURE",
                "consumption_id": claim["consumption_id"],
                "consumed_at_ns": claim["consumed_at_ns"],
                "evidence_file_sha256": {
                    relative: inventory[relative]
                    for relative in sorted(
                        {claim_relative, job_relative, derived_relative, console_relative}
                    )
                },
                "probe_launched": False,
                "physical_action_executed": False,
                "training_sample_eligible": False,
                "training_sample_packaged": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "model_rollout": False,
                "formal_q_b_evaluation": False,
            }
        )
    if set(inventory) != expected_files:
        raise Batch04AuditError("Batch-04 evidence inventory is not exact")
    audit_path = Path(__file__).resolve()
    worker_path = project_root / "scripts/m2c/run_path_blocked_collection_worker.py"
    return {
        "schema_version": "M2CS4V4Batch04InfrastructureFailureAuditV1",
        "status": "BLOCKED_PRE_KIT_STAGE_OUTPUT_PERMISSION_FAILURE",
        "batch_preregistration": {
            "path": PREREG_RELATIVE.as_posix(),
            "sha256": PREREG_FILE_SHA256,
            "introduced_commit": PREREG_COMMIT,
            "prereg_sha256": prereg["prereg_sha256"],
        },
        "attempts": attempts,
        "observed_counts": {
            "consumed_unique_train_keys": 3,
            "stage_builder_invocations": 3,
            "stage_permission_failures": 3,
            "probe_launches": 0,
            "physical_actions": 0,
            "training_samples_eligible": 0,
            "training_samples_packaged": 0,
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
        },
        "root_cause": {
            "classification": "HOST_OUTPUT_DIRECTORY_OWNED_BY_ROOT_MODE_0700",
            "frozen_image_runtime_user": "isaac-sim",
            "frozen_image_runtime_uid": 1234,
            "frozen_image_runtime_gid": 1234,
            "exact_failure": PERMISSION_FAILURE,
        },
        "permission_fix": {
            "commit": PERMISSION_FIX_COMMIT,
            "worker_path": "scripts/m2c/run_path_blocked_collection_worker.py",
            "worker_sha256": sha256_bytes(read_regular_file_once(worker_path)),
            "batch04_retried": False,
            "replacement_authorized": False,
        },
        "audit_implementation": {
            "path": "scripts/m2c/audit_s4_v4_batch04_permission_failure.py",
            "sha256": sha256_bytes(read_regular_file_once(audit_path)),
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_executed": False,
        "formal_q_b_evaluation_executed": False,
        "pure_model_success_episodes": None,
    }


def report_bytes(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    encoded = report_bytes(build_report(evidence_root=args.evidence_root))
    if args.expected_json is not None:
        if read_regular_file_once(args.expected_json) != encoded:
            raise SystemExit("Batch-04 audit differs from expected JSON")
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
        return 0
    print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
