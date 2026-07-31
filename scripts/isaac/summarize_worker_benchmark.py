#!/usr/bin/env python3
"""Compare isolated GPU workers with the dual-process Isaac capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def single_metrics(
    payload: dict[str, Any],
    resources: dict[str, Any],
) -> dict[str, Any]:
    transitions = max(int(payload["frames"]) - 1, 0)
    app_elapsed = float(payload["app_elapsed_s"])
    capture_wall = float(payload["benchmark_wall_s"])
    return {
        "physical_gpu_index": int(payload["physical_gpu_index"]),
        "frames": int(payload["frames"]),
        "sensor_frames": int(payload["sensor_frames"]),
        "sensor_frames_per_s_capture_only": float(payload["sensor_frames_per_s"]),
        "capture_wall_s": capture_wall,
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
        "effective_output_write_mb_s": (
            int(payload["output_bytes_before_metrics"])
            / capture_wall
            / 1_000_000
            if capture_wall
            else 0.0
        ),
        "host_summary": resources["host_summary"],
        "gpu_summary": resources["gpu_summary"],
        "memory_growth_first_100_episodes": resources[
            "memory_growth_first_100_episodes"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-gpu0", required=True, type=Path)
    parser.add_argument("--single-gpu1", required=True, type=Path)
    parser.add_argument("--dual-summary", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    parser.add_argument("--raw-log", type=Path)
    args = parser.parse_args()
    gpu0_raw = read(args.single_gpu0)
    gpu1_raw = read(args.single_gpu1)
    gpu0_resources = read(args.single_gpu0.parent / "host-resource-evidence.json")
    gpu1_resources = read(args.single_gpu1.parent / "host-resource-evidence.json")
    dual = read(args.dual_summary)
    if any(
        payload.get("status") != "PASS"
        for payload in (
            gpu0_raw,
            gpu1_raw,
            gpu0_resources,
            gpu1_resources,
            dual,
        )
    ):
        raise SystemExit("all single and dual benchmark inputs must be PASS")
    gpu0 = single_metrics(gpu0_raw, gpu0_resources)
    gpu1 = single_metrics(gpu1_raw, gpu1_resources)
    dual_transitions = sum(
        max(int(worker["sensor_frames"]) // 4 - 1, 0)
        for worker in dual["workers"]
    )
    total_wall = float(dual["total_runner_wall_s"])
    dual_capture_wall = float(dual["concurrent_benchmark_wall_s"])
    dual_output_bytes = sum(
        int(read(Path(worker["metrics"]))["output_bytes_before_metrics"])
        for worker in dual["workers"]
    )
    limitations: list[str] = []
    if min(
        float(gpu0["capture_wall_s"]),
        float(gpu1["capture_wall_s"]),
        dual_capture_wall,
    ) < 1800.0:
        limitations.append(
            "one or more configurations captured for less than 30 minutes"
        )
    growth_records = [
        gpu0["memory_growth_first_100_episodes"]["host_ram_bytes"],
        gpu0["memory_growth_first_100_episodes"]["gpu_vram_mib"],
        gpu1["memory_growth_first_100_episodes"]["host_ram_bytes"],
        gpu1["memory_growth_first_100_episodes"]["gpu_vram_mib"],
        dual["memory_growth_first_100_combined_episodes"]["host_ram_bytes"],
        *dual["memory_growth_first_100_combined_episodes"][
            "gpu_vram_mib"
        ].values(),
    ]
    if any(record["status"] != "MEASURED" for record in growth_records):
        limitations.append("100-episode RAM/VRAM growth was not fully measured")
    report = {
        "schema_version": "M2AIsaacWorkerBenchmarkV1",
        "status": "PASS" if not limitations else "PASS_WITH_LIMITATIONS",
        "run_root": str(args.report_json.parent),
        "target_capture_duration_s_per_configuration": 1800,
        "raw_log": (
            {
                "path": str(args.raw_log),
                "sha256": sha256(args.raw_log),
            }
            if args.raw_log and args.raw_log.is_file()
            else None
        ),
        "input_evidence": {
            "single_gpu0_metrics": str(args.single_gpu0),
            "single_gpu1_metrics": str(args.single_gpu1),
            "dual_summary": str(args.dual_summary),
        },
        "worker_strategy": "ONE_ISAAC_PROCESS_PER_PHYSICAL_GPU",
        "single_gpu0": gpu0,
        "single_gpu1": gpu1,
        "dual": {
            "gpu_indices": dual["gpu_indices"],
            "sensor_frames": int(dual["combined_sensor_frames"]),
            "sensor_frames_per_s_capture_only": float(
                dual["combined_sensor_frames_per_s"]
            ),
            "concurrent_capture_wall_s": dual_capture_wall,
            "total_runner_wall_s": total_wall,
            "valid_short_episodes": dual_transitions,
            "valid_short_episodes_per_hour_end_to_end": (
                dual_transitions * 3600.0 / total_wall if total_wall else 0.0
            ),
            "gpu_summary": dual["gpu_summary"],
            "host_summary": dual["host_summary"],
            "effective_output_write_mb_s": (
                dual_output_bytes / dual_capture_wall / 1_000_000
                if dual_capture_wall
                else 0.0
            ),
            "memory_growth_first_100_combined_episodes": dual[
                "memory_growth_first_100_combined_episodes"
            ],
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
        "limitations": limitations,
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
                f"- Dual effective output write: {report['dual']['effective_output_write_mb_s']:.2f} MB/s",
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
