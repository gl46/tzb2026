#!/usr/bin/env python3
"""Run two official-Isaac M1B dataset workers with serialized Kit startup."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import TextIO


OFFICIAL_ROBOT = "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_gpu_indices(value: str) -> tuple[int, int]:
    try:
        parsed = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("GPU indices must be integers") from error
    if len(parsed) != 2 or len(set(parsed)) != 2 or any(item < 0 for item in parsed):
        raise argparse.ArgumentTypeError(
            "exactly two distinct nonnegative GPU indices are required"
        )
    return parsed


def _worker_command(
    args: argparse.Namespace,
    *,
    worker_id: int,
    gpu_index: int,
    worker_output: Path,
    control: Path,
) -> list[str]:
    sdf_name = args.worker_sdf[worker_id]
    supervision_name = args.worker_supervision[worker_id]
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{args.container_prefix}-worker{worker_id}",
        "--gpus",
        f"device={gpu_index}",
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
        f"{worker_output}:/workspace/output",
        "-v",
        f"{control}:/workspace/control",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        args.image,
        "scripts/isaac_m1b_dataset_benchmark.py",
        "--sdf",
        f"/workspace/source/{sdf_name}",
        "--supervision",
        f"/workspace/source/{supervision_name}",
        "--urdf",
        "/workspace/source/panda_controlled.urdf",
        "--output",
        "/workspace/output",
        "--worker-id",
        str(worker_id),
        "--physical-gpu-index",
        str(gpu_index),
        "--frames",
        str(args.frames),
        "--warmup-frames",
        str(args.warmup_frames),
        "--ready-file",
        f"/workspace/control/worker{worker_id}.READY",
        "--start-file",
        "/workspace/control/START",
        "--barrier-timeout-s",
        str(args.timeout_s),
    ]
    if args.qrm_checkpoint is not None:
        mount_index = command.index("-w")
        command[mount_index:mount_index] = [
            "-v",
            f"{args.qrm_checkpoint.parent}:/workspace/qrm:ro",
        ]
        command.extend(
            [
                "--qrm-checkpoint",
                f"/workspace/qrm/{args.qrm_checkpoint.name}",
                "--qrm-model-id",
                args.qrm_model_id,
            ]
        )
    return command


def parse_smi_csv(text: str) -> list[dict[str, float | int]]:
    samples = []
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 4:
            continue
        try:
            samples.append(
                {
                    "gpu_index": int(fields[0]),
                    "memory_used_mib": float(fields[1]),
                    "utilization_gpu_percent": float(fields[2]),
                    "power_draw_w": float(fields[3]),
                }
            )
        except ValueError:
            continue
    return samples


def _sample_gpus(
    gpu_indices: tuple[int, int],
    samples: list[dict[str, object]],
    *,
    phase: str,
    started: float,
) -> None:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used,utilization.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return
    for sample in parse_smi_csv(completed.stdout):
        if sample["gpu_index"] in gpu_indices:
            samples.append(
                {
                    **sample,
                    "phase": phase,
                    "elapsed_s": time.monotonic() - started,
                }
            )


def summarize_gpu_samples(
    samples: list[dict[str, object]],
    gpu_indices: tuple[int, int],
) -> dict[str, object]:
    summary = {}
    for gpu_index in gpu_indices:
        selected = [
            sample for sample in samples if sample["gpu_index"] == gpu_index
        ]
        if not selected:
            summary[str(gpu_index)] = {"sample_count": 0}
            continue
        memory = [float(sample["memory_used_mib"]) for sample in selected]
        utilization = [
            float(sample["utilization_gpu_percent"]) for sample in selected
        ]
        power = [float(sample["power_draw_w"]) for sample in selected]
        summary[str(gpu_index)] = {
            "sample_count": len(selected),
            "memory_used_mib_peak": max(memory),
            "memory_used_mib_mean": statistics.fmean(memory),
            "utilization_gpu_percent_peak": max(utilization),
            "utilization_gpu_percent_mean": statistics.fmean(utilization),
            "power_draw_w_peak": max(power),
            "power_draw_w_mean": statistics.fmean(power),
        }
    return summary


def _wait_ready(
    process: subprocess.Popen[bytes],
    ready_file: Path,
    *,
    timeout_s: float,
    gpu_indices: tuple[int, int],
    samples: list[dict[str, object]],
    started: float,
    phase: str,
) -> None:
    deadline = time.monotonic() + timeout_s
    while not ready_file.is_file():
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(
                f"{phase} exited before READY with return code {returncode}"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{phase} did not reach READY within {timeout_s}s")
        _sample_gpus(gpu_indices, samples, phase=phase, started=started)
        time.sleep(0.5)


def _load_worker_metrics(
    path: Path,
    *,
    expected_frames: int,
    expected_source_sha256: str,
) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"worker evidence is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    camera_names = [camera["name"] for camera in payload.get("cameras", [])]
    if (
        payload.get("status") != "PASS"
        or payload.get("dataset_benchmark_source_sha256")
        != expected_source_sha256
        or payload.get("frames") != expected_frames
        or payload.get("camera_count") != 4
        or camera_names
        != ["policy_rgbd", "front_rgbd", "overhead_rgbd", "side_rgbd"]
        or payload.get("robot_asset", {}).get("provenance") != OFFICIAL_ROBOT
        or payload.get("robot_asset", {}).get("local_simplified_robot_used")
        is not False
        or payload.get("robot_asset", {}).get("variants")
        != {"Gripper": "Default", "Mesh": "Performance"}
        or payload.get("student_dataset_protocol", {}).get("policy_camera")
        != "policy_rgbd"
        or payload.get("student_dataset_protocol", {}).get(
            "policy_segmentation_input"
        )
        is not False
    ):
        raise RuntimeError(f"worker evidence failed closed validation: {path}")
    return payload


def _open_worker(
    args: argparse.Namespace,
    *,
    worker_id: int,
    gpu_index: int,
    control: Path,
) -> tuple[subprocess.Popen[bytes], TextIO]:
    worker_root = args.output / f"worker{worker_id}"
    worker_output = worker_root / "output"
    worker_output.mkdir(parents=True)
    worker_output.chmod(0o777)
    log = (worker_root / "run.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        _worker_command(
            args,
            worker_id=worker_id,
            gpu_index=gpu_index,
            worker_output=worker_output,
            control=control,
        ),
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return process, log


def _stop_owned_workers(
    processes: list[subprocess.Popen[bytes]],
    *,
    container_prefix: str,
) -> None:
    """Stop only containers created by this runner after a failed launch."""

    for worker_id in range(len(processes)):
        subprocess.run(
            [
                "docker",
                "stop",
                "--time",
                "10",
                f"{container_prefix}-worker{worker_id}",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gpu-indices", type=parse_gpu_indices, default=(0, 1))
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--image", default="nvcr.io/nvidia/isaac-sim:6.0.1")
    parser.add_argument("--container-prefix", default="m1b-isaac-dual-final")
    parser.add_argument("--qrm-checkpoint", type=Path)
    parser.add_argument(
        "--qrm-model-id",
        default="Q2_COARSE_MLP_FAILURE_CONTEXT",
        choices=(
            "Q0_COARSE_ONLY",
            "Q1_COARSE_MLP_RESIDUAL",
            "Q2_COARSE_MLP_FAILURE_CONTEXT",
        ),
    )
    parser.add_argument(
        "--worker-sdf",
        action="append",
        default=[],
        help="source-root-relative SDF; pass exactly twice in worker order",
    )
    parser.add_argument(
        "--worker-supervision",
        action="append",
        default=[],
        help="source-root-relative supervision JSON; pass exactly twice",
    )
    args = parser.parse_args()
    if not args.worker_sdf:
        args.worker_sdf = ["scene-3000.sdf", "scene-3000.sdf"]
    if not args.worker_supervision:
        args.worker_supervision = [
            "scene-3000.supervision.json",
            "scene-3000.supervision.json",
        ]
    if len(args.worker_sdf) != 2 or len(args.worker_supervision) != 2:
        parser.error("--worker-sdf and --worker-supervision require exactly two values")
    for relative in [*args.worker_sdf, *args.worker_supervision]:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            parser.error(f"worker source path must stay under source root: {relative}")
        if not (args.source_root / path).is_file():
            parser.error(f"worker source does not exist: {args.source_root / path}")
    if args.frames <= 0 or args.warmup_frames < 1 or args.timeout_s <= 0:
        parser.error("frame counts and timeout are invalid")
    for required in (args.project_root, args.source_root):
        if not required.is_dir():
            parser.error(f"required directory does not exist: {required}")
    if args.qrm_checkpoint is not None and not args.qrm_checkpoint.is_file():
        parser.error(f"QRM checkpoint does not exist: {args.qrm_checkpoint}")
    dataset_benchmark_path = (
        args.project_root / "scripts" / "isaac_m1b_dataset_benchmark.py"
    )
    if not dataset_benchmark_path.is_file():
        parser.error(
            f"dataset benchmark does not exist: {dataset_benchmark_path}"
        )
    dataset_benchmark_sha256 = _sha256(dataset_benchmark_path)
    dual_runner_sha256 = _sha256(Path(__file__))
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.mkdir(parents=True)
    control = args.output / "control"
    control.mkdir()
    control.chmod(0o777)
    started = time.monotonic()
    samples: list[dict[str, object]] = []
    processes: list[subprocess.Popen[bytes]] = []
    logs: list[TextIO] = []
    failure: str | None = None
    try:
        for worker_id, gpu_index in enumerate(args.gpu_indices):
            process, log = _open_worker(
                args,
                worker_id=worker_id,
                gpu_index=gpu_index,
                control=control,
            )
            processes.append(process)
            logs.append(log)
            _wait_ready(
                process,
                control / f"worker{worker_id}.READY",
                timeout_s=args.timeout_s,
                gpu_indices=args.gpu_indices,
                samples=samples,
                started=started,
                phase=f"worker{worker_id}_initialization",
            )
        (control / "START").touch()
        while any(process.poll() is None for process in processes):
            _sample_gpus(
                args.gpu_indices,
                samples,
                phase="concurrent_capture",
                started=started,
            )
            time.sleep(0.5)
        returncodes = [process.returncode for process in processes]
        worker_metrics = [
            _load_worker_metrics(
                args.output / f"worker{worker_id}" / "output" / "metrics.json",
                expected_frames=args.frames,
                expected_source_sha256=dataset_benchmark_sha256,
            )
            for worker_id in range(2)
        ]
        if any(returncode != 0 for returncode in returncodes):
            raise RuntimeError(f"worker return codes were {returncodes}")
    except BaseException as error:
        failure = f"{type(error).__name__}: {error}"
        _stop_owned_workers(
            processes,
            container_prefix=args.container_prefix,
        )
        worker_metrics = []
        returncodes = [
            process.poll() for process in processes
        ]
    finally:
        for log in logs:
            log.close()

    benchmark_wall_s = max(
        (float(metrics["benchmark_wall_s"]) for metrics in worker_metrics),
        default=0.0,
    )
    combined_sensor_frames = sum(
        int(metrics["sensor_frames"]) for metrics in worker_metrics
    )
    summary = {
        "schema_version": "IsaacM1BDual3080BenchmarkV1",
        "status": "PASS" if failure is None else "FAIL",
        "failure": failure,
        "robot_asset": OFFICIAL_ROBOT,
        "local_simplified_robot_used": False,
        "official_robot_variants": {
            "Gripper": "Default",
            "Mesh": "Performance",
        },
        "dataset_benchmark_source_sha256": dataset_benchmark_sha256,
        "dual_runner_source_sha256": dual_runner_sha256,
        "gpu_indices": list(args.gpu_indices),
        "worker_sources": [
            {
                "worker_id": worker_id,
                "sdf": args.worker_sdf[worker_id],
                "supervision": args.worker_supervision[worker_id],
                "sdf_sha256": _sha256(args.source_root / args.worker_sdf[worker_id]),
                "supervision_sha256": _sha256(
                    args.source_root / args.worker_supervision[worker_id]
                ),
            }
            for worker_id in range(2)
        ],
        "qrm_closed_loop_smoke": {
            "enabled": args.qrm_checkpoint is not None,
            "checkpoint": (
                str(args.qrm_checkpoint)
                if args.qrm_checkpoint is not None
                else None
            ),
            "model_id": (
                args.qrm_model_id
                if args.qrm_checkpoint is not None
                else None
            ),
        },
        "workers": [
            {
                "worker_id": worker_id,
                "returncode": returncodes[worker_id],
                "metrics": str(
                    args.output
                    / f"worker{worker_id}"
                    / "output"
                    / "metrics.json"
                ),
                "metrics_sha256": _sha256(
                    args.output
                    / f"worker{worker_id}"
                    / "output"
                    / "metrics.json"
                ),
                "sensor_frames": metrics["sensor_frames"],
                "sensor_frames_per_s": metrics["sensor_frames_per_s"],
                "benchmark_wall_s": metrics["benchmark_wall_s"],
            }
            for worker_id, metrics in enumerate(worker_metrics)
        ],
        "combined_sensor_frames": combined_sensor_frames,
        "concurrent_benchmark_wall_s": benchmark_wall_s,
        "combined_sensor_frames_per_s": (
            combined_sensor_frames / benchmark_wall_s
            if benchmark_wall_s > 0
            else 0.0
        ),
        "gpu_samples": samples,
        "gpu_summary": summarize_gpu_samples(samples, args.gpu_indices),
        "total_runner_wall_s": time.monotonic() - started,
        "startup_protocol": (
            "SERIALIZED_KIT_INITIALIZATION_THEN_SHARED_START_BARRIER"
        ),
    }
    summary_path = args.output / "dual-benchmark-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "combined_sensor_frames": combined_sensor_frames,
                "combined_sensor_frames_per_s": summary[
                    "combined_sensor_frames_per_s"
                ],
                "summary": str(summary_path),
                "failure": failure,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if failure is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
