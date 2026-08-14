#!/usr/bin/env python3
"""Replay all three consumed Batch-14 attempts without upgrading evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

from m2c.audit_s4_v4_batch04_permission_failure import (
    _claim_core_is_valid,
    _inventory,
    canonical_sha256,
    json_object,
    read_regular_file_once,
    report_bytes,
    sha256_bytes,
)
from m2c.audit_s4_v4_batch10_collection import (
    Batch10AuditError,
    CONTAINER_IMAGE_ID,
    RUNTIME_REGISTRY_SHA256,
    URDF_SHA256,
    _git_blob,
    _require_false_boundaries,
    _validate_physical_attempt,
)
from m2c.package_path_blocked_collection import project_frozen_manifests
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import load_v4_training_manifest


ROOT = Path(__file__).resolve().parents[2]
PREREG_RELATIVE = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-14-PREREG.json")
PREREG_FILE_SHA256 = "75662ba0e97c024251ebcddd90eddb6e70f51503edc942417f32eafe68687068"
PREREG_SHA256 = "2ebf9598d0fbc135e6c314070baf9485f3c7f90fc41307ff964712d73ed1ffe5"
PREREG_COMMIT = "efb975ee36f1f270934a59d76e2c2a4f00a4e6d4"
SOURCE_SNAPSHOT_COMMIT = "04c63fa7e439a44b912af487200be9a3689d94d6"
SOURCE_SNAPSHOT_INVENTORY_SHA256 = (
    "c19df1f710bdee01dff40aa0deacea8d5ee01c3411a8910adc7c786111327dd7"
)
PREDECESSOR_RECEIPT_SHA256 = "c717e291290bd4ba43262db26ea9a480710b00bce00fbadc5849f8f290d8504b"
CLAIM_FILE_SHA256 = (
    "7143e312761e8669706e6f878f0013631843f2f5565cb4ad6327d5ee0f785ac6",
    "59cdfe5d40e67fc9f8adb16f0b04bd1ff7299160dbabafaf7b7c2168a32b6cd6",
    "0b750c7ce05d430ccf17d829fd54e4aed3172fa1a9d15cc172d8a2bdedaebaef",
)
EXPECTED_DETECTION_COUNTS = (
    (7, 7, 9, 8, 9, 12, 12, 14),
    (7, 6, 7, 7, 8, 11, 11, 11),
    (7, 13, 10, 7, 8, 9, 10, 10),
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


class Batch14AuditError(Batch10AuditError):
    """Batch-14 bytes do not prove the bounded zero-eligible outcome."""


def _validate_claim_and_job(
    *,
    root: Path,
    inventory: Mapping[str, str],
    prereg: Mapping[str, Any],
    identity: Mapping[str, Any],
    ordinal: int,
    previous_receipt_sha256: str,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    sequence = ordinal + 23
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
        claim = json_object(claim_raw, label=f"Batch-14 claim {ordinal}")
        job = json_object(read_regular_file_once(root / relative["job"]), label="Batch-14 job")
    except FileNotFoundError as error:
        raise Batch14AuditError("Batch-14 claim or job evidence is missing") from error
    if sha256_bytes(claim_raw) != CLAIM_FILE_SHA256[ordinal] or claim_raw != projected_raw:
        raise Batch14AuditError("Batch-14 canonical and projected claim bytes differ")
    if not _claim_core_is_valid(claim):
        raise Batch14AuditError("Batch-14 claim semantic receipt hash is invalid")
    if (
        claim.get("schema_version") != "M2CS4V4CollectionConsumptionReceiptV1"
        or claim.get("batch_id") != "m2c-s4-v4-train-batch-14"
        or claim.get("ledger_namespace") != "M2C_S4_V4_COLLECTION_BATCH14"
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
        raise Batch14AuditError("Batch-14 claim identity or hash chain differs")
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
        raise Batch14AuditError("Batch-14 job does not bind the consumed claim")
    if inventory.get(relative["derived_probe"]) != claim.get("derived_probe_sha256"):
        raise Batch14AuditError("Batch-14 derived probe hash differs from its claim")
    _require_false_boundaries(claim)
    _require_false_boundaries(job)
    return claim, prefix, relative


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    prereg_raw = read_regular_file_once(project_root / PREREG_RELATIVE)
    if sha256_bytes(prereg_raw) != PREREG_FILE_SHA256:
        raise Batch14AuditError("Batch-14 preregistration bytes changed")
    if (
        _git_blob(project_root=project_root, commit=PREREG_COMMIT, relative_path=PREREG_RELATIVE)
        != prereg_raw
    ):
        raise Batch14AuditError("Batch-14 preregistration differs from its introduction blob")
    prereg = json_object(prereg_raw, label="Batch-14 preregistration")
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
        raise Batch14AuditError("Batch-14 preregistration contract differs")
    inventory = _inventory(root)
    if len(inventory) != 168:
        raise Batch14AuditError("Batch-14 evidence inventory count differs")
    job_keys = {path.name for path in (root / "raw/train").iterdir() if path.is_dir()}
    if job_keys != {str(item["matched_key"]) for item in selected}:
        raise Batch14AuditError("Batch-14 evidence job set differs from selected keys")

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
            raise Batch14AuditError("Batch-14 selected identity is malformed")
        claim, prefix, relative = _validate_claim_and_job(
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
            raise Batch14AuditError("Batch-14 per-job evidence inventory count differs")
        try:
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
        except Batch10AuditError as error:
            raise Batch14AuditError(str(error)) from error
        if (
            tuple(physical["offline_dataset_exclusion_reasons"])
            != EXPECTED_DATASET_EXCLUSIONS[ordinal]
        ):
            raise Batch14AuditError("Batch-14 offline dataset exclusion reasons differ")
        raw_probe = json_object(
            read_regular_file_once(root / relative["raw_probe"]), label="Batch-14 raw probe"
        )
        current_receipt_ids = {
            str(step["physical_receipts"][0]["receipt_id"])
            for step in raw_probe["m2c_path_blocked_physical_chain"]["steps"]
        }
        if all_receipt_ids & current_receipt_ids:
            raise Batch14AuditError("Batch-14 physical receipt ID is reused")
        all_receipt_ids.update(current_receipt_ids)
        attempts.append(
            {
                "attempt_id": f"batch14-{ordinal + 1:02d}",
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
    if (root / "packaged").exists() and any((root / "packaged").rglob("*")):
        raise Batch14AuditError("Batch-14 evidence contains packaged output")

    audit_path = Path(__file__).resolve()
    helper_path = project_root / "scripts/m2c/audit_s4_v4_batch10_collection.py"
    return {
        "schema_version": "M2CS4V4Batch14CollectionAuditV1",
        "status": "BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH14",
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
            "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
        },
        "audit_implementation": {
            "path": "scripts/m2c/audit_s4_v4_batch14_collection.py",
            "sha256": sha256_bytes(read_regular_file_once(audit_path)),
            "physical_replay_helper_path": "scripts/m2c/audit_s4_v4_batch10_collection.py",
            "physical_replay_helper_sha256": sha256_bytes(read_regular_file_once(helper_path)),
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_executed": False,
        "model_rollout_executed": False,
        "formal_q_b_evaluation_executed": False,
        "pure_model_success_episodes": None,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    return f"""# M2C S4 V4 Batch-14 collection audit

Status: `{report["status"]}`

The three outcome-blind preregistered TRAIN keys were consumed exactly once, with no retry or
replacement. All three completed strict eight-step V4 physical chains. Scene 19227 ended at the
unchanged REGRASP pregrasp-IK gate; scenes 19229 and 19231 ended at the unchanged REGRASP
contact gate. Host replay accepted all raw chains under the ADR-0025 32-detection schema and
produced `EMPTY` datasets.

## Observed outcomes

- scene 19227: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- scene 19229: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 19231: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`; offline replay also
  records `STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch14_collection.py \\
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch14-complete \\
  --expected-json reports/m2c-s4-v4-batch14-collection.json
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
        raise SystemExit("Batch-14 audit differs from expected JSON")
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
