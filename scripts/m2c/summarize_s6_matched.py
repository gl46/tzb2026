#!/usr/bin/env python3
"""Summarize the pre-registered four-method M2C S6 matched evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
from typing import Any

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    Method,
    M2BClosedLoopEpisodeV1,
    fc_gain_over_b0,
    summarize_matched,
)


EXPECTED_METHODS: tuple[Method, ...] = (
    "B0",
    "QRM_COARSE_NO_FC",
    "QRM_COARSE_FC",
    "QRM_COARSE_FC_MLP",
)
MINIMUM_MATCHED_KEYS = 30
MINIMUM_MODEL_DECISIONS_EXECUTED = 50
BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 20_260_812
DEFAULT_PREREGISTRATION = (
    Path(__file__).resolve().parents[2] / "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md"
)


def _nearest_rank(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot take a percentile of an empty sample")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(probability * len(ordered) + 0.999999999999)))
    return ordered[rank - 1]


def paired_bootstrap_difference(
    pairs: list[tuple[bool, bool]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Return a deterministic percentile CI for first-minus-second success."""

    if not pairs:
        raise ValueError("paired bootstrap requires at least one matched key")
    if resamples < 1:
        raise ValueError("paired bootstrap requires a positive resample count")
    rng = random.Random(seed)
    count = len(pairs)
    differences = []
    for _ in range(resamples):
        total = 0
        for _ in range(count):
            first, second = pairs[rng.randrange(count)]
            total += int(first) - int(second)
        differences.append(total / count)
    point = sum(int(first) - int(second) for first, second in pairs) / count
    return {
        "estimate": point,
        "confidence_level": 0.95,
        "interval": [
            _nearest_rank(differences, 0.025),
            _nearest_rank(differences, 0.975),
        ],
        "method": "PAIRED_NONPARAMETRIC_BOOTSTRAP_PERCENTILE",
        "resamples": resamples,
        "seed": seed,
        "matched_keys": count,
        "discordance": {
            "first_only_success": sum(first and not second for first, second in pairs),
            "second_only_success": sum(second and not first for first, second in pairs),
            "both_success": sum(first and second for first, second in pairs),
            "neither_success": sum(not first and not second for first, second in pairs),
        },
    }


def _complete_outcomes(
    episodes: list[M2BClosedLoopEpisodeV1],
) -> dict[str, dict[str, bool]]:
    by_key: dict[str, dict[str, bool]] = {}
    duplicate_methods: set[str] = set()
    for episode in episodes:
        outcomes = by_key.setdefault(episode.matched_key, {})
        if episode.method in outcomes:
            duplicate_methods.add(episode.matched_key)
        outcomes[episode.method] = episode.final_success
    expected = set(EXPECTED_METHODS)
    return {
        key: outcomes
        for key, outcomes in by_key.items()
        if key not in duplicate_methods and set(outcomes) == expected
    }


def _method_pairs(
    outcomes: dict[str, dict[str, bool]],
    first: Method,
    second: Method,
) -> list[tuple[bool, bool]]:
    return [(outcomes[key][first], outcomes[key][second]) for key in sorted(outcomes)]


def summarize_s6(
    episodes: list[M2BClosedLoopEpisodeV1],
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    base = summarize_matched(episodes, expected_methods=EXPECTED_METHODS)
    findings = list(base["findings"])
    complete_outcomes = _complete_outcomes(episodes)
    complete_keys = len(complete_outcomes)
    qrm_executed = int(base["qrm_model_decisions_executed"])
    violations = sum(
        int(metrics["collision_or_safety_violations"])
        for metrics in base["method_metrics"].values()
    )
    receipt_episodes: dict[str, set[str]] = {}
    for episode in episodes:
        for decision in episode.decisions:
            digest = decision.gate_evidence_sha256.get("execution_outcome")
            if digest is not None:
                receipt_episodes.setdefault(digest, set()).add(episode.episode_id)
    reused_receipts = {
        digest: sorted(episode_ids)
        for digest, episode_ids in receipt_episodes.items()
        if len(episode_ids) > 1
    }
    if reused_receipts:
        findings.append(
            f"execution outcome receipts reused across episodes: {sorted(reused_receipts)}"
        )
    if complete_keys < MINIMUM_MATCHED_KEYS:
        findings.append(f"complete matched keys {complete_keys} < {MINIMUM_MATCHED_KEYS}")
    if qrm_executed < MINIMUM_MODEL_DECISIONS_EXECUTED:
        findings.append(
            "physically executed model decisions "
            f"{qrm_executed} < {MINIMUM_MODEL_DECISIONS_EXECUTED}"
        )
    if violations:
        findings.append(f"collision or safety violations: {violations}")

    primary = None
    secondary_fc_over_no_fc = None
    secondary_mlp_over_b0 = None
    if complete_outcomes:
        primary = paired_bootstrap_difference(
            _method_pairs(
                complete_outcomes,
                "QRM_COARSE_FC",
                "B0",
            ),
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        primary["name"] = "fc_gain_over_b0"
        primary["estimate_crosscheck"] = fc_gain_over_b0(
            float(base["method_metrics"]["QRM_COARSE_FC"]["final_task_success_rate"]),
            float(base["method_metrics"]["B0"]["final_task_success_rate"]),
        )
        secondary_fc_over_no_fc = paired_bootstrap_difference(
            _method_pairs(
                complete_outcomes,
                "QRM_COARSE_FC",
                "QRM_COARSE_NO_FC",
            ),
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        secondary_fc_over_no_fc["name"] = "fc_gain_over_no_fc"
        secondary_mlp_over_b0 = paired_bootstrap_difference(
            _method_pairs(
                complete_outcomes,
                "QRM_COARSE_FC_MLP",
                "B0",
            ),
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        secondary_mlp_over_b0["name"] = "fc_mlp_gain_over_b0"

    formal_ready = not findings
    return {
        "schema_version": "M2CS6MatchedEvaluationReportV1",
        "status": (
            "PASS_M2C_S6_FORMAL_MATCHED_EVALUATION"
            if formal_ready
            else "IN_PROGRESS_NOT_M2C_S6_FORMAL"
        ),
        "expected_methods": list(EXPECTED_METHODS),
        "episodes": len(episodes),
        "matched_keys": int(base["matched_keys"]),
        "complete_matched_keys": complete_keys,
        "minimum_complete_matched_keys": MINIMUM_MATCHED_KEYS,
        "qrm_model_decisions_executed": qrm_executed,
        "minimum_model_decisions_executed": MINIMUM_MODEL_DECISIONS_EXECUTED,
        "collision_or_safety_violations": violations,
        "reused_execution_outcome_receipts": reused_receipts,
        "method_metrics": base["method_metrics"],
        "primary_metric": primary,
        "secondary_metrics": [
            metric
            for metric in (
                secondary_fc_over_no_fc,
                secondary_mlp_over_b0,
            )
            if metric is not None
        ],
        "findings": findings,
        "formal_evaluation_ready": formal_ready,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=DEFAULT_PREREGISTRATION,
    )
    args = parser.parse_args()
    episodes = [
        M2BClosedLoopEpisodeV1.model_validate_json(line)
        for line in args.episodes.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = summarize_s6(episodes)
    report.update(
        {
            "episodes_path": str(args.episodes),
            "episodes_sha256": hashlib.sha256(args.episodes.read_bytes()).hexdigest(),
            "preregistration_path": str(args.preregistration),
            "preregistration_sha256": hashlib.sha256(args.preregistration.read_bytes()).hexdigest(),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["formal_evaluation_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
