#!/usr/bin/env python3
"""Build or run one isolated Isaac dataset worker command."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


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
    ready = args.output / "control" / "worker.READY"
    start = args.output / "control" / "START"
    process = subprocess.Popen(command)
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
            time.sleep(0.25)
        start.touch()
        return process.wait()
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
