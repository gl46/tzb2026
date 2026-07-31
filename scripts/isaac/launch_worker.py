#!/usr/bin/env python3
"""Build or run one isolated Isaac dataset worker command."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from host_resources import (
    ResourceMonitor,
    first_episode_window_growth,
    summarize_gpu_samples,
    summarize_host_samples,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sdf", required=True)
    parser.add_argument("--supervision", required=True)
    parser.add_argument("--worker-id", required=True, type=int)
    parser.add_argument("--gpu", required=True, type=int)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    for relative in (args.sdf, args.supervision, "panda_controlled.urdf"):
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            parser.error(f"source path escapes source root: {relative}")
    command = [
        "docker", "run", "--rm", "--gpus", f"device={args.gpu}",
        "-e", "ACCEPT_EULA=Y", "-e", "PRIVACY_CONSENT=Y",
        "-e", "PYTHONPATH=/workspace/project/src",
        "-v", f"{args.project_root}:/workspace/project:ro",
        "-v", f"{args.source_root}:/workspace/source:ro",
        "-v", f"{args.output}:/workspace/output",
        "-w", "/workspace/project", "--entrypoint", "/isaac-sim/python.sh",
        "nvcr.io/nvidia/isaac-sim:6.0.1",
        "scripts/isaac_m1b_dataset_benchmark.py",
        "--sdf", f"/workspace/source/{args.sdf}",
        "--supervision", f"/workspace/source/{args.supervision}",
        "--urdf", "/workspace/source/panda_controlled.urdf",
        "--output", "/workspace/output",
        "--worker-id", str(args.worker_id),
        "--physical-gpu-index", str(args.gpu),
        "--frames", str(args.frames),
        "--warmup-frames", str(args.warmup_frames),
        "--ready-file", "/workspace/output/control/worker.READY",
        "--start-file", "/workspace/output/control/START",
        "--barrier-timeout-s", str(args.timeout_s),
    ]
    if args.dry_run:
        print(json.dumps({"worker_id": args.worker_id, "gpu": args.gpu, "command": command}))
        return 0
    args.output.mkdir(parents=True, exist_ok=False)
    args.output.chmod(0o777)
    ready = args.output / "control" / "worker.READY"
    start = args.output / "control" / "START"
    process = subprocess.Popen(command)
    started = time.monotonic()
    monitor = ResourceMonitor(args.output, (args.gpu,))
    deadline = time.monotonic() + args.timeout_s
    try:
        while not ready.is_file():
            returncode = process.poll()
            if returncode is not None:
                return returncode
            if time.monotonic() >= deadline:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return 124
            monitor.sample(
                phase="initialization",
                elapsed_s=time.monotonic() - started,
            )
            time.sleep(0.25)
        start.touch()
        while process.poll() is None:
            monitor.sample(
                phase="capture",
                elapsed_s=time.monotonic() - started,
            )
            time.sleep(0.5)
        returncode = int(process.returncode)
        metrics_path = args.output / "metrics.json"
        if metrics_path.is_file():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            transitions = max(int(metrics.get("frames", 0)) - 1, 0)
            capture_wall_s = float(metrics.get("benchmark_wall_s", 0.0))
            selected_gpu = [
                sample
                for sample in monitor.gpu_samples
                if int(sample["gpu_index"]) == args.gpu
            ]
            resource_report = {
                "schema_version": "M2AHostResourceEvidenceV1",
                "status": "PASS" if returncode == 0 else "FAIL",
                "gpu_index": args.gpu,
                "host_summary": summarize_host_samples(monitor.host_samples),
                "gpu_summary": summarize_gpu_samples(
                    monitor.gpu_samples,
                    (args.gpu,),
                ),
                "host_samples": monitor.host_samples,
                "gpu_samples": monitor.gpu_samples,
                "memory_growth_first_100_episodes": {
                    "host_ram_bytes": first_episode_window_growth(
                        monitor.host_samples,
                        value_key="ram_used_bytes",
                        episode_count=transitions,
                        capture_wall_s=capture_wall_s,
                    ),
                    "gpu_vram_mib": first_episode_window_growth(
                        selected_gpu,
                        value_key="memory_used_mib",
                        episode_count=transitions,
                        capture_wall_s=capture_wall_s,
                    ),
                },
            }
            (args.output / "host-resource-evidence.json").write_text(
                json.dumps(resource_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return returncode
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
