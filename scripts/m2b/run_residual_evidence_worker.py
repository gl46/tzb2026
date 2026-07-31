#!/usr/bin/env python3
"""Run independent public-action perturbations against accepted corrections."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from m2b.run_failure_evidence_worker import (
        failure_command,
        public_selector_entity,
        stage_is_valid,
    )
except ModuleNotFoundError:
    from run_failure_evidence_worker import (
        failure_command,
        public_selector_entity,
        stage_is_valid,
    )


PERTURBATION_MAGNITUDES = (
    (0.002, 0.002, 0.001),
    (0.006, 0.006, 0.003),
    (0.015, 0.015, 0.005),
)


def perturbation_for_seed(seed: int) -> tuple[float, float, float]:
    magnitude = PERTURBATION_MAGNITUDES[seed % len(PERTURBATION_MAGNITUDES)]
    signs = (
        -1.0 if seed & 1 else 1.0,
        -1.0 if seed & 2 else 1.0,
        -1.0 if seed & 4 else 1.0,
    )
    return tuple(sign * value for sign, value in zip(signs, magnitude))


def accepted_correction(summary_path: Path) -> dict[str, Any] | None:
    if not summary_path.is_file():
        return None
    summary = json.loads(summary_path.read_text())
    accepted = [
        attempt
        for attempt in summary.get("attempts", [])
        if attempt.get("accepted") is True
        and attempt.get("evidence")
        and attempt.get("evidence_sha256")
    ]
    return accepted[-1] if accepted else None


def valid_stage(
    scene_root: Path, *, sdf: Path, supervision: Path
) -> Path | None:
    for attempt in sorted(scene_root.glob("stage-attempt-*")):
        if stage_is_valid(attempt, sdf=sdf, supervision=supervision):
            return attempt / "m1b_physics_scene.usdc"
    return None


def write_status(output_root: Path, records: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": "M2BResidualEvidenceWorkerStatusV1",
        "status": "RUNNING_OR_PARTIAL",
        "records": records,
        "pairs_ready": sum(record.get("pair_ready") is True for record in records),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    temporary = output_root / "worker-status.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(output_root / "worker-status.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--failure-worker-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--scene-seed", action="append", type=int, required=True)
    parser.add_argument("--gpu", required=True, type=int)
    parser.add_argument("--worker-id", required=True, type=int)
    parser.add_argument("--settle-s", type=float, default=10.0)
    parser.add_argument("--timeout-s", type=float, default=4000.0)
    parser.add_argument("--image", default="nvcr.io/nvidia/isaac-sim:6.0.1")
    parser.add_argument("--container-prefix", default="m2b-residual")
    args = parser.parse_args()
    args.max_failure_attempts = 1
    args.release_follow_delta_z_m = 0.08
    args.output_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for seed in args.scene_seed:
        sdf = args.source_root / f"scene-{seed}.sdf"
        supervision = args.source_root / f"scene-{seed}.supervision.json"
        failure_scene = args.failure_worker_root / f"scene-{seed}"
        correction = accepted_correction(
            failure_scene
            / "failures/wrong_object/physical-failure-smoke.json"
        )
        stage = valid_stage(
            failure_scene, sdf=sdf, supervision=supervision
        )
        if correction is None or stage is None:
            records.append(
                {
                    "scene_seed": seed,
                    "status": "CORRECTION_OR_STAGE_UNAVAILABLE",
                    "pair_ready": False,
                }
            )
            write_status(args.output_root, records)
            continue
        offset = perturbation_for_seed(seed)
        args.public_regrasp_offset_camera_xyz_m = ",".join(
            f"{value:.6f}" for value in offset
        )
        args.container_prefix = f"m2b-residual-g{args.gpu}-s{seed}"
        output = args.output_root / f"scene-{seed}/perturbed"
        output.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            failure_command(
                args,
                failure="WRONG_OBJECT",
                sdf=sdf,
                supervision=supervision,
                stage=stage,
                output=output,
                yellow_entity=public_selector_entity(sdf, "yellow"),
                red_entity=public_selector_entity(sdf, "red"),
            ),
            capture_output=True,
            text=True,
            check=False,
            timeout=args.timeout_s,
        )
        (output / "worker-console.log").write_text(
            completed.stdout + completed.stderr
        )
        summary_path = output / "physical-failure-smoke.json"
        summary = (
            json.loads(summary_path.read_text())
            if summary_path.is_file()
            else {}
        )
        evidence_attempts = [
            attempt
            for attempt in summary.get("attempts", [])
            if attempt.get("evidence") and attempt.get("evidence_sha256")
        ]
        perturbed = evidence_attempts[-1] if evidence_attempts else None
        records.append(
            {
                "scene_seed": seed,
                "status": "PAIR_READY" if perturbed else "NO_PERTURBED_EVIDENCE",
                "pair_ready": perturbed is not None,
                "perturbation_camera_xyz_m": list(offset),
                "perturbed_evidence": (
                    perturbed["evidence"] if perturbed else None
                ),
                "perturbed_evidence_sha256": (
                    perturbed["evidence_sha256"] if perturbed else None
                ),
                "corrected_evidence": correction["evidence"],
                "corrected_evidence_sha256": correction["evidence_sha256"],
                "runner_returncode": completed.returncode,
            }
        )
        write_status(args.output_root, records)
        time.sleep(args.settle_s)
    payload = json.loads((args.output_root / "worker-status.json").read_text())
    payload["status"] = "COMPLETE_QUEUE"
    (args.output_root / "worker-status.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
