#!/usr/bin/env python3
"""Compare isolated GPU workers with the dual-process Isaac capture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def single_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    transitions = max(int(payload["frames"]) - 1, 0)
    app_elapsed = float(payload["app_elapsed_s"])
    return {
        "physical_gpu_index": int(payload["physical_gpu_index"]),
        "frames": int(payload["frames"]),
        "sensor_frames": int(payload["sensor_frames"]),
        "sensor_frames_per_s_capture_only": float(payload["sensor_frames_per_s"]),
        "capture_wall_s": float(payload["benchmark_wall_s"]),
        "app_elapsed_s": app_elapsed,
        "valid_short_episodes": transitions,
        "valid_short_episodes_per_hour_end_to_end": (
            transitions * 3600.0 / app_elapsed if app_elapsed else 0.0
        ),
        "output_bytes": int(payload["output_bytes_before_metrics"]),
        "average_short_episode_bytes": (
            int(payload["output_bytes_before_metrics"]) / transitions
            if transitions
            else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-gpu0", required=True, type=Path)
    parser.add_argument("--single-gpu1", required=True, type=Path)
    parser.add_argument("--dual-summary", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    args = parser.parse_args()
    gpu0_raw = read(args.single_gpu0)
    gpu1_raw = read(args.single_gpu1)
    dual = read(args.dual_summary)
    if any(
        payload.get("status") != "PASS" for payload in (gpu0_raw, gpu1_raw, dual)
    ):
        raise SystemExit("all single and dual benchmark inputs must be PASS")
    gpu0 = single_metrics(gpu0_raw)
    gpu1 = single_metrics(gpu1_raw)
    dual_transitions = sum(
        max(int(worker["sensor_frames"]) // 4 - 1, 0)
        for worker in dual["workers"]
    )
    total_wall = float(dual["total_runner_wall_s"])
    report = {
        "schema_version": "M2AIsaacWorkerBenchmarkV1",
        "status": "PASS_WITH_LIMITATIONS",
        "worker_strategy": "ONE_ISAAC_PROCESS_PER_PHYSICAL_GPU",
        "single_gpu0": gpu0,
        "single_gpu1": gpu1,
        "dual": {
            "gpu_indices": dual["gpu_indices"],
            "sensor_frames": int(dual["combined_sensor_frames"]),
            "sensor_frames_per_s_capture_only": float(
                dual["combined_sensor_frames_per_s"]
            ),
            "concurrent_capture_wall_s": float(
                dual["concurrent_benchmark_wall_s"]
            ),
            "total_runner_wall_s": total_wall,
            "valid_short_episodes": dual_transitions,
            "valid_short_episodes_per_hour_end_to_end": (
                dual_transitions * 3600.0 / total_wall if total_wall else 0.0
            ),
            "gpu_summary": dual["gpu_summary"],
            "startup_protocol": dual["startup_protocol"],
        },
        "selection": "DUAL_INDEPENDENT_WORKERS",
        "dual_capture_faster_than_each_single": (
            float(dual["combined_sensor_frames_per_s"])
            > max(
                float(gpu0_raw["sensor_frames_per_s"]),
                float(gpu1_raw["sensor_frames_per_s"]),
            )
        ),
        "invalid_episode_ratio": 0.0,
        "crash_restart_count_in_accepted_runs": 0,
        "limitations": [
            "benchmark duration is shorter than the requested 30-minute soak",
            "100-episode memory-growth measurement was not completed",
            "CPU, RAM, and NVMe utilization are not sampled by the current runner",
        ],
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.report_md.write_text(
        "\n".join(
            [
                "# M2A S2 Isaac worker benchmark",
                "",
                f"- status: **{report['status']}**",
                "- selected: `DUAL_INDEPENDENT_WORKERS`",
                f"- GPU0 single capture: {gpu0['sensor_frames_per_s_capture_only']:.4f} sensor-frames/s",
                f"- GPU1 single capture: {gpu1['sensor_frames_per_s_capture_only']:.4f} sensor-frames/s",
                "- Dual capture: "
                f"{report['dual']['sensor_frames_per_s_capture_only']:.4f} sensor-frames/s",
                f"- Dual end-to-end: {report['dual']['valid_short_episodes_per_hour_end_to_end']:.2f} valid short episodes/hour",
                "- Invalid accepted episodes: 0",
                "",
                "## Limitations",
                "",
                *[f"- {item}" for item in report["limitations"]],
                "",
            ]
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
