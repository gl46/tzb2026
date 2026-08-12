#!/usr/bin/env python3
"""Merge frozen M2B records with accepted S3 evidence and enforce full coverage."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any

from m2b.build_dataset_v2 import (
    code_revision_histogram,
    package,
    remote_json,
    remote_sha256,
)
from m2b.run_physical_failure_smoke import (
    PHYSICAL_SMOKE_SOURCE_SHA256,
    accepted as strict_smoke_accepted,
)
from m2c.build_headroom_domain import DATASET_VERSION, PROJECT, sha256_file
from m2c.freeze_s3_evidence import DEFAULT_REMOTE_ROOT, LEDGER_NAME
from xh_agent.data_engine.isaac.failure_rich import (
    validate_failure_recovery_episode,
)


MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
EXPECTED_NEW_ACCEPTED_PER_FAILURE = 50
FROZEN_PHYSICAL_RUNNER = "scripts/m2b/run_physical_failure_smoke.py"
FROZEN_PHYSICAL_RUNNER_SHA256 = (
    "7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865"
)
REQUIRED_COLLISION_GATE_PATHS = {
    "EMPTY_GRASP": {
        "$.phases.detach_retreat.collision_gate",
        "$.phases.lift.collision_gate",
    },
    "WRONG_OBJECT": {
        "$.m2b_recovery.wrong_object.regrasp_execution.lift_motion.collision_gate",
        "$.m2b_recovery.wrong_object.regrasp_execution.pregrasp_motion.collision_gate",
        "$.phases.detach_retreat.collision_gate",
        "$.phases.lift.collision_gate",
    },
    "RELEASE_FAILURE": {
        "$.m2b_release_failure_injection.follow_motion.collision_gate",
        "$.phases.detach_retreat.collision_gate",
        "$.phases.lift.collision_gate",
    },
}
INJECTION_KEY = {
    "EMPTY_GRASP": "m2b_empty_grasp_injection",
    "WRONG_OBJECT": "m2b_wrong_object_injection",
    "RELEASE_FAILURE": "m2b_release_failure_injection",
}
RECOVERY_PUBLIC_PREDICATE_KEY = {
    "EMPTY_GRASP": "public_final_predicates",
    "WRONG_OBJECT": "public_regrasp_predicates",
    "RELEASE_FAILURE": "public_final_predicates",
}
FULL_FAILURE_MINIMUM = 100
FULL_RECOVERY_MINIMUM = 50
BASE_DATASET = PROJECT / "artifacts/m2b/dataset-v2.jsonl"
BASE_DATASET_SHA256 = "c24e34493ba2226c1aa691c1b1c43993fbecdff5ad74b291e08c4913efc71362"
DEFAULT_PLAN = PROJECT / "configs/m2c_s3_collection_plan.json"
DEFAULT_FREEZE_REPORT = PROJECT / "reports/m2c-s3-evidence-freeze.json"
DEFAULT_REPORT_MD = PROJECT / "reports/m2c-s3-dataset-v3.md"


def load_stable_worker_status(
    host: str,
    path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one worker status and bind the exact stable remote bytes."""
    digest_before = remote_sha256(host, path)
    status = remote_json(host, path)
    digest_after = remote_sha256(host, path)
    if digest_before != digest_after:
        raise ValueError(f"S3 worker status changed while being read: {path}")
    if len(digest_after) != 64:
        raise ValueError(f"S3 worker status SHA-256 is malformed: {path}")
    snapshot = {
        "host": host,
        "path": path,
        "sha256": digest_after,
        "schema_version": status.get("schema_version"),
        "status": status.get("status"),
        "accepted_counts": status.get("accepted_counts", {}),
        "record_count": len(status.get("records", [])),
        "teacher_used": status.get("teacher_used"),
        "privileged_truth_policy_input": status.get("privileged_truth_policy_input"),
    }
    return status, snapshot


def validate_evidence_freeze(
    path: Path,
    *,
    host: str,
    worker_status_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    freeze = json.loads(path.read_text(encoding="utf-8"))
    if freeze.get("schema_version") != "M2CS3EvidenceFreezeV1":
        raise ValueError("unsupported S3 evidence-freeze report")
    if freeze.get("status") != "PASS" or freeze.get("evidence_tree_readonly") is not True:
        raise ValueError("S3 evidence tree is not frozen read-only")
    if freeze.get("host") != host:
        raise ValueError("S3 evidence-freeze host does not match packaging host")
    if freeze.get("remote_root") != str(DEFAULT_REMOTE_ROOT):
        raise ValueError("S3 evidence-freeze root does not match frozen S3 root")
    if freeze.get("ledger") != str(DEFAULT_REMOTE_ROOT / LEDGER_NAME):
        raise ValueError("S3 evidence-freeze ledger path is unexpected")
    if freeze.get("teacher_used") is not False:
        raise ValueError("S3 evidence freeze is not explicitly Teacher-free")
    if freeze.get("privileged_truth_policy_input") is not False:
        raise ValueError("S3 evidence freeze used privileged truth as policy input")
    ledger_digest = str(freeze.get("ledger_sha256", ""))
    if len(ledger_digest) != 64:
        raise ValueError("S3 evidence-freeze ledger SHA-256 is malformed")
    if int(freeze.get("files_hashed", 0)) <= 0:
        raise ValueError("S3 evidence-freeze file inventory is empty")

    frozen_by_path = {
        str(item.get("path")): item for item in freeze.get("worker_status_snapshots", [])
    }
    current_by_path = {str(item.get("path")): item for item in worker_status_snapshots}
    if set(frozen_by_path) != set(current_by_path):
        raise ValueError("S3 frozen/current worker-status path sets differ")
    for status_path, current in current_by_path.items():
        frozen = frozen_by_path[status_path]
        for field in (
            "sha256",
            "status",
            "accepted_counts",
            "record_count",
            "teacher_used",
            "privileged_truth_policy_input",
        ):
            if frozen.get(field) != current.get(field):
                raise ValueError(
                    f"S3 frozen/current worker status differs at {status_path}: {field}"
                )
    return {
        "report_path": str(path),
        "report_sha256": sha256_file(path),
        "host": host,
        "remote_root": freeze.get("remote_root"),
        "ledger": freeze.get("ledger"),
        "ledger_sha256": ledger_digest,
        "files_hashed": int(freeze.get("files_hashed", 0)),
        "evidence_tree_readonly": True,
    }


def verify_remote_evidence_ledger(host: str, freeze: dict[str, Any]) -> None:
    ledger = str(freeze["ledger"])
    expected_ledger_sha256 = str(freeze["ledger_sha256"])
    if remote_sha256(host, ledger) != expected_ledger_sha256:
        raise ValueError("remote S3 evidence ledger SHA-256 changed after freeze")
    root = str(freeze["remote_root"])
    command = (
        f"cd {shlex.quote(root)} && sha256sum --check --strict {shlex.quote(Path(ledger).name)}"
    )
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, command],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"remote S3 evidence ledger verification failed: {detail}")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def accepted_evidence(
    statuses: list[dict[str, Any]],
) -> tuple[list[tuple[str, str]], list[dict[str, object]]]:
    evidence = []
    rejected = []
    for status in statuses:
        if status.get("teacher_used") is not False:
            raise ValueError("S3 worker status is not explicitly Teacher-free")
        if status.get("privileged_truth_policy_input") is not False:
            raise ValueError("S3 worker status used privileged policy input")
        for record in status.get("records", []):
            failure = record.get("failure_type")
            if failure is None:
                rejected.append(
                    {
                        "scene_seed": record.get("scene_seed"),
                        "failure_type": None,
                        "status": record.get("status", "UNKNOWN"),
                        "reason": "source or stage did not reach a failure attempt",
                    }
                )
                continue
            if failure not in MANDATORY_FAILURES:
                raise ValueError(f"unsupported S3 failure type: {failure}")
            if record.get("accepted") is True and record.get("evidence"):
                evidence.append((str(failure), str(record["evidence"])))
            else:
                rejected.append(
                    {
                        "scene_seed": record.get("scene_seed"),
                        "failure_type": failure,
                        "status": record.get("status", "UNKNOWN"),
                        "reason": ("frozen physical/public acceptance predicate did not pass"),
                    }
                )
    return evidence, rejected


def validate_frozen_acceptance_predicate(plan: dict[str, Any]) -> dict[str, Any]:
    """Bind the re-audit to the exact predicate source used for S3 collection."""
    runtime = plan.get("frozen_collection_runtime")
    if not isinstance(runtime, dict):
        raise ValueError("S3 plan lacks frozen collection runtime")
    if runtime.get("physical_runner") != FROZEN_PHYSICAL_RUNNER:
        raise ValueError("S3 physical acceptance predicate path changed")
    if runtime.get("physical_runner_sha256") != FROZEN_PHYSICAL_RUNNER_SHA256:
        raise ValueError("S3 plan physical acceptance predicate SHA-256 changed")
    runner = PROJECT / FROZEN_PHYSICAL_RUNNER
    actual = sha256_file(runner)
    if actual != FROZEN_PHYSICAL_RUNNER_SHA256:
        raise ValueError("local S3 physical acceptance predicate source changed")
    if PHYSICAL_SMOKE_SOURCE_SHA256 != FROZEN_PHYSICAL_RUNNER_SHA256:
        raise ValueError("imported S3 physical acceptance predicate source changed")
    return {
        "path": FROZEN_PHYSICAL_RUNNER,
        "sha256": FROZEN_PHYSICAL_RUNNER_SHA256,
        "public_rgbd_required": True,
        "predicate": "m2b.run_physical_failure_smoke.accepted",
    }


def _walk_objects(value: object, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    objects: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        objects.append((path, value))
        for key, child in value.items():
            objects.extend(_walk_objects(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            objects.extend(_walk_objects(child, f"{path}[{index}]"))
    return objects


def _validate_public_predicate_result(
    predicate: object,
    *,
    location: str,
) -> None:
    if not isinstance(predicate, dict):
        raise ValueError(f"missing public predicate result at {location}")
    if predicate.get("schema_version") != "PublicFailurePredicateResultV2":
        raise ValueError(f"unsupported public predicate schema at {location}")
    if predicate.get("simulator_truth_used") is not False:
        raise ValueError(f"simulator truth entered public predicate at {location}")
    if not str(predicate.get("source", "")).startswith("PUBLIC_"):
        raise ValueError(f"non-public predicate source at {location}")
    if not predicate.get("predicates"):
        raise ValueError(f"empty public predicate result at {location}")


def audit_accepted_payload(
    payload: dict[str, Any],
    *,
    failure: str,
    evidence_path: str,
    declared_sha256: str,
    actual_sha256: str,
    scene_seed: int,
) -> dict[str, Any]:
    """Re-run the frozen physical/public acceptance boundary for one record."""
    if failure not in MANDATORY_FAILURES:
        raise ValueError(f"unsupported accepted failure type: {failure}")
    if declared_sha256 != actual_sha256 or len(actual_sha256) != 64:
        raise ValueError(f"accepted evidence SHA-256 mismatch: {evidence_path}")
    if int(payload.get("scene_seed", -1)) != scene_seed:
        raise ValueError(f"accepted evidence scene seed mismatch: {evidence_path}")
    if not strict_smoke_accepted(payload, failure, public_rgbd_required=True):
        raise ValueError(f"strict physical/public predicate failed: {evidence_path}")

    objects = _walk_objects(payload)
    teacher_true = [
        path
        for path, item in objects
        if item.get("teacher_used") is True
        or ("teacher_response" in item and item.get("teacher_response") is not None)
    ]
    if teacher_true:
        raise ValueError(f"Teacher boundary violation at {teacher_true[0]}")
    policy_truth_true = [
        path
        for path, item in objects
        if item.get("privileged_truth_policy_input") is True
        or item.get("simulator_truth_policy_input") is True
        or item.get("policy_input_simulator_truth") is True
    ]
    if policy_truth_true:
        raise ValueError(f"privileged truth policy-input violation at {policy_truth_true[0]}")

    public_rgbd = payload.get("m2b_public_rgbd")
    if not isinstance(public_rgbd, dict):
        raise ValueError(f"missing public RGB-D evidence: {evidence_path}")
    if public_rgbd.get("schema_version") != "M2BPublicRGBDEvidenceV2":
        raise ValueError(f"unsupported public RGB-D schema: {evidence_path}")
    if public_rgbd.get("simulator_truth_policy_input") is not False:
        raise ValueError(f"public RGB-D used simulator truth: {evidence_path}")
    task_spec = public_rgbd.get("task_spec")
    if not isinstance(task_spec, dict) or not str(task_spec.get("target_track_id", "")).startswith(
        "track-"
    ):
        raise ValueError(f"public TaskSpec target track is missing: {evidence_path}")

    injection = payload.get(INJECTION_KEY[failure])
    recovery = (payload.get("m2b_recovery") or {}).get(failure.lower())
    if not isinstance(injection, dict) or not isinstance(recovery, dict):
        raise ValueError(f"failure/recovery payload is missing: {evidence_path}")
    _validate_public_predicate_result(
        injection.get("public_predicates"),
        location=f"{evidence_path}:{INJECTION_KEY[failure]}.public_predicates",
    )
    recovery_predicate_key = RECOVERY_PUBLIC_PREDICATE_KEY[failure]
    _validate_public_predicate_result(
        recovery.get(recovery_predicate_key),
        location=f"{evidence_path}:m2b_recovery.{failure.lower()}.{recovery_predicate_key}",
    )

    protocol = payload.get("action_protocol")
    protocol_fields = ("frame", "units", "dimensions", "frequency_hz", "normalization")
    if not isinstance(protocol, dict) or any(protocol.get(field) in (None, "") for field in protocol_fields):
        raise ValueError(f"action protocol is not explicit: {evidence_path}")

    collision_gates = [
        (path, item)
        for path, item in objects
        if item.get("schema_version") == "M2BIsaacCollisionGateV1"
    ]
    collision_paths = {path for path, _ in collision_gates}
    missing_collision_paths = REQUIRED_COLLISION_GATE_PATHS[failure] - collision_paths
    if failure == "WRONG_OBJECT" and not any(
        path.startswith(
            "$.m2b_recovery.wrong_object.regrasp_execution.attempts["
        )
        and path.endswith("].contact_motion.collision_gate")
        for path in collision_paths
    ):
        missing_collision_paths.add(
            "$.m2b_recovery.wrong_object.regrasp_execution."
            "attempts[*].contact_motion.collision_gate"
        )
    if failure == "WRONG_OBJECT" and not any(
        path.startswith(
            "$.m2b_recovery.wrong_object.regrasp_execution.ik_reachability_scan.trials["
        )
        and path.endswith("].pregrasp_motion.collision_gate")
        for path in collision_paths
    ):
        missing_collision_paths.add(
            "$.m2b_recovery.wrong_object.regrasp_execution."
            "ik_reachability_scan.trials[*].pregrasp_motion.collision_gate"
        )
    if missing_collision_paths:
        raise ValueError(
            f"required collision gates are missing for {failure}: "
            f"{sorted(missing_collision_paths)}: {evidence_path}"
        )
    for path, gate in collision_gates:
        if (
            gate.get("status") != "PASS"
            or gate.get("contact_reporting_required") is not True
            or int(gate.get("unexpected_robot_contact_events", -1)) != 0
            or gate.get("unexpected_contacts") not in ([], None)
            or gate.get("teacher_used") is not False
            or gate.get("privileged_truth_policy_input") is not False
        ):
            raise ValueError(f"collision/safety gate failed at {path}: {evidence_path}")

    return {
        "scene_seed": scene_seed,
        "failure_type": failure,
        "evidence_path": evidence_path,
        "evidence_sha256": actual_sha256,
        "strict_physical_public_predicate_passed": True,
        "public_predicate_results_checked": 2,
        "collision_gates_checked": len(collision_gates),
        "collision_or_safety_violations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def audit_accepted_evidence(
    statuses: list[dict[str, Any]],
    *,
    host: str,
    predicate_binding: dict[str, Any],
    expected_per_failure: int = EXPECTED_NEW_ACCEPTED_PER_FAILURE,
) -> dict[str, Any]:
    """Independently re-audit every accepted S3 payload after evidence freeze."""
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for status in statuses:
        if status.get("teacher_used") is not False:
            raise ValueError("S3 worker status is not explicitly Teacher-free")
        if status.get("privileged_truth_policy_input") is not False:
            raise ValueError("S3 worker status used privileged policy input")
        for record in status.get("records", []):
            if record.get("accepted") is not True:
                continue
            failure = str(record.get("failure_type"))
            path = str(record.get("evidence"))
            declared_sha256 = str(record.get("evidence_sha256", ""))
            actual_sha256 = remote_sha256(host, path)
            payload = remote_json(host, path)
            audited = audit_accepted_payload(
                payload,
                failure=failure,
                evidence_path=path,
                declared_sha256=declared_sha256,
                actual_sha256=actual_sha256,
                scene_seed=int(record.get("scene_seed", -1)),
            )
            records.append(audited)
            counts[failure] += 1

    expected_total = expected_per_failure * len(MANDATORY_FAILURES)
    if len(records) != expected_total or any(
        counts[failure] != expected_per_failure for failure in MANDATORY_FAILURES
    ):
        raise ValueError(
            "accepted evidence audit did not bind the exact frozen S3 target: "
            f"records={len(records)}, counts={dict(counts)}"
        )
    return {
        "schema_version": "M2CS3AcceptedEvidenceAuditV1",
        "status": "PASS",
        "records_audited": len(records),
        "counts_by_failure": {
            failure: counts[failure] for failure in MANDATORY_FAILURES
        },
        "evidence_sha256_matches": len(records),
        "strict_physical_public_predicates_passed": len(records),
        "public_predicate_results_checked": sum(
            int(record["public_predicate_results_checked"]) for record in records
        ),
        "collision_gates_checked": sum(
            int(record["collision_gates_checked"]) for record in records
        ),
        "collision_or_safety_violations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "acceptance_predicate": predicate_binding,
        "records": records,
    }


def _promote_record(
    episode: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    promoted = deepcopy(episode)
    prior_version = str(promoted["dataset_version"])
    promoted["source_dataset_version"] = prior_version
    promoted["dataset_version"] = DATASET_VERSION
    promoted["m2c_s3_source"] = source
    promoted["teacher_used"] = False
    promoted["policy_input_simulator_truth"] = False
    return promoted


def merge_episodes(
    base: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    merged = []
    quarantine = []
    seen_evidence: set[str] = set()
    candidates = [
        *[(episode, "FROZEN_M2B_DATASET_V2") for episode in base],
        *[
            (episode, "M2C_S3_ACCEPTED_PHYSICAL_EVIDENCE")
            for episode in sorted(
                additions,
                key=lambda item: (
                    int(item["scene_seed"]),
                    str(item["failure_context"]["failure_type"]),
                    int(item["injection_seed"]),
                ),
            )
        ],
    ]
    for episode, source in candidates:
        try:
            digest = str(episode["provenance"]["evidence_sha256"])
            if len(digest) != 64:
                raise ValueError("evidence SHA-256 is malformed")
            if digest in seen_evidence:
                continue
            promoted = _promote_record(episode, source=source)
            errors = validate_failure_recovery_episode(promoted)
            if errors:
                raise ValueError(errors)
            seen_evidence.add(digest)
            merged.append(promoted)
        except (KeyError, TypeError, ValueError) as error:
            quarantine.append(
                {
                    "episode_id": str(episode.get("episode_id", "UNKNOWN")),
                    "reason": f"{type(error).__name__}: {error}",
                    "source": source,
                }
            )
    return merged, quarantine


def coverage_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    failures = Counter(str(episode["failure_context"]["failure_type"]) for episode in episodes)
    recoveries = Counter(
        str(episode["failure_context"]["failure_type"])
        for episode in episodes
        if episode["recovery_execution"]["successful"] is True
    )
    splits = Counter(str(episode["split"]) for episode in episodes)
    by_split: dict[str, Counter[str]] = {}
    split_groups: dict[str, set[str]] = {}
    for episode in episodes:
        split = str(episode["split"])
        failure = str(episode["failure_context"]["failure_type"])
        by_split.setdefault(split, Counter())[failure] += 1
        split_groups.setdefault(str(episode["split_group"]), set()).add(split)
    leakage = sorted(group for group, assigned in split_groups.items() if len(assigned) > 1)
    full_gate = all(
        failures[failure] >= FULL_FAILURE_MINIMUM and recoveries[failure] >= FULL_RECOVERY_MINIMUM
        for failure in MANDATORY_FAILURES
    )
    return {
        "failure_counts": {failure: failures[failure] for failure in MANDATORY_FAILURES},
        "successful_recovery_counts": {
            failure: recoveries[failure] for failure in MANDATORY_FAILURES
        },
        "split_counts": dict(sorted(splits.items())),
        "counts_by_split": {
            split: {failure: counts[failure] for failure in MANDATORY_FAILURES}
            for split, counts in sorted(by_split.items())
        },
        "unique_scene_groups": len(split_groups),
        "split_group_leakage": leakage,
        "full_class_coverage_gate_passed": full_gate and not leakage,
    }


def fourth_class_records(plan: dict[str, Any]) -> list[dict[str, Any]]:
    fourth = plan["fourth_class"]
    if (
        fourth["failure_type"] != "PATH_BLOCKED"
        or fourth["model_training_eligible"] is not False
        or fourth["new_skill_label_created"] is not False
    ):
        raise ValueError("fourth-class raw-only boundary changed")
    return [
        {
            "schema_version": "M2CPathBlockedRawEvidenceV1",
            "failure_type": "PATH_BLOCKED",
            "scene_seed": int(item["scene_seed"]),
            "evidence_path": str(item["evidence_path"]),
            "evidence_sha256": str(item["evidence_sha256"]),
            "strict_complete_existence_proof": bool(item["strict_complete_existence_proof"]),
            "model_training_eligible": False,
            "new_skill_label_created": False,
            "human_adr_required_before_model_label_or_q_b": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        for item in fourth["evidence"]
    ]


def write_report_markdown(path: Path, report: dict[str, Any]) -> None:
    failures = report["failure_counts"]
    recoveries = report["successful_recovery_counts"]
    snapshots = report["worker_status_snapshots"]
    freeze = report["evidence_freeze"]
    audit = report["accepted_evidence_audit"]
    rejected = report["collection_rejections"]
    lines = [
        "# M2C S3 Dataset V3",
        "",
        f"- Verdict: **{report['status']}**.",
        f"- Valid/quarantined episodes: {report['episodes_valid']}/{report['episodes_quarantined']}.",
        f"- Failure counts: `{failures}`.",
        f"- Successful recovery counts: `{recoveries}`.",
        f"- Split-group leakage: `{report['split_group_leakage']}`.",
        f"- Collection attempts rejected by frozen predicates: {rejected}; every rejection is retained in the JSON report.",
        (
            f"- Accepted-evidence audit: {audit['records_audited']}/150 records; "
            f"strict predicates {audit['strict_physical_public_predicates_passed']}/150; "
            f"SHA matches {audit['evidence_sha256_matches']}/150; "
            f"collision gates checked {audit['collision_gates_checked']}; violations 0."
        ),
        "",
        "## Evidence boundary",
        "",
        f"- Remote evidence tree: `{freeze['remote_root']}`; read-only: `{freeze['evidence_tree_readonly']}`.",
        f"- Evidence ledger: `{freeze['ledger']}`; SHA-256 `{freeze['ledger_sha256']}`; {freeze['files_hashed']} files bound.",
        *[
            (
                f"- Worker status `{snapshot['path']}`: SHA-256 "
                f"`{snapshot['sha256']}`, accepted `{snapshot['accepted_counts']}`, "
                f"records `{snapshot['record_count']}`."
            )
            for snapshot in snapshots
        ],
        "- Teacher used: no; Teacher kill-rule events: none.",
        "- Privileged simulator truth used as policy input: no.",
        "- The world-model mainline was not replaced.",
        "- PATH_BLOCKED remains raw evaluator evidence only; it is not a model training label and no new skill label was created.",
        "",
        "## Task report",
        "",
        "- Changed/generated files:",
        f"  - `{report['output_path']}` (SHA-256 `{report['output_sha256']}`)",
        f"  - `{report['quarantine_path']}` (SHA-256 `{report['quarantine_sha256']}`)",
        f"  - `{report['fourth_class']['path']}` (SHA-256 `{report['fourth_class']['sha256']}`)",
        f"  - `{report['evidence_freeze']['report_path']}` (SHA-256 `{report['evidence_freeze']['report_sha256']}`)",
        f"  - `{path}`",
        "- Tests: full class-coverage gate, 150/150 strict physical/public acceptance re-audit, recursive collision/safety gate audit, strict episode validation, accepted-evidence SHA binding, zero packaging quarantine, and split-group leakage check.",
        f"- Failures: {rejected} collection attempts were rejected and retained with explicit reasons; packaging quarantine is {report['episodes_quarantined']}.",
        "- Blocker: Q-B remains forbidden until a separate human expressivity ADR is committed; this S3 result does not authorize Q-B.",
        "- Next command: `sed -n '1,240p' docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md`.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(
    *,
    base: list[dict[str, Any]],
    additions: list[dict[str, Any]],
    package_quarantine: list[dict[str, Any]],
    collection_rejections: list[dict[str, object]],
    worker_status_snapshots: list[dict[str, Any]],
    evidence_freeze: dict[str, Any],
    plan: dict[str, Any],
    accepted_evidence_audit: dict[str, Any],
    output: Path,
    quarantine_path: Path,
    fourth_class_path: Path,
    report_path: Path,
    report_md_path: Path | None = None,
) -> dict[str, Any]:
    merged, merge_quarantine = merge_episodes(base, additions)
    quarantine = [*package_quarantine, *merge_quarantine]
    coverage = coverage_summary(merged)
    raw_fourth = fourth_class_records(plan)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in merged),
        encoding="utf-8",
    )
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in quarantine),
        encoding="utf-8",
    )
    fourth_class_path.parent.mkdir(parents=True, exist_ok=True)
    fourth_class_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in raw_fourth),
        encoding="utf-8",
    )

    additions_by_failure = Counter(
        str(item["failure_context"]["failure_type"]) for item in additions
    )
    rejections_by_failure = Counter(
        str(item.get("failure_type") or "INFRASTRUCTURE") for item in collection_rejections
    )
    evidence_audit_passed = bool(
        accepted_evidence_audit.get("status") == "PASS"
        and int(accepted_evidence_audit.get("records_audited", -1))
        == EXPECTED_NEW_ACCEPTED_PER_FAILURE * len(MANDATORY_FAILURES)
        and accepted_evidence_audit.get("counts_by_failure")
        == {
            failure: EXPECTED_NEW_ACCEPTED_PER_FAILURE
            for failure in MANDATORY_FAILURES
        }
        and int(accepted_evidence_audit.get("evidence_sha256_matches", -1))
        == int(accepted_evidence_audit.get("records_audited", -2))
        and int(
            accepted_evidence_audit.get(
                "strict_physical_public_predicates_passed", -1
            )
        )
        == int(accepted_evidence_audit.get("records_audited", -2))
        and int(accepted_evidence_audit.get("public_predicate_results_checked", -1))
        == 300
        and int(accepted_evidence_audit.get("collision_gates_checked", -1)) >= 550
        and int(accepted_evidence_audit.get("collision_or_safety_violations", -1))
        == 0
        and len(accepted_evidence_audit.get("records", [])) == 150
        and accepted_evidence_audit.get("teacher_used") is False
        and accepted_evidence_audit.get("privileged_truth_policy_input") is False
        and accepted_evidence_audit.get("acceptance_predicate")
        == {
            "path": FROZEN_PHYSICAL_RUNNER,
            "sha256": FROZEN_PHYSICAL_RUNNER_SHA256,
            "public_rgbd_required": True,
            "predicate": "m2b.run_physical_failure_smoke.accepted",
        }
    )
    status = (
        "PASS_S3_FULL_CLASS_COVERAGE"
        if coverage["full_class_coverage_gate_passed"]
        and not quarantine
        and evidence_audit_passed
        else "IN_PROGRESS_S3_FULL_CLASS_COVERAGE"
    )
    report: dict[str, Any] = {
        "schema_version": "M2CS3DatasetReportV1",
        "status": status,
        "dataset_version": DATASET_VERSION,
        "episodes_valid": len(merged),
        "episodes_quarantined": len(quarantine),
        **coverage,
        "frozen_base_episodes": len(base),
        "new_accepted_episodes": len(additions),
        "new_accepted_counts": {
            failure: additions_by_failure[failure] for failure in MANDATORY_FAILURES
        },
        "collection_rejections": len(collection_rejections),
        "collection_rejection_counts": dict(sorted(rejections_by_failure.items())),
        "collection_rejection_records": collection_rejections,
        "worker_status_snapshots": worker_status_snapshots,
        "evidence_freeze": evidence_freeze,
        "accepted_evidence_audit": accepted_evidence_audit,
        "code_revision_histogram": code_revision_histogram(merged),
        "base_dataset": {
            "path": str(BASE_DATASET),
            "sha256": sha256_file(BASE_DATASET),
            "readonly": True,
        },
        "plan": {
            "path": str(DEFAULT_PLAN),
            "sha256": sha256_file(DEFAULT_PLAN),
            "plan_sha256": plan["plan_sha256"],
        },
        "output_path": str(output),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "quarantine_path": str(quarantine_path),
        "quarantine_sha256": hashlib.sha256(quarantine_path.read_bytes()).hexdigest(),
        "fourth_class": {
            "failure_type": "PATH_BLOCKED",
            "raw_records": len(raw_fourth),
            "successful_recoveries": sum(
                item["strict_complete_existence_proof"] for item in raw_fourth
            ),
            "path": str(fourth_class_path),
            "sha256": hashlib.sha256(fourth_class_path.read_bytes()).hexdigest(),
            "model_training_eligible": False,
            "new_skill_label_created": False,
            "human_adr_required_before_model_label_or_q_b": True,
        },
        "q_b_training_or_evaluation_executed": False,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
        "task_report": {
            "changed_or_generated_files": [
                str(output),
                str(quarantine_path),
                str(fourth_class_path),
                str(evidence_freeze["report_path"]),
                str(report_path),
                *([str(report_md_path)] if report_md_path is not None else []),
            ],
            "tests": [
                {
                    "name": "S3 frozen-evidence dataset gates",
                    "status": "PASS" if status == "PASS_S3_FULL_CLASS_COVERAGE" else "FAIL",
                    "checks": [
                        "full class coverage",
                        "150/150 strict physical/public acceptance re-audit",
                        "recursive collision/safety gate audit",
                        "strict episode validation",
                        "accepted-evidence SHA binding",
                        "zero packaging quarantine",
                        "split-group leakage",
                    ],
                }
            ],
            "failures": {
                "collection_attempts_rejected": len(collection_rejections),
                "packaging_quarantine": len(quarantine),
            },
            "blockers": [
                "Q-B is forbidden until a separate human expressivity ADR is committed."
            ],
            "next_command": (
                "sed -n '1,240p' "
                "docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md"
            ),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if report_md_path is not None:
        write_report_markdown(report_md_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--freeze-report", type=Path, default=DEFAULT_FREEZE_REPORT)
    parser.add_argument(
        "--worker-status",
        action="append",
        required=True,
        help="absolute remote worker-status.json; repeat for both workers",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--fourth-class-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args()

    if sha256_file(BASE_DATASET) != BASE_DATASET_SHA256:
        raise SystemExit("frozen M2B Dataset V2 hash mismatch")
    plan = json.loads(args.plan.read_text())
    if plan.get("schema_version") != "M2CS3CollectionPlanV1":
        raise SystemExit("unsupported M2C S3 collection plan")
    if len(set(args.worker_status)) != len(args.worker_status):
        raise SystemExit("duplicate S3 worker-status path")
    statuses = []
    worker_status_snapshots = []
    for path in args.worker_status:
        try:
            status, snapshot = load_stable_worker_status(args.host, path)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        statuses.append(status)
        worker_status_snapshots.append(snapshot)
    for status in statuses:
        if status.get("status") != "COMPLETE_ACCEPTED_TARGET":
            raise SystemExit("S3 worker has not reached its frozen accepted target")
        counts = status.get("accepted_counts", {})
        if any(int(counts.get(failure, -1)) != 25 for failure in MANDATORY_FAILURES):
            raise SystemExit("S3 worker accepted counts do not equal 25/class")
    try:
        evidence_freeze = validate_evidence_freeze(
            args.freeze_report,
            host=args.host,
            worker_status_snapshots=worker_status_snapshots,
        )
        verify_remote_evidence_ledger(args.host, evidence_freeze)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
    evidence, rejected = accepted_evidence(statuses)
    try:
        predicate_binding = validate_frozen_acceptance_predicate(plan)
        accepted_evidence_audit = audit_accepted_evidence(
            statuses,
            host=args.host,
            predicate_binding=predicate_binding,
        )
    except (KeyError, TypeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
    additions, package_quarantine = package(evidence, host=args.host)
    report = write_outputs(
        base=load_jsonl(BASE_DATASET),
        additions=additions,
        package_quarantine=package_quarantine,
        collection_rejections=rejected,
        worker_status_snapshots=worker_status_snapshots,
        evidence_freeze=evidence_freeze,
        accepted_evidence_audit=accepted_evidence_audit,
        plan=plan,
        output=args.output,
        quarantine_path=args.quarantine,
        fourth_class_path=args.fourth_class_output,
        report_path=args.report,
        report_md_path=args.report_md,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS_S3_FULL_CLASS_COVERAGE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
