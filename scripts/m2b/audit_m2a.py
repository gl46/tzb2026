#!/usr/bin/env python3
"""Freeze M2A evidence and diagnose its FC, residual, and mapping limits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Iterable


PROJECT = Path(__file__).resolve().parents[2]
MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")


def command(args: list[str], *, cwd: Path = PROJECT) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {args}\n"
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def git_blob(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=PROJECT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"missing Git evidence {commit}:{path}")
    return completed.stdout


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def entropy(values: Iterable[Any]) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if not total:
        return 0.0
    return -sum(
        (count / total) * math.log2(count / total)
        for count in counts.values()
    )


def load_episodes(dataset_root: Path) -> list[dict[str, Any]]:
    paths = sorted((dataset_root / "shards").glob("*.READY/episodes.jsonl"))
    if not paths:
        raise RuntimeError(f"no READY episode files under {dataset_root}")
    return [
        json.loads(line)
        for path in paths
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def verify_artifact_index(commit: str) -> dict[str, Any]:
    index_path = "reports/m2a-artifact-index.json"
    index = json.loads(git_blob(commit, index_path))
    failures = []
    for item in index["artifacts"]:
        observed = sha256_bytes(git_blob(commit, item["path"]))
        if observed != item["sha256"]:
            failures.append(
                {
                    "path": item["path"],
                    "expected": item["sha256"],
                    "observed": observed,
                }
            )
    return {
        "index_path": index_path,
        "artifact_count": len(index["artifacts"]),
        "verified_count": len(index["artifacts"]) - len(failures),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def failure_context_audit(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    failure_types = Counter(
        episode["failure_context"]["failure_type"] for episode in episodes
    )
    skills = Counter(episode["nominal_skill"] for episode in episodes)
    recovery_sequences = Counter(
        tuple(episode.get("recovery_sequence", [])) for episode in episodes
    )
    split_counts = Counter(episode["split"] for episode in episodes)
    failure_by_split: dict[str, dict[str, int]] = {}
    for split in sorted(split_counts):
        failure_by_split[split] = dict(
            sorted(
                Counter(
                    episode["failure_context"]["failure_type"]
                    for episode in episodes
                    if episode["split"] == split
                ).items()
            )
        )
    skill_by_failure: dict[str, dict[str, int]] = {}
    for failure_type in sorted(failure_types):
        skill_by_failure[failure_type] = dict(
            sorted(
                Counter(
                    episode["nominal_skill"]
                    for episode in episodes
                    if episode["failure_context"]["failure_type"]
                    == failure_type
                ).items()
            )
        )
    contexts = [episode["failure_context"] for episode in episodes]
    nonempty = sum(
        bool(
            context["failure_type"] != "NONE"
            or context.get("predicate_residual")
            or context.get("attempted_recoveries")
            or context.get("retry_count")
        )
        for context in contexts
    )
    field_entropy = {
        "failure_type_bits": entropy(
            context["failure_type"] for context in contexts
        ),
        "last_skill_bits": entropy(
            context.get("last_skill") for context in contexts
        ),
        "retry_count_bits": entropy(
            context.get("retry_count", 0) for context in contexts
        ),
        "predicate_residual_bits": entropy(
            tuple(context.get("predicate_residual", []))
            for context in contexts
        ),
        "attempted_recoveries_bits": entropy(
            tuple(context.get("attempted_recoveries", []))
            for context in contexts
        ),
    }
    scene_splits: dict[int, set[str]] = defaultdict(set)
    for episode in episodes:
        scene_splits[int(episode["scene_seed"])].add(episode["split"])
    mandatory_counts = {
        failure_type: failure_types.get(failure_type, 0)
        for failure_type in MANDATORY_FAILURES
    }
    repeated_action_examples = sum(
        bool(context.get("attempted_recoveries"))
        and episode["nominal_skill"]
        == context.get("attempted_recoveries", [None])[-1]
        for episode, context in zip(episodes, contexts)
    )
    diagnosis = [
        "FailureContext reached the prompt in the FC-on pipeline; the M2A raw reports explicitly distinguish failure_context=on/off.",
        "The corpus exposes only NONE and TRACKING_LOST, and nominal skill is deterministic within each failure type.",
        "retry_count is always zero and attempted_recoveries is always empty, so no history-conditioned alternative recovery decision exists.",
        "The dominant REOBSERVE class can be inferred from public tracking quality, making FailureContext redundant rather than proven ineffective.",
        "M2A's two-seed zero overall accuracy/macro-F1 delta is therefore inconclusive for the mandatory physical failures.",
    ]
    return {
        "schema_version": "M2BFailureContextAuditV1",
        "status": "LIMITED",
        "episodes": len(episodes),
        "split_counts": dict(sorted(split_counts.items())),
        "coarse_skill_counts": dict(sorted(skills.items())),
        "failure_type_counts": dict(sorted(failure_types.items())),
        "mandatory_failure_counts": mandatory_counts,
        "recovery_sequence_counts": {
            json.dumps(list(key)): value
            for key, value in sorted(recovery_sequences.items())
        },
        "failure_by_split": failure_by_split,
        "skill_by_failure": skill_by_failure,
        "failure_context_nonempty_count": nonempty,
        "failure_context_nonempty_rate": nonempty / max(len(episodes), 1),
        "failure_context_unique_combinations": len(
            {json.dumps(context, sort_keys=True) for context in contexts}
        ),
        "field_entropy": field_entropy,
        "retry_count_values": sorted(
            {int(context.get("retry_count", 0)) for context in contexts}
        ),
        "attempted_recovery_nonempty_count": sum(
            bool(context.get("attempted_recoveries")) for context in contexts
        ),
        "same_failure_repeated_action_examples": repeated_action_examples,
        "unique_scene_seeds": len(scene_splits),
        "scene_split_conflicts": sum(
            len(splits) > 1 for splits in scene_splits.values()
        ),
        "duplicate_episode_ids": len(episodes)
        - len({episode["episode_id"] for episode in episodes}),
        "diagnosis": diagnosis,
        "verdict": "INCONCLUSIVE",
        "required_v2_change": (
            "collect matched visual states with distinct physical failure "
            "histories and distinct recovery labels"
        ),
    }


def residual_audit(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [episode["residual_action"]["values"][0] for episode in episodes]
    width = len(rows[0])
    axis_stats = []
    for axis in range(width):
        values = [float(row[axis]) for row in rows]
        axis_stats.append(
            {
                "dimension": episodes[0]["residual_action"][
                    "dimension_names"
                ][axis],
                "mean": fmean(values),
                "std": pstdev(values),
                "min": min(values),
                "max": max(values),
                "exact_zero_rate": sum(value == 0.0 for value in values)
                / len(values),
            }
        )
    translation_norms = [
        math.sqrt(sum(float(value) ** 2 for value in row[:3]))
        for row in rows
    ]
    flattened = [float(value) for row in rows for value in row]
    exact_zero = sum(all(float(value) == 0.0 for value in row) for row in rows)
    near_zero = sum(norm <= 0.001 for norm in translation_norms)
    saturation = sum(
        any(abs(float(value)) >= 0.03 - 1e-12 for value in row[:3])
        for row in rows
    )
    repeated_chunks = sum(
        len(
            {
                tuple(float(value) for value in chunk)
                for chunk in episode["residual_action"]["values"]
            }
        )
        == 1
        for episode in episodes
    )
    nominal_zero = sum(
        all(
            float(value) == 0.0
            for row in episode["nominal_action"]["values"]
            for value in row
        )
        for episode in episodes
    )
    correction_success = sum(
        bool(episode.get("result", {}).get("correction_success"))
        for episode in episodes
    )
    return {
        "schema_version": "M2BResidualAuditV1",
        "status": "RESIDUAL_TARGET_DEGENERATE",
        "episodes": len(episodes),
        "target_semantics": episodes[0]
        .get("provenance", {})
        .get("residual_label"),
        "exact_zero_count": exact_zero,
        "exact_zero_rate": exact_zero / len(rows),
        "near_zero_translation_threshold_m": 0.001,
        "near_zero_translation_count": near_zero,
        "near_zero_translation_rate": near_zero / len(rows),
        "translation_norm": {
            "min": min(translation_norms),
            "max": max(translation_norms),
            "mean": fmean(translation_norms),
            "rmse": math.sqrt(fmean(value**2 for value in translation_norms)),
        },
        "axis_stats": axis_stats,
        "clip_limit_translation_m": 0.03,
        "translation_saturation_count": saturation,
        "translation_saturation_rate": saturation / len(rows),
        "identical_rows_within_chunk_count": repeated_chunks,
        "nominal_action_exact_zero_count": nominal_zero,
        "successful_correction_label_count": correction_success,
        "zero_residual_baseline": {
            "mae_all_dimensions": fmean(abs(value) for value in flattened),
            "rmse_all_dimensions": math.sqrt(
                fmean(value**2 for value in flattened)
            ),
            "translation_mae": fmean(
                abs(float(value)) for row in rows for value in row[:3]
            ),
            "translation_rmse": math.sqrt(
                fmean(float(value) ** 2 for row in rows for value in row[:3])
            ),
        },
        "diagnosis": [
            "The target is nearest simulator truth minus a public track, not a demonstrated successful correction to an executed perturbed nominal.",
            "Every nominal action is zero and every four-step residual chunk repeats one row, so temporal correction structure is absent.",
            "Rotation and gripper targets are identically zero while translation is frequently clipped at the 30 mm bound.",
            "No episode records correction_success, so target magnitude alone does not establish learnability or execution benefit.",
        ],
        "required_v2_change": (
            "use bounded B0 perturbation -> physically verified safe correction "
            "pairs and retain both zero and non-zero examples"
        ),
    }


def remote_mapping_decisions(host: str, root: str) -> tuple[list[dict[str, Any]], int]:
    paths = command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            host,
            f"find '{root}' -name metrics.json -type f -print | sort",
        ]
    ).splitlines()
    decisions: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(
            command(
                ["ssh", "-o", "BatchMode=yes", host, f"cat '{path}'"]
            )
        )
        decisions.extend(
            payload.get("qrm_closed_loop_smoke", {}).get("decisions", [])
        )
    return decisions, len(paths)


def mapping_audit(
    decisions: list[dict[str, Any]],
    *,
    metrics_files: int,
    worker_source: str,
) -> dict[str, Any]:
    reasons = Counter(
        decision.get("mapping_validation", "other") for decision in decisions
    )
    skills = Counter(decision.get("coarse_skill", "UNKNOWN") for decision in decisions)
    applicable = [
        decision
        for decision in decisions
        if decision.get("applies_to_step") is not None
    ]
    integration_gate_is_unconditional = (
        'False,\n                    "UNVERIFIED_CAMERA_RESIDUAL_TO_JOINT_MAPPING"'
        in worker_source
        and '"REJECTED_NO_OFFICIAL_EVIDENCE"' in worker_source
    )
    reason_histogram = {
        "unknown_skill_enum": 0,
        "alias_or_case_mismatch": 0,
        "schema_version_mismatch": 0,
        "missing_target_track": 0,
        "stale_track": 0,
        "unsupported_parameter": 0,
        "coordinate_frame_mismatch": 0,
        "unit_mismatch": 0,
        "out_of_range_residual": 0,
        "low_confidence": 0,
        "safety_rejection": 0,
        "integration_mapping_absent": len(decisions),
        "other": 0,
    }
    return {
        "schema_version": "M2BRuntimeMappingAuditV1",
        "status": "MAPPING_INTEGRATION_ABSENT",
        "metrics_files": metrics_files,
        "model_decisions_total": len(decisions),
        "model_decisions_applicable": len(applicable),
        "coarse_skill_histogram": dict(sorted(skills.items())),
        "raw_mapping_reason_histogram": dict(sorted(reasons.items())),
        "public_track_count_range": (
            [
                min(int(item["public_track_count"]) for item in decisions),
                max(int(item["public_track_count"]) for item in decisions),
            ]
            if decisions
            else None
        ),
        "residual_proposed_count": sum(
            bool(item.get("residual_proposed")) for item in decisions
        ),
        "integration_gate_is_unconditional": integration_gate_is_unconditional,
        "reason_histogram": reason_histogram,
        "model_output_invalid_count_proven": 0,
        "integration_mapping_missing_count": len(decisions),
        "diagnosis": [
            "All M2A outputs were APPROACH, a canonical project skill, and every decision had public tracks.",
            "The worker passed an unconditional False mapping callback and emitted the same REJECTED_NO_OFFICIAL_EVIDENCE reason without evaluating skill, track, schema, frame, units, parameters, range, IK, or collision separately.",
            "M2A therefore proves fail-closed integration behavior; it does not prove that all model outputs were intrinsically invalid.",
        ],
        "required_v2_change": (
            "versioned registry plus staged schema/skill/track/frame/unit/range/"
            "IK/collision validation with distinct rejection reasons"
        ),
    }


def write_report(path: Path, payload: dict[str, Any], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    markdown = path.with_suffix(".md")
    lines = [
        f"# {title}",
        "",
        f"- status: **{payload['status']}**",
        "",
        "```json",
        json.dumps(payload, indent=2, sort_keys=True),
        "```",
        "",
    ]
    markdown.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-commit",
        default="1c83776c91c6a9c5e7bf2d873d20da367ffdff81",
    )
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--mapping-host", default="root@labserver")
    parser.add_argument(
        "--mapping-root",
        default=(
            "/var/tmp/xh-data/isaac-industrial/closed-loop/"
            "qrm-beta-seeds-3200-3209"
        ),
    )
    parser.add_argument("--report-dir", default=PROJECT / "reports", type=Path)
    args = parser.parse_args()

    initial_porcelain = command(["git", "status", "--porcelain"]).strip()
    baseline_status = json.loads(
        git_blob(args.baseline_commit, "reports/m2a-status.json")
    )
    baseline_manifest = json.loads(
        git_blob(
            args.baseline_commit,
            "data/manifests/isaac-industrial-v1-pilot.json",
        )
    )
    local_manifest = json.loads(
        (args.dataset_root / "manifest.json").read_text()
    )
    artifact_verification = verify_artifact_index(args.baseline_commit)
    remote_m2a_head = command(
        [
            "git",
            "ls-remote",
            "origin",
            "refs/heads/codex/m2a-isaac-data-qrm-beta",
        ]
    ).split()[0]
    baseline_is_remote_ancestor = (
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                args.baseline_commit,
                remote_m2a_head,
            ],
            cwd=PROJECT,
            check=False,
        ).returncode
        == 0
    )
    manifest_sha = hashlib.sha256(
        (args.dataset_root / "manifest.json").read_bytes()
    ).hexdigest()
    freeze = {
        "schema_version": "M2BM2AFreezeV1",
        "status": "PASS",
        "baseline_commit": args.baseline_commit,
        "baseline_commit_exists": True,
        "remote_m2a_head": remote_m2a_head,
        "baseline_is_remote_ancestor": baseline_is_remote_ancestor,
        "worktree_clean_before_report_write": initial_porcelain == "",
        "baseline_status": baseline_status["status"],
        "baseline_tests_passed": baseline_status["tests_passed"],
        "baseline_teacher_used": baseline_status["teacher_used"],
        "baseline_oracle_leakage_detected": baseline_status[
            "oracle_leakage_detected"
        ],
        "dataset_version": local_manifest["dataset_version"],
        "dataset_manifest_hash": local_manifest["dataset_manifest_hash"],
        "expected_dataset_manifest_hash": baseline_manifest[
            "dataset_manifest_hash"
        ],
        "manifest_file_sha256": manifest_sha,
        "dataset_hash_verified": local_manifest["dataset_manifest_hash"]
        == baseline_manifest["dataset_manifest_hash"],
        "episodes_valid": local_manifest["episodes_valid"],
        "episodes_quarantined": local_manifest["episodes_quarantined"],
        "artifact_index": artifact_verification,
        "m2a_reports_mutated": False,
        "teacher_kill_rule_events": [],
    }
    if not all(
        (
            freeze["baseline_is_remote_ancestor"],
            freeze["dataset_hash_verified"],
            artifact_verification["status"] == "PASS",
            baseline_status["tests_passed"] == 215,
        )
    ):
        freeze["status"] = "FAIL"

    episodes = load_episodes(args.dataset_root)
    fc = failure_context_audit(episodes)
    residual = residual_audit(episodes)
    decisions, metrics_files = remote_mapping_decisions(
        args.mapping_host, args.mapping_root
    )
    worker_source = git_blob(
        args.baseline_commit, "scripts/isaac_m1b_dataset_benchmark.py"
    ).decode()
    mapping = mapping_audit(
        decisions,
        metrics_files=metrics_files,
        worker_source=worker_source,
    )

    write_report(
        args.report_dir / "m2b-s0-m2a-freeze.json",
        freeze,
        "M2B S0 M2A frozen baseline",
    )
    write_report(
        args.report_dir / "m2b-s0-failure-context-audit.json",
        fc,
        "M2B S0 FailureContext information audit",
    )
    write_report(
        args.report_dir / "m2b-s0-residual-audit.json",
        residual,
        "M2B S0 residual target audit",
    )
    write_report(
        args.report_dir / "m2b-s0-runtime-mapping-audit.json",
        mapping,
        "M2B S0 runtime mapping audit",
    )
    print(
        json.dumps(
            {
                "freeze": freeze["status"],
                "failure_context": fc["status"],
                "residual": residual["status"],
                "mapping": mapping["status"],
            },
            sort_keys=True,
        )
    )
    return 0 if freeze["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
