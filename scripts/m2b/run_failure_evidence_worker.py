#!/usr/bin/env python3
"""Restart-safe per-GPU worker for diverse held-out M2B failure evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


PUBLIC_COLORS = {
    "red": (0.8, 0.1, 0.1),
    "green": (0.1, 0.7, 0.2),
    "blue": (0.1, 0.2, 0.8),
    "yellow": (0.8, 0.6, 0.1),
    "magenta": (0.7, 0.1, 0.7),
    "cyan": (0.1, 0.7, 0.7),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_selector_entity(sdf: Path, color: str) -> str:
    """Resolve the generator-side entity for public color/world_x=max TaskSpec.

    The entity is used only to configure the physical injection and isolated
    simulator supervision.  Runtime public selection still uses RGB-D tracks.
    """
    wanted = PUBLIC_COLORS[color]
    candidates = []
    root = ET.parse(sdf).getroot()
    for model in root.findall(".//world/model"):
        name = model.get("name") or ""
        if not name.startswith("cylinder_"):
            continue
        pose = [float(value) for value in (model.findtext("pose") or "").split()]
        diffuse = model.findtext(".//visual/material/diffuse")
        if len(pose) < 3 or diffuse is None:
            continue
        rgb = tuple(float(value) for value in diffuse.split()[:3])
        if all(abs(value - expected) <= 1e-6 for value, expected in zip(rgb, wanted)):
            candidates.append((pose[0], name))
    if not candidates:
        raise ValueError(f"scene has no public {color!r} cylinder")
    return max(candidates)[1]


def stage_is_valid(output: Path, *, sdf: Path, supervision: Path) -> bool:
    metrics_path = output / "metrics.json"
    stage_path = output / "m1b_physics_scene.usdc"
    if not metrics_path.is_file() or not stage_path.is_file():
        return False
    metrics = json.loads(metrics_path.read_text())
    hashes = metrics.get("source_hashes", {})
    return bool(
        metrics.get("status") == "PASS"
        and hashes.get(sdf.name) == sha256_file(sdf)
        and hashes.get(supervision.name) == sha256_file(supervision)
        and metrics.get("clean_physics_stage", {}).get("sha256")
        == sha256_file(stage_path)
    )


def stage_command(
    args: argparse.Namespace,
    *,
    sdf: Path,
    supervision: Path,
    output: Path,
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{args.container_prefix}-g{args.gpu}-s{sdf.stem.split('-')[-1]}-stage",
        "--gpus",
        f"device={args.gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{args.project_root}:/workspace/project:ro",
        "-v",
        f"{args.source_root}:/workspace/source:ro",
        "-v",
        f"{output}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        args.image,
        "scripts/isaac_m1b_dataset_benchmark.py",
        "--sdf",
        f"/workspace/source/{sdf.name}",
        "--supervision",
        f"/workspace/source/{supervision.name}",
        "--urdf",
        "/workspace/source/panda_controlled.urdf",
        "--output",
        "/workspace/output",
        "--worker-id",
        str(args.worker_id),
        "--physical-gpu-index",
        str(args.gpu),
        "--frames",
        "1",
        "--warmup-frames",
        "1",
    ]


def ensure_stage(
    args: argparse.Namespace,
    *,
    scene_root: Path,
    sdf: Path,
    supervision: Path,
) -> Path | None:
    for attempt in range(1, args.max_stage_attempts + 1):
        output = scene_root / f"stage-attempt-{attempt:02d}"
        if stage_is_valid(output, sdf=sdf, supervision=supervision):
            return output / "m1b_physics_scene.usdc"
        if output.exists():
            continue
        output.mkdir(parents=True)
        output.chmod(0o777)
        completed = subprocess.run(
            stage_command(
                args,
                sdf=sdf,
                supervision=supervision,
                output=output,
            ),
            capture_output=True,
            text=True,
            check=False,
            timeout=args.stage_timeout_s,
        )
        (output / "console.log").write_text(
            completed.stdout + completed.stderr
        )
        if stage_is_valid(output, sdf=sdf, supervision=supervision):
            return output / "m1b_physics_scene.usdc"
        if attempt < args.max_stage_attempts:
            time.sleep(args.settle_s)
    return None


def failure_command(
    args: argparse.Namespace,
    *,
    failure: str,
    sdf: Path,
    supervision: Path,
    stage: Path,
    output: Path,
    yellow_entity: str,
    red_entity: str,
) -> list[str]:
    return [
        "python3",
        str(args.project_root / "scripts/m2b/run_physical_failure_smoke.py"),
        "--project-root",
        str(args.project_root),
        "--source-root",
        str(args.source_root),
        "--stage",
        str(stage),
        "--sdf",
        str(sdf),
        "--supervision",
        str(supervision),
        "--output-root",
        str(output),
        "--gpu",
        str(args.gpu),
        "--target-object",
        yellow_entity,
        "--public-target-object",
        yellow_entity,
        "--wrong-object-task-target",
        red_entity,
        "--max-attempts",
        str(args.max_failure_attempts),
        "--settle-s",
        str(args.settle_s),
        "--capture-public-rgbd",
        "--release-follow-delta-z-m",
        str(args.release_follow_delta_z_m),
        "--public-regrasp-offset-camera-xyz-m",
        getattr(args, "public_regrasp_offset_camera_xyz_m", "0,0,0"),
        "--container-prefix",
        (
            f"{args.container_prefix}-g{args.gpu}-"
            f"s{sdf.stem.split('-')[-1]}"
        ),
        "--failures",
        failure,
    ]


def write_status(output_root: Path, records: list[dict[str, Any]]) -> None:
    accepted = Counter(
        record["failure_type"]
        for record in records
        if record.get("accepted") is True
    )
    payload = {
        "schema_version": "M2BFailureEvidenceWorkerStatusV1",
        "status": "RUNNING_OR_PARTIAL",
        "records": records,
        "accepted_counts": dict(sorted(accepted.items())),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    temporary = output_root / "worker-status.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(output_root / "worker-status.json")


def load_existing_records(output_root: Path) -> list[dict[str, Any]]:
    path = output_root / "worker-status.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != "M2BFailureEvidenceWorkerStatusV1":
        raise ValueError("unsupported existing failure-worker status")
    if payload.get("teacher_used") is not False:
        raise ValueError("existing failure-worker status is not Teacher-free")
    return [dict(record) for record in payload.get("records", [])]


def accepted_target_reached(
    records: list[dict[str, Any]],
    failures: list[str],
    target: int,
) -> bool:
    if target <= 0:
        return False
    counts = Counter(
        str(record["failure_type"])
        for record in records
        if record.get("accepted") is True and record.get("failure_type")
    )
    return all(counts[failure] >= target for failure in failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--scene-seed", action="append", type=int, required=True)
    parser.add_argument("--gpu", required=True, type=int)
    parser.add_argument("--worker-id", required=True, type=int)
    parser.add_argument(
        "--failures",
        default="EMPTY_GRASP,WRONG_OBJECT,RELEASE_FAILURE",
    )
    parser.add_argument("--max-stage-attempts", type=int, default=2)
    parser.add_argument("--max-failure-attempts", type=int, default=2)
    parser.add_argument("--stage-timeout-s", type=float, default=900.0)
    parser.add_argument("--failure-timeout-s", type=float, default=4000.0)
    parser.add_argument("--settle-s", type=float, default=30.0)
    parser.add_argument(
        "--accepted-target-per-failure",
        type=int,
        default=0,
        help=(
            "Stop this worker after each requested class reaches this many "
            "accepted records; zero consumes the full queue."
        ),
    )
    parser.add_argument("--release-follow-delta-z-m", type=float, default=0.08)
    parser.add_argument("--image", default="nvcr.io/nvidia/isaac-sim:6.0.1")
    parser.add_argument("--container-prefix", default="m2b-evidence")
    args = parser.parse_args()
    failures = [item.strip() for item in args.failures.split(",") if item.strip()]
    allowed = {"EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"}
    if not failures or not set(failures).issubset(allowed):
        parser.error(f"--failures must be a subset of {sorted(allowed)}")
    if args.accepted_target_per_failure < 0:
        parser.error("--accepted-target-per-failure must be nonnegative")
    args.output_root.mkdir(parents=True, exist_ok=True)
    records = load_existing_records(args.output_root)
    recorded_failure_keys = {
        (int(record["scene_seed"]), str(record["failure_type"]))
        for record in records
        if record.get("scene_seed") is not None
        and record.get("failure_type") is not None
    }
    terminal_scene_statuses = {
        int(record["scene_seed"])
        for record in records
        if record.get("scene_seed") is not None
        and record.get("failure_type") is None
        and record.get("status") in {"SOURCE_MISSING", "STAGE_FAILED"}
    }
    for seed in args.scene_seed:
        if accepted_target_reached(
            records, failures, args.accepted_target_per_failure
        ):
            break
        if seed in terminal_scene_statuses:
            continue
        if all((seed, failure) in recorded_failure_keys for failure in failures):
            continue
        sdf = args.source_root / f"scene-{seed}.sdf"
        supervision = args.source_root / f"scene-{seed}.supervision.json"
        if not sdf.is_file() or not supervision.is_file():
            records.append({"scene_seed": seed, "status": "SOURCE_MISSING"})
            terminal_scene_statuses.add(seed)
            write_status(args.output_root, records)
            continue
        scene_root = args.output_root / f"scene-{seed}"
        scene_root.mkdir(parents=True, exist_ok=True)
        stage = ensure_stage(
            args,
            scene_root=scene_root,
            sdf=sdf,
            supervision=supervision,
        )
        if stage is None:
            records.append({"scene_seed": seed, "status": "STAGE_FAILED"})
            terminal_scene_statuses.add(seed)
            write_status(args.output_root, records)
            continue
        yellow_entity = public_selector_entity(sdf, "yellow")
        red_entity = public_selector_entity(sdf, "red")
        for failure in failures:
            if (seed, failure) in recorded_failure_keys:
                continue
            accepted = Counter(
                str(record["failure_type"])
                for record in records
                if record.get("accepted") is True
                and record.get("failure_type")
            )
            if (
                args.accepted_target_per_failure > 0
                and accepted[failure] >= args.accepted_target_per_failure
            ):
                continue
            output = scene_root / "failures" / failure.lower()
            completed = subprocess.run(
                failure_command(
                    args,
                    failure=failure,
                    sdf=sdf,
                    supervision=supervision,
                    stage=stage,
                    output=output,
                    yellow_entity=yellow_entity,
                    red_entity=red_entity,
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=args.failure_timeout_s,
            )
            summary_path = output / "physical-failure-smoke.json"
            summary = (
                json.loads(summary_path.read_text())
                if summary_path.is_file()
                else {}
            )
            accepted_attempts = [
                item for item in summary.get("attempts", []) if item.get("accepted")
            ]
            records.append(
                {
                    "scene_seed": seed,
                    "failure_type": failure,
                    "status": summary.get("status", "NO_SUMMARY"),
                    "accepted": bool(accepted_attempts),
                    "evidence": (
                        accepted_attempts[-1]["evidence"]
                        if accepted_attempts
                        else None
                    ),
                    "evidence_sha256": (
                        accepted_attempts[-1]["evidence_sha256"]
                        if accepted_attempts
                        else None
                    ),
                    "runner_returncode": completed.returncode,
                }
            )
            recorded_failure_keys.add((seed, failure))
            write_status(args.output_root, records)
            time.sleep(args.settle_s)
    payload = json.loads((args.output_root / "worker-status.json").read_text())
    payload["status"] = (
        "COMPLETE_ACCEPTED_TARGET"
        if accepted_target_reached(
            records, failures, args.accepted_target_per_failure
        )
        else "COMPLETE_QUEUE"
    )
    payload["accepted_target_per_failure"] = (
        args.accepted_target_per_failure
    )
    (args.output_root / "worker-status.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
