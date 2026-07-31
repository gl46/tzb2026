#!/usr/bin/env python3
"""Aggregate matched two-seed M2B FailureContext coarse experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize(
    off_reports: list[dict], on_reports: list[dict], *, dataset_sha256: str
) -> dict:
    if len(off_reports) != len(on_reports) or len(off_reports) < 2:
        raise ValueError("M2B ablation requires at least two matched report pairs")
    pairs = []
    for off, on in zip(off_reports, on_reports):
        if off["failure_context"] != "off" or on["failure_context"] != "on":
            raise ValueError("reports are not an FC off/on pair")
        for field in ("seed", "n_train", "n_eval", "eval_split", "labels"):
            if off[field] != on[field]:
                raise ValueError(f"paired reports disagree on {field}")
        if not str(off["status"]).startswith("PASS") or not str(
            on["status"]
        ).startswith("PASS"):
            raise ValueError("a paired training run did not pass")
        pairs.append(
            {
                "seed": off["seed"],
                "n_train": off["n_train"],
                "n_eval": off["n_eval"],
                "off_accuracy": off["eval_accuracy"],
                "on_accuracy": on["eval_accuracy"],
                "accuracy_delta": on["eval_accuracy"] - off["eval_accuracy"],
                "off_macro_f1": off["eval_metrics"]["macro_f1"],
                "on_macro_f1": on["eval_metrics"]["macro_f1"],
                "macro_f1_delta": (
                    on["eval_metrics"]["macro_f1"]
                    - off["eval_metrics"]["macro_f1"]
                ),
                "failure_context_sanity": on.get(
                    "failure_context_sanity", {}
                ),
            }
        )
    accuracy_deltas = [pair["accuracy_delta"] for pair in pairs]
    macro_f1_deltas = [pair["macro_f1_delta"] for pair in pairs]
    pipeline_verified = all(
        pair["failure_context_sanity"].get("status")
        == "PASS_FIELDS_MASKED_AND_PERMUTED"
        and pair["failure_context_sanity"].get("masked_inputs_changed")
        == pair["n_eval"]
        and pair["failure_context_sanity"].get(
            "permuted_inputs_changed"
        )
        == pair["n_eval"]
        for pair in pairs
    )
    sensitivity_observed = all(
        pair["failure_context_sanity"].get(
            "model_sensitivity_observed"
        )
        is True
        for pair in pairs
    )
    directionally_positive = all(
        value > 0.0 for value in accuracy_deltas
    ) and all(value > 0.0 for value in macro_f1_deltas)
    supported = (
        pipeline_verified
        and sensitivity_observed
        and directionally_positive
    )
    interpretation = (
        "FC_PIPELINE_SANITY_FAILED"
        if not pipeline_verified
        else "FC_MODEL_SENSITIVITY_NOT_OBSERVED"
        if not sensitivity_observed
        else "FC_DIRECTIONALLY_POSITIVE_ACROSS_SEEDS"
        if directionally_positive
        else "FC_NOT_DIRECTIONALLY_POSITIVE_ACROSS_SEEDS"
    )
    return {
        "schema_version": "M2BCoarseFailureContextAblationV1",
        "status": "PASS_ABLATION_COMPLETE",
        "dataset_sha256": dataset_sha256,
        "pairs": pairs,
        "mean_accuracy_delta": sum(accuracy_deltas) / len(accuracy_deltas),
        "mean_macro_f1_delta": sum(macro_f1_deltas) / len(macro_f1_deltas),
        "failure_context_pipeline_verified": pipeline_verified,
        "failure_context_model_sensitivity_observed": (
            sensitivity_observed
        ),
        "failure_context_supported_offline": supported,
        "interpretation": interpretation,
        "formal_ablation": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--off-report", action="append", required=True, type=Path)
    parser.add_argument("--on-report", action="append", required=True, type=Path)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = summarize(
        [json.loads(path.read_text()) for path in args.off_report],
        [json.loads(path.read_text()) for path in args.on_report],
        dataset_sha256=args.dataset_sha256,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
