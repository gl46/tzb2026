#!/usr/bin/env python3
"""Package accepted physical failure evidence into Dataset V2 coarse records."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from m2b.build_failure_evidence_pilot import build_episode, remote_json
except ModuleNotFoundError:  # direct `python scripts/m2b/...` execution
    from build_failure_evidence_pilot import build_episode, remote_json

from xh_agent.data_engine.isaac.failure_rich import (
    failure_rich_group_key,
    validate_failure_recovery_episode,
)


MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")


def scene_split(scene_seed: int) -> str:
    bucket = int(
        hashlib.sha256(f"scene-{scene_seed}".encode()).hexdigest()[:8], 16
    ) % 100
    if bucket < 80:
        return "train"
    return "val" if bucket < 90 else "test"


def remote_sha256(host: str, path: str) -> str:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "sha256sum", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.split()[0]


def evidence_from_worker_status(
    host: str,
    path: str,
) -> list[tuple[str, str]]:
    status = remote_json(host, path)
    return [
        (record["failure_type"], record["evidence"])
        for record in status.get("records", [])
        if record.get("accepted") is True and record.get("evidence")
    ]


def package(
    evidence: list[tuple[str, str]],
    *,
    host: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    episodes = []
    quarantined = []
    seen_hashes = set()
    for failure_type, path in evidence:
        try:
            digest = remote_sha256(host, path)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            payload = remote_json(host, path)
            injection_seed = int(digest[:8], 16)
            episode = build_episode(
                payload,
                failure_type=failure_type,
                evidence_path=path,
                evidence_sha256=digest,
                injection_seed=injection_seed,
            )
            scene_seed = int(episode["scene_seed"])
            episode.update(
                {
                    "dataset_version": "isaac-industrial-v2-failure-rich",
                    "split": scene_split(scene_seed),
                    "split_group": f"scene-{scene_seed}",
                    "group_key": failure_rich_group_key(
                        scene_seed,
                        failure_type,
                        injection_seed,
                    ),
                    "dataset_role": "FAILURE_RECOVERY_COARSE_SUPERVISION",
                    "model_rollout": False,
                }
            )
            episode["provenance"]["packager"] = (
                "scripts/m2b/build_dataset_v2.py"
            )
            errors = validate_failure_recovery_episode(episode)
            if errors:
                raise ValueError(errors)
            episodes.append(episode)
        except (KeyError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            quarantined.append(
                {
                    "failure_type": failure_type,
                    "evidence_path": path,
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
    return episodes, quarantined


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="FAILURE_TYPE=/absolute/remote/actuation-probe.json",
    )
    parser.add_argument(
        "--remote-worker-status",
        action="append",
        default=[],
        help="Remote worker-status.json; may be RUNNING_OR_PARTIAL.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    evidence = []
    for item in args.evidence:
        failure_type, path = item.split("=", 1)
        evidence.append((failure_type, path))
    for status_path in args.remote_worker_status:
        evidence.extend(evidence_from_worker_status(args.host, status_path))
    if not evidence:
        raise SystemExit("no accepted evidence was supplied")
    unsupported = sorted(set(failure for failure, _ in evidence) - set(MANDATORY_FAILURES))
    if unsupported:
        raise SystemExit(f"unsupported failure types: {unsupported}")
    episodes, quarantined = package(evidence, host=args.host)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in episodes)
    )
    args.quarantine.parent.mkdir(parents=True, exist_ok=True)
    args.quarantine.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in quarantined)
    )
    failure_counts = Counter(
        episode["failure_context"]["failure_type"] for episode in episodes
    )
    recovery_counts = Counter(
        episode["failure_context"]["failure_type"]
        for episode in episodes
        if episode["recovery_execution"]["successful"] is True
    )
    split_counts = Counter(episode["split"] for episode in episodes)
    limited_gate = all(
        failure_counts[failure] >= 50
        and recovery_counts[failure] >= 25
        for failure in MANDATORY_FAILURES
    )
    split_groups: dict[str, set[str]] = {}
    for episode in episodes:
        split_groups.setdefault(episode["split_group"], set()).add(
            episode["split"]
        )
    leakage = sorted(
        group for group, splits in split_groups.items() if len(splits) > 1
    )
    report = {
        "schema_version": "M2BDatasetV2ReportV1",
        "status": (
            "PASS_DATASET_V2_LIMITED_CLASS_COVERAGE"
            if limited_gate and not leakage
            else "IN_PROGRESS_DATASET_V2_LIMITED_CLASS_COVERAGE"
        ),
        "episodes_generated": len(evidence),
        "episodes_valid": len(episodes),
        "episodes_quarantined": len(quarantined),
        "failure_counts": {
            failure: failure_counts[failure] for failure in MANDATORY_FAILURES
        },
        "successful_recovery_counts": {
            failure: recovery_counts[failure] for failure in MANDATORY_FAILURES
        },
        "split_counts": dict(sorted(split_counts.items())),
        "unique_scene_groups": len(split_groups),
        "split_group_leakage": leakage,
        "limited_coverage_gate_passed": limited_gate and not leakage,
        "model_rollout_episodes": 0,
        "coarse_failure_recovery_supervision_episodes": len(episodes),
        "residual_training_eligible_episodes": 0,
        "output_path": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "quarantine_path": str(args.quarantine),
        "quarantine_sha256": hashlib.sha256(
            args.quarantine.read_bytes()
        ).hexdigest(),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "limitations": [
            "These episodes supervise FailureContext and coarse recovery skills, not model rollout attribution.",
            "Residual targets remain excluded until independent perturbation/correction executions exist.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
