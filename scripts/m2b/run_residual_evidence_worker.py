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


def perturbations_for_scene(seed: int, count: int) -> tuple[tuple[float, float, float], ...]:
    if count < 1 or count > 6:
        raise ValueError("perturbations per scene must be in [1, 6]")
    offsets = tuple(
        # Seven is coprime with the 24 sign/magnitude combinations, so a
        # scene window rotates through the entire bounded schedule instead
        # of collapsing to a small subset across seeds.
        perturbation_for_seed(seed * 7 + index + 1)
        for index in range(count)
    )
    if len(set(offsets)) != len(offsets):
        raise ValueError("scene perturbation schedule is not unique")
    return offsets


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


def perturbed_action_attempted(evidence_path: Path) -> bool:
    if not evidence_path.is_file():
        return False
    try:
        payload = json.loads(evidence_path.read_text())
        execution = payload["m2b_recovery"]["wrong_object"]["regrasp_execution"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False
    return bool(execution.get("attempts"))


def revalidate_pair_ready_records(records: list[dict[str, Any]]) -> int:
    changed = 0
    for record in records:
        if record.get("pair_ready") is not True:
            continue
        evidence = record.get("perturbed_evidence")
        if evidence and perturbed_action_attempted(Path(str(evidence))):
            continue
        record["pair_ready"] = False
        record["status"] = "PERTURBED_ACTION_NOT_ATTEMPTED"
        changed += 1
    return changed


def valid_stage(scene_root: Path, *, sdf: Path, supervision: Path) -> Path | None:
    for attempt in sorted(scene_root.glob("stage-attempt-*")):
        if stage_is_valid(attempt, sdf=sdf, supervision=supervision):
            return attempt / "m1b_physics_scene.usdc"
    return None


def write_status(
    output_root: Path,
    records: list[dict[str, Any]],
    *,
    pair_target: int,
    perturbations_per_scene: int,
) -> None:
    pairs_ready = sum(record.get("pair_ready") is True for record in records)
    payload = {
        "schema_version": "M2BResidualEvidenceWorkerStatusV1",
        "status": "RUNNING_OR_PARTIAL",
        "records": records,
        "pairs_ready": pairs_ready,
        "pair_target": pair_target,
        "pairs_remaining": max(pair_target - pairs_ready, 0),
        "perturbations_per_scene": perturbations_per_scene,
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
    parser.add_argument("--perturbations-per-scene", type=int, default=3)
    parser.add_argument("--pair-target", type=int, default=30)
    parser.add_argument(
        "--revalidate-only",
        action="store_true",
        help="Revalidate existing pair-ready records without running Isaac.",
    )
    parser.add_argument("--image", default="nvcr.io/nvidia/isaac-sim:6.0.1")
    parser.add_argument("--container-prefix", default="m2b-residual")
    args = parser.parse_args()
    args.max_failure_attempts = 1
    args.release_follow_delta_z_m = 0.08
    args.output_root.mkdir(parents=True, exist_ok=True)
    if not 1 <= args.perturbations_per_scene <= 6:
        parser.error("--perturbations-per-scene must be in [1, 6]")
    if args.pair_target < 1:
        parser.error("--pair-target must be positive")
    status_path = args.output_root / "worker-status.json"
    if status_path.is_file():
        existing = json.loads(status_path.read_text())
        if existing.get("schema_version") != "M2BResidualEvidenceWorkerStatusV1":
            raise ValueError("unsupported existing residual-worker status")
        if existing.get("teacher_used") is not False:
            raise ValueError("existing residual-worker status is not Teacher-free")
        records = [dict(record) for record in existing.get("records", [])]
    else:
        records = []
    revalidated = revalidate_pair_ready_records(records)
    if revalidated:
        write_status(
            args.output_root,
            records,
            pair_target=args.pair_target,
            perturbations_per_scene=args.perturbations_per_scene,
        )
    if args.revalidate_only:
        if not status_path.is_file():
            write_status(
                args.output_root,
                records,
                pair_target=args.pair_target,
                perturbations_per_scene=args.perturbations_per_scene,
            )
        payload = json.loads(status_path.read_text())
        payload["status"] = "REVALIDATED_PARTIAL"
        payload["records_reclassified"] = revalidated
        status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    recorded_keys = {
        (int(record["scene_seed"]), int(record["perturbation_index"]))
        for record in records
        if record.get("scene_seed") is not None and record.get("perturbation_index") is not None
    }
    for seed in args.scene_seed:
        if sum(record.get("pair_ready") is True for record in records) >= args.pair_target:
            break
        sdf = args.source_root / f"scene-{seed}.sdf"
        supervision = args.source_root / f"scene-{seed}.supervision.json"
        failure_scene = args.failure_worker_root / f"scene-{seed}"
        correction = accepted_correction(
            failure_scene / "failures/wrong_object/physical-failure-smoke.json"
        )
        stage = valid_stage(failure_scene, sdf=sdf, supervision=supervision)
        if correction is None or stage is None:
            if (seed, 0) not in recorded_keys:
                records.append(
                    {
                        "scene_seed": seed,
                        "status": "CORRECTION_OR_STAGE_UNAVAILABLE",
                        "pair_ready": False,
                        "perturbation_index": 0,
                    }
                )
                recorded_keys.add((seed, 0))
                write_status(
                    args.output_root,
                    records,
                    pair_target=args.pair_target,
                    perturbations_per_scene=args.perturbations_per_scene,
                )
            continue
        for perturbation_index, offset in enumerate(
            perturbations_for_scene(seed, args.perturbations_per_scene),
            start=1,
        ):
            if sum(record.get("pair_ready") is True for record in records) >= args.pair_target:
                break
            if (seed, perturbation_index) in recorded_keys:
                continue
            args.public_regrasp_offset_camera_xyz_m = ",".join(f"{value:.6f}" for value in offset)
            args.container_prefix = f"m2b-residual-g{args.gpu}-s{seed}-p{perturbation_index}"
            output = args.output_root / (f"scene-{seed}/perturbation-{perturbation_index:02d}")
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
            (output / "worker-console.log").write_text(completed.stdout + completed.stderr)
            summary_path = output / "physical-failure-smoke.json"
            summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
            evidence_attempts = [
                attempt
                for attempt in summary.get("attempts", [])
                if attempt.get("evidence")
                and attempt.get("evidence_sha256")
                and perturbed_action_attempted(Path(str(attempt["evidence"])))
            ]
            perturbed = evidence_attempts[-1] if evidence_attempts else None
            records.append(
                {
                    "scene_seed": seed,
                    "perturbation_index": perturbation_index,
                    "status": ("PAIR_READY" if perturbed else "NO_PERTURBED_EVIDENCE"),
                    "pair_ready": perturbed is not None,
                    "perturbation_camera_xyz_m": list(offset),
                    "perturbed_evidence": (perturbed["evidence"] if perturbed else None),
                    "perturbed_evidence_sha256": (
                        perturbed["evidence_sha256"] if perturbed else None
                    ),
                    "corrected_evidence": correction["evidence"],
                    "corrected_evidence_sha256": correction["evidence_sha256"],
                    "runner_returncode": completed.returncode,
                }
            )
            recorded_keys.add((seed, perturbation_index))
            write_status(
                args.output_root,
                records,
                pair_target=args.pair_target,
                perturbations_per_scene=args.perturbations_per_scene,
            )
            time.sleep(args.settle_s)
    payload = json.loads((args.output_root / "worker-status.json").read_text())
    payload["status"] = (
        "COMPLETE_PAIR_TARGET"
        if int(payload.get("pairs_ready", 0)) >= args.pair_target
        else "COMPLETE_QUEUE"
    )
    (args.output_root / "worker-status.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
