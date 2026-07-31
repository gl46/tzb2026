#!/usr/bin/env python3
"""Package independently executed perturbation/correction evidence pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
        ["ssh", "-o", "BatchMode=yes", host, "cat", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot read {host}:{path}: {completed.stderr}")
    return json.loads(completed.stdout)


def remote_sha256(host: str, path: str) -> str:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "sha256sum", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.split()[0]


def _execution(payload: dict[str, Any]) -> dict[str, Any]:
    execution = payload["m2b_recovery"]["wrong_object"]["regrasp_execution"]
    if execution["public_action_input"].get("simulator_truth_used") is not False:
        raise ValueError("residual execution consumed simulator truth")
    return execution


def build_pair(
    perturbed: dict[str, Any],
    corrected: dict[str, Any],
    *,
    perturbed_path: str,
    corrected_path: str,
    perturbed_sha256: str,
    corrected_sha256: str,
) -> dict[str, Any]:
    if perturbed["scene_seed"] != corrected["scene_seed"]:
        raise ValueError("residual executions use different scene seeds")
    if perturbed["source_hashes"] != corrected["source_hashes"]:
        raise ValueError("residual executions use different scene assets")
    perturbed_execution = _execution(perturbed)
    corrected_execution = _execution(corrected)
    perturbed_input = perturbed_execution["public_action_input"]
    corrected_input = corrected_execution["public_action_input"]
    if (
        perturbed_input.get("controlled_offset_coordinate_frame")
        != "m2b_policy_rgbd_optical"
        or corrected_input.get("controlled_offset_coordinate_frame")
        != "m2b_policy_rgbd_optical"
    ):
        raise ValueError("residual action frame is missing or ambiguous")
    offset = [
        float(value)
        for value in perturbed_input["controlled_offset_camera_xyz_m"]
    ]
    corrected_offset = [
        float(value)
        for value in corrected_input["controlled_offset_camera_xyz_m"]
    ]
    if any(abs(value) > 1e-12 for value in corrected_offset):
        raise ValueError("corrected execution must use zero controlled offset")
    if not (
        0.002 <= abs(offset[0]) <= 0.015
        and 0.002 <= abs(offset[1]) <= 0.015
        and 0.001 <= abs(offset[2]) <= 0.005
    ):
        raise ValueError("perturbation is outside the M2B camera-frame envelope")
    target_delta = math.dist(
        perturbed_input["target_world_m"], corrected_input["target_world_m"]
    )
    if target_delta > 0.01:
        raise ValueError("public target estimates differ by more than 10 mm")
    if not perturbed_execution.get("attempts"):
        raise ValueError("perturbed action was not physically attempted")
    correction_success = bool(
        corrected_execution.get("status") == "LIFTED"
        and float(corrected_execution.get("object_lift_m", 0.0)) >= 0.05
        and float(corrected_execution.get("follow_error_m", 1.0)) <= 0.02
    )
    nominal = [*offset, *([0.0] * 6), 1.0]
    corrected_action = [0.0, 0.0, 0.0, *([0.0] * 6), 1.0]
    residual = [
        target - source
        for source, target in zip(nominal, corrected_action)
    ]
    pair = ResidualCorrectionPairV2(
        dimension_names=DIMENSIONS,
        perturbed_nominal=nominal,
        corrected_action=corrected_action,
        residual_target=residual,
        perturbation_xyz_m=offset,
        correction_physically_successful=correction_success,
    )
    return {
        "pair_id": (
            f"m2b-residual-{perturbed['scene_seed']}-"
            f"{perturbed_sha256[:12]}"
        ),
        "scene_seed": int(perturbed["scene_seed"]),
        **pair.model_dump(mode="json"),
        "physical_correction_evidence": {
            "independent_executions": True,
            "perturbed_evidence_path": perturbed_path,
            "perturbed_evidence_sha256": perturbed_sha256,
            "perturbed_execution_status": perturbed_execution["status"],
            "corrected_evidence_path": corrected_path,
            "corrected_evidence_sha256": corrected_sha256,
            "corrected_object_lift_m": corrected_execution["object_lift_m"],
            "corrected_follow_error_m": corrected_execution["follow_error_m"],
            "public_target_estimate_delta_m": target_delta,
            "policy_input_simulator_truth": False,
        },
        "teacher_used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument(
        "--pair",
        action="append",
        default=[],
        help="PERTURBED_EVIDENCE,CORRECTED_EVIDENCE remote paths",
    )
    parser.add_argument(
        "--remote-worker-status",
        action="append",
        default=[],
        help="Remote M2BResidualEvidenceWorkerStatusV1 path.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    requested_pairs = list(args.pair)
    for status_path in args.remote_worker_status:
        status = remote_json(args.host, status_path)
        requested_pairs.extend(
            f"{record['perturbed_evidence']},{record['corrected_evidence']}"
            for record in status.get("records", [])
            if record.get("pair_ready") is True
        )
    if not requested_pairs:
        raise SystemExit("no residual evidence pairs were supplied")
    pairs = []
    quarantine = []
    for item in requested_pairs:
        perturbed_path, corrected_path = item.split(",", 1)
        try:
            perturbed_digest = remote_sha256(args.host, perturbed_path)
            corrected_digest = remote_sha256(args.host, corrected_path)
            pairs.append(
                build_pair(
                    remote_json(args.host, perturbed_path),
                    remote_json(args.host, corrected_path),
                    perturbed_path=perturbed_path,
                    corrected_path=corrected_path,
                    perturbed_sha256=perturbed_digest,
                    corrected_sha256=corrected_digest,
                )
            )
        except (
            KeyError,
            RuntimeError,
            subprocess.SubprocessError,
            ValueError,
        ) as error:
            quarantine.append(
                {
                    "perturbed_evidence_path": perturbed_path,
                    "corrected_evidence_path": corrected_path,
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(pair, sort_keys=True) + "\n" for pair in pairs)
    )
    args.quarantine.parent.mkdir(parents=True, exist_ok=True)
    args.quarantine.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in quarantine)
    )
    pair_nonzero_fraction = sum(
        any(abs(value) > 1e-12 for value in pair["residual_target"])
        for pair in pairs
    ) / max(len(pairs), 1)
    report = {
        "schema_version": "M2BResidualPairsReportV1",
        "status": (
            "PASS_INFORMATIVE_RESIDUAL_TARGETS"
            if len(pairs) >= 50 and pair_nonzero_fraction >= 0.3
            else "IN_PROGRESS_RESIDUAL_PAIR_SCALE"
        ),
        "valid_pairs": len(pairs),
        "quarantined_pairs": len(quarantine),
        "unique_physical_correction_anchors": len(
            {pair["physical_correction_evidence"]["corrected_evidence_sha256"] for pair in pairs}
        ),
        "nonzero_pair_fraction": pair_nonzero_fraction,
        "all_targets_reconstructible": True,
        "training_only_privileged_label": True,
        "online_policy_truth_input": False,
        "teacher_used": False,
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if pairs else 1


if __name__ == "__main__":
    raise SystemExit(main())
