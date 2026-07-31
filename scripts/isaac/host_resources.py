#!/usr/bin/env python3
"""Low-overhead Linux host and GPU sampling for retained Isaac benchmarks."""

from __future__ import annotations

import os
import statistics
import subprocess
from pathlib import Path
from typing import Any


def _cpu_totals() -> tuple[int, int]:
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values) - idle, sum(values)


def _memory_bytes() -> tuple[int, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.split()[0]) * 1024
    return values["MemTotal"], values["MemAvailable"]


def parse_gpu_csv(text: str) -> list[dict[str, float | int]]:
    samples: list[dict[str, float | int]] = []
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


class ResourceMonitor:
    """Sample whole-host pressure and selected physical GPUs."""

    def __init__(self, output_root: Path, gpu_indices: tuple[int, ...]) -> None:
        self.output_root = output_root
        self.gpu_indices = gpu_indices
        self.host_samples: list[dict[str, Any]] = []
        self.gpu_samples: list[dict[str, Any]] = []
        self._previous_cpu: tuple[int, int] | None = None

    def sample(self, *, phase: str, elapsed_s: float) -> None:
        busy, total = _cpu_totals()
        cpu_percent: float | None = None
        if self._previous_cpu is not None:
            previous_busy, previous_total = self._previous_cpu
            total_delta = total - previous_total
            if total_delta > 0:
                cpu_percent = 100.0 * (busy - previous_busy) / total_delta
        self._previous_cpu = (busy, total)
        memory_total, memory_available = _memory_bytes()
        filesystem = os.statvfs(self.output_root)
        self.host_samples.append(
            {
                "phase": phase,
                "elapsed_s": elapsed_s,
                "cpu_utilization_percent": cpu_percent,
                "ram_total_bytes": memory_total,
                "ram_used_bytes": memory_total - memory_available,
                "ram_available_bytes": memory_available,
                "filesystem_available_bytes": (
                    filesystem.f_bavail * filesystem.f_frsize
                ),
            }
        )
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
        for sample in parse_gpu_csv(completed.stdout):
            if int(sample["gpu_index"]) in self.gpu_indices:
                self.gpu_samples.append(
                    {**sample, "phase": phase, "elapsed_s": elapsed_s}
                )


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize_host_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    cpu = [
        float(sample["cpu_utilization_percent"])
        for sample in samples
        if sample.get("cpu_utilization_percent") is not None
    ]
    ram_used = [int(sample["ram_used_bytes"]) for sample in samples]
    ram_available = [int(sample["ram_available_bytes"]) for sample in samples]
    filesystem_available = [
        int(sample["filesystem_available_bytes"]) for sample in samples
    ]
    return {
        "sample_count": len(samples),
        "cpu_utilization_percent_mean": _mean(cpu),
        "cpu_utilization_percent_peak": max(cpu) if cpu else None,
        "ram_used_bytes_mean": _mean([float(value) for value in ram_used]),
        "ram_used_bytes_peak": max(ram_used) if ram_used else None,
        "ram_available_bytes_min": min(ram_available) if ram_available else None,
        "filesystem_available_bytes_min": (
            min(filesystem_available) if filesystem_available else None
        ),
    }


def summarize_gpu_samples(
    samples: list[dict[str, Any]],
    gpu_indices: tuple[int, ...],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for gpu_index in gpu_indices:
        selected = [
            sample for sample in samples if int(sample["gpu_index"]) == gpu_index
        ]
        memory = [float(sample["memory_used_mib"]) for sample in selected]
        utilization = [
            float(sample["utilization_gpu_percent"]) for sample in selected
        ]
        power = [float(sample["power_draw_w"]) for sample in selected]
        summary[str(gpu_index)] = {
            "sample_count": len(selected),
            "memory_used_mib_peak": max(memory) if memory else None,
            "memory_used_mib_mean": _mean(memory),
            "utilization_gpu_percent_peak": max(utilization) if utilization else None,
            "utilization_gpu_percent_mean": _mean(utilization),
            "power_draw_w_peak": max(power) if power else None,
            "power_draw_w_mean": _mean(power),
        }
    return summary


def first_episode_window_growth(
    samples: list[dict[str, Any]],
    *,
    value_key: str,
    episode_count: int,
    capture_wall_s: float,
    window_episodes: int = 100,
    phase: str = "capture",
) -> dict[str, Any]:
    selected = sorted(
        (
            sample
            for sample in samples
            if sample.get("phase") == phase and sample.get(value_key) is not None
        ),
        key=lambda sample: float(sample["elapsed_s"]),
    )
    if not selected or episode_count < window_episodes or capture_wall_s <= 0:
        return {
            "status": "NOT_MEASURED",
            "window_episodes": window_episodes,
            "growth": None,
        }
    start_elapsed = float(selected[0]["elapsed_s"])
    target_elapsed = (
        start_elapsed + capture_wall_s * window_episodes / episode_count
    )
    end = min(
        selected,
        key=lambda sample: abs(float(sample["elapsed_s"]) - target_elapsed),
    )
    start_value = float(selected[0][value_key])
    end_value = float(end[value_key])
    return {
        "status": "MEASURED",
        "window_episodes": window_episodes,
        "start": start_value,
        "end": end_value,
        "growth": end_value - start_value,
        "sample_elapsed_s": float(end["elapsed_s"]) - start_elapsed,
    }
