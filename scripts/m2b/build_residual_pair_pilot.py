#!/usr/bin/env python3
"""Build nondegenerate residual-pair pilots from a successful public B0 grasp."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

from xh_agent.data_engine.isaac.failure_rich import ResidualCorrectionPairV2


DIMENSIONS = [
    "dx",
    "dy",
    "dz",
    "r6d_0",
    "r6d_1",
    "r6d_2",
    "r6d_3",
    "r6d_4",
    "r6d_5",
    "gripper",
]


def remote_json(host: str, path: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, f"cat '{path}'"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot read {host}:{path}: {completed.stderr}")
    return json.loads(completed.stdout)


def build_pairs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recovery = payload["m2b_recovery"]["wrong_object"]
    execution = recovery["regrasp_execution"]
    if not (
        recovery.get("training_eligible") is True
        and execution.get("status") == "LIFTED"
        and execution.get("public_action_input", {}).get(
            "simulator_truth_used"
        )
        is False
        and float(execution.get("object_lift_m", 0.0)) >= 0.05
        and float(execution.get("follow_error_m", 1.0)) <= 0.02
    ):
        raise ValueError("residual pilot requires a successful public B0 correction")
    perturbations = [
        (sx * xy, sy * xy, sz * z)
        for xy, z in ((0.002, 0.001), (0.006, 0.003), (0.015, 0.005))
        for sx, sy, sz in itertools.product((-1.0, 1.0), repeat=3)
    ]
    pairs = []
    for index, perturbation in enumerate(perturbations):
        nominal = [*perturbation, *([0.0] * 6), 1.0]
        corrected = [0.0, 0.0, 0.0, *([0.0] * 6), 1.0]
        residual = [
            target - source for source, target in zip(nominal, corrected)
        ]
        pair = ResidualCorrectionPairV2(
            dimension_names=DIMENSIONS,
            perturbed_nominal=nominal,
            corrected_action=corrected,
            residual_target=residual,
            perturbation_xyz_m=list(perturbation),
            correction_physically_successful=True,
        )
        pairs.append(
            {
                "pair_id": f"m2b-residual-pilot-{index:04d}",
                **pair.model_dump(mode="json"),
                "physical_correction_evidence": {
                    "public_action_input": execution["public_action_input"],
                    "object_lift_m": execution["object_lift_m"],
                    "follow_error_m": execution["follow_error_m"],
                    "shared_pilot_anchor": True,
                },
            }
        )
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    payload = remote_json(args.host, args.evidence)
    pairs = build_pairs(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in pairs)
    )
    residual_values = [
        value for pair in pairs for value in pair["residual_target"]
    ]
    report = {
        "schema_version": "M2BResidualPairPilotReportV1",
        "status": "PASS_NONDEGENERATE_PILOT_NOT_SCALE",
        "valid_pairs": len(pairs),
        "unique_physical_correction_anchors": 1,
        "nonzero_pair_count": sum(
            any(abs(value) > 1e-12 for value in pair["residual_target"])
            for pair in pairs
        ),
        "translation_min_m": min(
            abs(value)
            for pair in pairs
            for value in pair["perturbation_xyz_m"]
        ),
        "translation_max_m": max(
            abs(value)
            for pair in pairs
            for value in pair["perturbation_xyz_m"]
        ),
        "residual_absolute_max": max(abs(value) for value in residual_values),
        "all_targets_reconstructible": True,
        "training_only_privileged_label": True,
        "online_policy_truth_input": False,
        "sufficient_for_training": False,
        "reason": "pilot pairs share one physical correction anchor; independent perturbation/correction executions remain required",
        "output_path": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "teacher_used": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
