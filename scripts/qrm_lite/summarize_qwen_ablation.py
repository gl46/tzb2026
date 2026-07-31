#!/usr/bin/env python3
"""Aggregate paired real-data Qwen FailureContext on/off runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    if not str(report.get("status", "")).startswith("PASS"):
        raise ValueError(f"training report did not pass: {path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--off-report", action="append", required=True, type=Path)
    parser.add_argument("--on-report", action="append", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    parser.add_argument("--training-code-revision")
    parser.add_argument("--dataset-manifest-hash")
    parser.add_argument("--configured-base-revision")
    args = parser.parse_args()
    if len(args.off_report) != len(args.on_report):
        raise SystemExit("the number of off/on reports must match")

    pairs = []
    for off_path, on_path in zip(args.off_report, args.on_report):
        off = load(off_path)
        on = load(on_path)
        if off["failure_context"] != "off" or on["failure_context"] != "on":
            raise SystemExit("reports are not an off/on pair")
        matching = ("seed", "n_train", "n_eval", "eval_split", "labels")
        mismatched = [field for field in matching if off[field] != on[field]]
        if mismatched:
            raise SystemExit(f"off/on reports differ in paired fields: {mismatched}")
        pairs.append(
            {
                "seed": off["seed"],
                "off_report": str(off_path),
                "on_report": str(on_path),
                "off_accuracy": off["eval_accuracy"],
                "on_accuracy": on["eval_accuracy"],
                "accuracy_delta": on["eval_accuracy"] - off["eval_accuracy"],
                "off_macro_f1": off["eval_metrics"]["macro_f1"],
                "on_macro_f1": on["eval_metrics"]["macro_f1"],
                "macro_f1_delta": (
                    on["eval_metrics"]["macro_f1"]
                    - off["eval_metrics"]["macro_f1"]
                ),
            }
        )

    accuracy_values = [pair["accuracy_delta"] for pair in pairs]
    macro_f1_values = [pair["macro_f1_delta"] for pair in pairs]
    limitations = [
        "Each paired run uses one epoch, at most 120 train samples, and 50 held-out test samples.",
        "Two seeds on one 550-episode Pilot dataset cannot establish deployment benefit.",
        "Physical EMPTY_GRASP, RELEASE_FAILURE, and WRONG_OBJECT cases are absent.",
    ]
    if not all(value > 0 for value in accuracy_values):
        limitations.append(
            "FailureContext did not improve held-out accuracy for every seed."
        )
    raw_reports = [
        load(report_path)
        for report_path in [*args.off_report, *args.on_report]
    ]
    runtime_revisions = sorted(
        {str(report.get("revision", "")) for report in raw_reports}
    )
    if runtime_revisions == [""]:
        limitations.append(
            "The local Qwen snapshot did not retain Hub revision metadata; "
            "the configured base revision is recorded but not independently "
            "verified by the raw training reports."
        )
    training_source = Path(__file__).with_name("train_qwen_coarse_beta.py")
    report = {
        "schema_version": "M2AQwenFailureContextAblationV1",
        "status": "PASS_WITH_LIMITATIONS",
        "pairs": pairs,
        "accuracy_deltas": {
            "per_seed": {
                str(pair["seed"]): pair["accuracy_delta"] for pair in pairs
            },
            "mean": sum(accuracy_values) / len(accuracy_values),
        },
        "macro_f1_deltas": {
            "per_seed": {
                str(pair["seed"]): pair["macro_f1_delta"] for pair in pairs
            },
            "mean": sum(macro_f1_values) / len(macro_f1_values),
        },
        "limitations": limitations,
        "oracle_policy_inputs": False,
        "teacher_used": False,
        "flow_status": "DISABLED",
        "model_ids": sorted(
            {
                str(report.get("model_id", ""))
                for report in raw_reports
                if report.get("model_id")
            }
        ),
        "runtime_revisions": runtime_revisions,
        "configured_base_revision": args.configured_base_revision,
        "dataset_manifest_hash": args.dataset_manifest_hash,
        "training_code_revision": args.training_code_revision,
        "training_source_sha256": hashlib.sha256(
            training_source.read_bytes()
        ).hexdigest(),
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = [
        "# M2A S4 Qwen FailureContext ablation",
        "",
        "- status: **PASS_WITH_LIMITATIONS**",
        f"- paired seeds: {', '.join(str(pair['seed']) for pair in pairs)}",
        f"- mean accuracy delta (on - off): {report['accuracy_deltas']['mean']:.6f}",
        f"- mean macro-F1 delta (on - off): {report['macro_f1_deltas']['mean']:.6f}",
        f"- Teacher used: `{report['teacher_used']}`",
        f"- dataset manifest hash: `{report['dataset_manifest_hash']}`",
        f"- training code revision: `{report['training_code_revision']}`",
        f"- configured base revision: `{report['configured_base_revision']}`",
        f"- raw runtime revision metadata: `{report['runtime_revisions']}`",
        "",
        "| seed | off accuracy | on accuracy | delta | off macro-F1 | on macro-F1 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        "| {seed} | {off_accuracy:.6f} | {on_accuracy:.6f} | "
        "{accuracy_delta:.6f} | {off_macro_f1:.6f} | {on_macro_f1:.6f} |".format(
            **pair
        )
        for pair in pairs
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in limitations)
    args.report_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
