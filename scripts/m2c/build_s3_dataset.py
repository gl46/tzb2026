#!/usr/bin/env python3
"""Merge frozen M2B records with accepted S3 evidence and enforce full coverage."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from m2b.build_dataset_v2 import (
    code_revision_histogram,
    package,
    remote_json,
    remote_sha256,
)
from m2c.build_headroom_domain import DATASET_VERSION, PROJECT, sha256_file
from m2c.freeze_s3_evidence import DEFAULT_REMOTE_ROOT, LEDGER_NAME
from xh_agent.data_engine.isaac.failure_rich import (
    validate_failure_recovery_episode,
)


MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
FULL_FAILURE_MINIMUM = 100
FULL_RECOVERY_MINIMUM = 50
BASE_DATASET = PROJECT / "artifacts/m2b/dataset-v2.jsonl"
BASE_DATASET_SHA256 = "c24e34493ba2226c1aa691c1b1c43993fbecdff5ad74b291e08c4913efc71362"
DEFAULT_PLAN = PROJECT / "configs/m2c_s3_collection_plan.json"
DEFAULT_FREEZE_REPORT = PROJECT / "reports/m2c-s3-evidence-freeze.json"


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


def write_outputs(
    *,
    base: list[dict[str, Any]],
    additions: list[dict[str, Any]],
    package_quarantine: list[dict[str, Any]],
    collection_rejections: list[dict[str, object]],
    worker_status_snapshots: list[dict[str, Any]],
    evidence_freeze: dict[str, Any],
    plan: dict[str, Any],
    output: Path,
    quarantine_path: Path,
    fourth_class_path: Path,
    report_path: Path,
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
    status = (
        "PASS_S3_FULL_CLASS_COVERAGE"
        if coverage["full_class_coverage_gate_passed"] and not quarantine
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
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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
        if any(int(counts.get(failure, 0)) < 25 for failure in MANDATORY_FAILURES):
            raise SystemExit("S3 worker accepted counts are below 25/class")
    try:
        evidence_freeze = validate_evidence_freeze(
            args.freeze_report,
            host=args.host,
            worker_status_snapshots=worker_status_snapshots,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    evidence, rejected = accepted_evidence(statuses)
    additions, package_quarantine = package(evidence, host=args.host)
    report = write_outputs(
        base=load_jsonl(BASE_DATASET),
        additions=additions,
        package_quarantine=package_quarantine,
        collection_rejections=rejected,
        worker_status_snapshots=worker_status_snapshots,
        evidence_freeze=evidence_freeze,
        plan=plan,
        output=args.output,
        quarantine_path=args.quarantine,
        fourth_class_path=args.fourth_class_output,
        report_path=args.report,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS_S3_FULL_CLASS_COVERAGE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
