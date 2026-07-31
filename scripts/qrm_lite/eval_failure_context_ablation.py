#!/usr/bin/env python3
"""Core Beta-1 ablation: Q1 (no FailureContext) vs Q2 (with FailureContext)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from xh_agent.policy.qrm_lite.contracts import QRMTrainingSampleV1
from xh_agent.policy.qrm_lite.metrics_beta1 import (
    RecoveryEvent,
    compare_q1_q2,
    macro_f1,
    recovery_top1_accuracy,
    skill_accuracy,
)
from xh_agent.policy.qrm_lite.models_q012 import (
    FormalModelId,
    FormalPolicy,
    load_formal_checkpoint,
)
from xh_agent.policy.qrm_lite.recovery_loop import EmptyGraspRecoveryProtocol, RecoveryLoopConfig
from xh_agent.policy.qrm_lite.transforms import build_identity_action_chunk


def load_samples(path: Path) -> list[QRMTrainingSampleV1]:
    return [
        QRMTrainingSampleV1.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def offline_recovery_events(model: FormalPolicy, samples: list[QRMTrainingSampleV1]) -> list[RecoveryEvent]:
    events = []
    for s in samples:
        if s.observation.failure_context.failure_type.value == "NONE":
            continue
        prev = s.observation.failure_context.last_skill or "GRASP"
        # if last action summary contains family, keep skill token
        if s.observation.failure_context.last_action_summary:
            prev = s.observation.failure_context.last_action_summary.split(":", 1)[0]
        out = model.predict(s.observation, nominal=np.asarray(s.nominal_action_chunk.values))
        chosen = out.recovery_skill or (out.coarse.skill_type if out.coarse else "ABORT_SAFE")
        events.append(
            RecoveryEvent(
                episode_id=s.episode_id,
                failure_type=s.observation.failure_context.failure_type.value,
                previous_action=prev if prev in {"RETRY_TOP", "GRASP"} else "RETRY_TOP",
                chosen_action=chosen,
                model_id=model.model_id.value,
            )
        )
    return events


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Q1 vs Q2 FailureContext ablation")
    p.add_argument("--dataset", default="data/qrm_lite/manifests/real-v1.jsonl")
    p.add_argument("--q1-ckpt", default="artifacts/qrm_lite/beta1/Q1.npz")
    p.add_argument("--q2-ckpt", default="artifacts/qrm_lite/beta1/Q2.npz")
    p.add_argument("--report", default="reports/qrm-lite-beta1-failure-context-ablation.md")
    p.add_argument("--report-json", default="reports/qrm-lite-beta1-failure-context-ablation.json")
    p.add_argument("--run-dry-loop", action="store_true", default=True)
    args = p.parse_args(argv)

    samples = load_samples(Path(args.dataset))
    val = [s for s in samples if s.split in {"val", "test"}] or samples
    fail_samples = [s for s in val if s.observation.failure_context.failure_type.value != "NONE"]

    q1_path = Path(args.q1_ckpt)
    q2_path = Path(args.q2_ckpt)
    q1 = (
        load_formal_checkpoint(str(q1_path))
        if q1_path.exists()
        else FormalPolicy(FormalModelId.Q1)
    )
    q2 = (
        load_formal_checkpoint(str(q2_path))
        if q2_path.exists()
        else FormalPolicy(FormalModelId.Q2)
    )

    def skill_eval(model: FormalPolicy):
        y_true = [s.coarse_intent.skill_type for s in fail_samples]
        y_pred = []
        for s in fail_samples:
            out = model.predict(s.observation, nominal=build_identity_action_chunk(4))
            y_pred.append(out.recovery_skill or (out.coarse.skill_type if out.coarse else ""))
        return {
            "recovery_top1": recovery_top1_accuracy(y_true, y_pred),
            "skill_accuracy": skill_accuracy(y_true, y_pred),
            "macro_f1": macro_f1(y_true, y_pred),
            "n_fail_samples": len(fail_samples),
        }

    e1 = offline_recovery_events(q1, fail_samples)
    e2 = offline_recovery_events(q2, fail_samples)
    # For untrained heads, dry recovery loop still exercises protocol metrics path
    loop = EmptyGraspRecoveryProtocol(q1, q2).run_suite(RecoveryLoopConfig(n_q1=10, n_q2=10))

    report = {
        "primary_comparison": "Q1_no_failure_context vs Q2_with_failure_context",
        "not_compared": "MLP vs Flow (Flow is IMPLEMENTED_NOT_SELECTED)",
        "q1_offline": skill_eval(q1),
        "q2_offline": skill_eval(q2),
        "offline_repetition": compare_q1_q2(e1, e2),
        "dry_recovery_loop": {
            "q1_vs_q2": loop["q1_vs_q2"],
            "moveit_reject_rate": loop["moveit_reject_rate"],
            "mean_attempts": loop["mean_attempts"],
        },
        "headline_metric": "same_failed_action_repetition_rate",
        "interpretation_guide": {
            "good": "Q2 reduces same-failed-action repetition vs Q1 and improves recovery top-1",
            "example": "Q1 42% repeat top grasp after empty-grasp → Q2 18% with more side/oblique/reobserve",
        },
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path(args.report).write_text(
        "\n".join(
            [
                "# Beta-1 FailureContext ablation (Q1 vs Q2)",
                "",
                "Primary question: does FailureContext reduce same-failed-action repetition?",
                "",
                f"- offline repetition: `{json.dumps(report['offline_repetition'])}`",
                f"- dry loop q1 vs q2: `{json.dumps(report['dry_recovery_loop']['q1_vs_q2'])}`",
                f"- q1 offline: `{json.dumps(report['q1_offline'])}`",
                f"- q2 offline: `{json.dumps(report['q2_offline'])}`",
                "",
                "Flow is not part of this comparison.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
