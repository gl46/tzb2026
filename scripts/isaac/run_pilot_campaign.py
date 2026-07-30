#!/usr/bin/env python3
"""Run resumable pairs of real Isaac workers over distinct scene seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def valid_prior(run_root: Path, expected: list[Path]) -> bool:
    summary_path = run_root / "dual-benchmark-summary.json"
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text())
    except json.JSONDecodeError:
        return False
    sources = summary.get("worker_sources", [])
    return (
        summary.get("status") == "PASS"
        and len(sources) == 2
        and all((run_root / f"worker{i}" / "output" / "metrics.json").is_file() for i in range(2))
        and [item.get("sdf_sha256") for item in sources]
        == [sha256(expected[0]), sha256(expected[2])]
        and [item.get("supervision_sha256") for item in sources]
        == [sha256(expected[1]), sha256(expected[3])]
    )


def quarantine_failed_run(run_root: Path, *, attempt: int) -> Path:
    quarantine_root = run_root.parent / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    attempt_number = attempt
    destination = quarantine_root / f"{run_root.name}-attempt-{attempt_number:02d}"
    while destination.exists():
        attempt_number += 1
        destination = quarantine_root / (
            f"{run_root.name}-attempt-{attempt_number:02d}"
        )
    run_root.replace(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--dataset-version", default="isaac-industrial-v1-pilot")
    parser.add_argument("--seed-start", type=int, default=3100)
    parser.add_argument("--scene-count", type=int, default=50)
    parser.add_argument("--frames-per-scene", type=int, default=12)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--max-infrastructure-attempts", type=int, default=6)
    parser.add_argument(
        "--infrastructure-settle-s",
        type=float,
        default=120.0,
        help="wait before each Isaac launch so the prior driver/container teardown settles",
    )
    parser.add_argument("--timeout-s", type=float, default=900.0)
    args = parser.parse_args()
    if args.scene_count < 2 or args.scene_count % 2:
        parser.error("--scene-count must be an even number >=2")
    if args.frames_per_scene < 2:
        parser.error("--frames-per-scene must be >=2")
    raw_root = args.data_root / args.dataset_version / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    campaign_path = raw_root / "campaign.json"
    pairs = [
        (args.seed_start + offset, args.seed_start + offset + 1)
        for offset in range(0, args.scene_count, 2)
    ]
    if args.max_runs is not None:
        pairs = pairs[: args.max_runs]
    records: list[dict] = []
    started = time.monotonic()
    for pair_index, (seed0, seed1) in enumerate(pairs):
        run_root = raw_root / f"seeds-{seed0}-{seed1}"
        files = [
            args.source_root / f"scene-{seed0}.sdf",
            args.source_root / f"scene-{seed0}.supervision.json",
            args.source_root / f"scene-{seed1}.sdf",
            args.source_root / f"scene-{seed1}.supervision.json",
        ]
        missing = [str(path) for path in files if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"missing generated scene files: {missing}")
        resumed = valid_prior(run_root, files)
        quarantined: list[str] = []
        if not resumed:
            for attempt in range(1, args.max_infrastructure_attempts + 1):
                if run_root.exists():
                    quarantined.append(
                        str(quarantine_failed_run(run_root, attempt=attempt))
                    )
                if args.infrastructure_settle_s > 0:
                    time.sleep(args.infrastructure_settle_s)
                command = [
                    sys.executable,
                    str(args.project_root / "scripts" / "run_isaac_m1b_dual_benchmark.py"),
                    "--project-root",
                    str(args.project_root),
                    "--source-root",
                    str(args.source_root),
                    "--output",
                    str(run_root),
                    "--frames",
                    str(args.frames_per_scene),
                    "--warmup-frames",
                    str(args.warmup_frames),
                    "--timeout-s",
                    str(args.timeout_s),
                    "--container-prefix",
                    f"m2a-{seed0}-{seed1}-a{attempt}",
                    "--worker-sdf",
                    files[0].name,
                    "--worker-sdf",
                    files[2].name,
                    "--worker-supervision",
                    files[1].name,
                    "--worker-supervision",
                    files[3].name,
                ]
                completed = subprocess.run(command, check=False)
                if completed.returncode == 0 and valid_prior(run_root, files):
                    break
            else:
                raise RuntimeError(
                    f"dual worker exhausted infrastructure retries for seeds {seed0}/{seed1}"
                )
        records.append(
            {
                "pair_index": pair_index,
                "seeds": [seed0, seed1],
                "run_root": str(run_root),
                "resumed": resumed,
                "quarantined_attempts": quarantined,
                "status": "PASS",
            }
        )
        atomic_json(
            campaign_path,
            {
                "schema_version": "M2AIsaacPilotCampaignV1",
                "status": "RUNNING" if len(records) < len(pairs) else "PASS",
                "dataset_version": args.dataset_version,
                "scene_count_requested": args.scene_count,
                "scene_count_completed": len(records) * 2,
                "frames_per_scene": args.frames_per_scene,
                "expected_short_episodes": len(records) * 2 * (args.frames_per_scene - 1),
                "elapsed_s": time.monotonic() - started,
                "runs": records,
            },
        )
        print(json.dumps(records[-1], sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
