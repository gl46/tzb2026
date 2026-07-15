"""Read-only local/SSH doctor. Missing optional programs are reported, never fatal."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID = {"FOUND", "MISSING", "UNKNOWN", "ERROR", "NOT_APPLICABLE"}


def _item(status: str, value: str | None = None) -> dict[str, str]:
    assert status in VALID
    result = {"status": status}
    if value:
        result["value"] = value[:500]
    return result


def _run(command: list[str], timeout: int = 4) -> tuple[str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return "MISSING", ""
    except subprocess.TimeoutExpired:
        return "ERROR", "timeout"
    output = (completed.stdout or completed.stderr).strip()
    return ("FOUND" if completed.returncode == 0 else "ERROR"), output


def _program(name: str, version_args: list[str] | None = None) -> dict[str, str]:
    path = shutil.which(name)
    if not path:
        return _item("MISSING")
    if not version_args:
        return _item("FOUND", path)
    status, output = _run([name, *version_args])
    return _item(status, output or path)


def local_doctor() -> dict[str, Any]:
    gpu_status, gpu_value = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_mode", "--format=csv,noheader"])
    items = {
        "os": _item("FOUND", f"{platform.platform()} {platform.machine()}"),
        "kernel": _item("FOUND", platform.release()),
        "cpu": _item("FOUND", f"logical_cores={os.cpu_count() or 'unknown'}"),
        "ram": _item("UNKNOWN"), "swap": _item("UNKNOWN"), "filesystem": _item("FOUND", str(shutil.disk_usage("/"))),
        "nvidia_gpu": _item(gpu_status, gpu_value), "cuda_runtime": _program("nvcc", ["--version"]),
        "gpu_processes": _item("UNKNOWN" if gpu_status != "FOUND" else "FOUND"), "mig": _item("UNKNOWN"), "compute_mode": _item("UNKNOWN"),
        "docker": _program("docker", ["--version"]), "nvidia_container_toolkit": _program("nvidia-container-cli", ["--version"]),
        "python": _program("python3", ["--version"]), "uv": _program("uv", ["--version"]), "git": _program("git", ["--version"]),
        "git_lfs": _program("git-lfs", ["version"]), "ffmpeg": _program("ffmpeg", ["-version"]),
        "ros2": _program("ros2", ["--help"]), "colcon": _program("colcon", ["--version"]), "gazebo_gz": _program("gz", ["--versions"]),
        "ros_gz": _item("UNKNOWN"), "gz_ros2_control": _item("UNKNOWN"), "ros2_control": _item("UNKNOWN"), "moveit2": _item("UNKNOWN"),
        "rviz": _program("rviz2", ["--help"]), "franka_panda_resources": _item("UNKNOWN"), "egl_ogre_headless": _item("UNKNOWN"),
        "network_interfaces": _item("UNKNOWN"), "time_sync_offset": _item("UNKNOWN"), "relevant_environment": _item("FOUND", "only allow-gate names recorded"),
    }
    return {"scope": "local", "generated_at": datetime.now(timezone.utc).isoformat(), "items": items}


def remote_doctor(host: str | None, user: str | None) -> dict[str, Any]:
    if not host:
        return {
            "scope": "remote", "host_alias": None, "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": {"ssh": _item("NOT_APPLICABLE", "REMOTE_NODE_NOT_CONFIGURED")},
        }
    user = user or ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", host) or not re.fullmatch(r"[A-Za-z0-9_.-]+", user):
        raise ValueError("remote host and user must be simple SSH aliases")
    probe = r"""set -e
if [ -f /opt/ros/jazzy/setup.bash ]; then source /opt/ros/jazzy/setup.bash; fi
emit() { printf '%s=%s\n' "$1" "$2"; }
pkg_prefix() { if command -v ros2 >/dev/null 2>&1; then ros2 pkg prefix "$1" 2>/dev/null || true; fi; }
emit os "$(uname -srm) | $(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '\"')"
emit ram "$(free -h 2>/dev/null | awk '/^Mem:/ {print $2 " total, " $7 " available"}')"
emit swap "$(free -h 2>/dev/null | awk '/^Swap:/ {print $2 " total, " $3 " used"}')"
emit filesystem "$(df -h / 2>/dev/null | awk 'NR==2 {print $2 " total, " $4 " available"}')"
emit nvidia_gpu "$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null | paste -sd ';' -)"
emit compute_mode "$(nvidia-smi --query-gpu=compute_mode --format=csv,noheader 2>/dev/null | paste -sd ';' -)"
emit gpu_processes "$(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null | paste -sd ';' -)"
emit mig "$(nvidia-smi -i 0 -q 2>/dev/null | awk -F: '/MIG Mode/ {gsub(/^ +| +$/, "", $2); print $2; exit}')"
emit cuda_runtime "$(command -v nvcc || true)"
emit docker "$(command -v docker || true)"
emit python "$(command -v python3 || true)"
emit git "$(command -v git || true)"
emit git_lfs "$(command -v git-lfs || true)"
emit ffmpeg "$(command -v ffmpeg || true)"
emit ros2 "$(command -v ros2 || true)"
emit colcon "$(command -v colcon || true)"
emit gazebo_gz "$(gz sim --versions 2>/dev/null | head -n 1 || true)"
emit ros_gz "$(pkg_prefix ros_gz_sim)"
emit gz_ros2_control "$(pkg_prefix gz_ros2_control)"
emit ros2_control "$(pkg_prefix controller_manager)"
emit moveit2 "$(pkg_prefix moveit_ros_move_group)"
emit rviz "$(command -v rviz2 || true)"
emit franka_panda_resources "$(pkg_prefix moveit_resources_panda_moveit_config)"
emit egl_ogre_headless "$(command -v gz || true)"
emit network_interfaces "$(ip -brief link 2>/dev/null | awk '{print $1}' | paste -sd ',' -)"
emit time_sync_offset "UNKNOWN"
emit relevant_environment "ROS_DISTRO=${ROS_DISTRO:-unset}; RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-default}"
"""
    status, output = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"{user}@{host}", probe], timeout=12)
    base = {key: _item("UNKNOWN") for key in (
        "os", "ram", "swap", "filesystem", "nvidia_gpu", "cuda_runtime", "gpu_processes", "mig", "compute_mode", "docker", "python", "git", "git_lfs", "ffmpeg", "ros2", "colcon", "gazebo_gz", "ros_gz", "gz_ros2_control", "ros2_control", "moveit2", "rviz", "franka_panda_resources", "egl_ogre_headless", "network_interfaces", "time_sync_offset", "relevant_environment",
    )}
    if status != "FOUND":
        base["ssh"] = _item("ERROR", output)
        return {"scope": "remote", "host_alias": host, "generated_at": datetime.now(timezone.utc).isoformat(), "items": base}
    values = {}
    for line in output.splitlines():
        key, marker, value = line.partition("=")
        if marker:
            values[key.strip()] = value.strip()
    base["ssh"] = _item("FOUND", "BatchMode read-only probe")
    for key in ("os", "ram", "swap", "filesystem", "nvidia_gpu", "compute_mode", "mig", "network_interfaces", "relevant_environment"):
        value = values.get(key, "")
        base[key] = _item("FOUND" if value else "UNKNOWN", value)
    for key in ("cuda_runtime", "docker", "python", "git", "git_lfs", "ffmpeg", "ros2", "colcon", "gazebo_gz", "ros_gz", "gz_ros2_control", "ros2_control", "moveit2", "rviz", "franka_panda_resources", "egl_ogre_headless"):
        value = values.get(key, "")
        base[key] = _item("FOUND" if value else "MISSING", value)
    gpu_processes = values.get("gpu_processes", "")
    base["gpu_processes"] = _item("FOUND" if values.get("nvidia_gpu") else "NOT_APPLICABLE", gpu_processes or "none")
    base["time_sync_offset"] = _item("UNKNOWN", values.get("time_sync_offset"))
    return {"scope": "remote", "host_alias": host, "generated_at": datetime.now(timezone.utc).isoformat(), "items": base}


def main() -> int:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--local", action="store_true")
    scope.add_argument("--remote")
    parser.add_argument("--user")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = local_doctor() if args.local else remote_doctor(args.remote, args.user)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "scope": result["scope"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
