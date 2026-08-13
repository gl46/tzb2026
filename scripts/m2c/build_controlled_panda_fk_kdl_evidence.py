#!/usr/bin/env python3
"""Build and run the independent node2 KDL FK comparison create-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

EVIDENCE_SCHEMA_VERSION = "M2CControlledPandaFKKDLEvidenceV1"
VERIFIER_REPO_PATH = "scripts/m2c/controlled_panda_fk_kdl_verifier_v1.cpp"
CONTROLLED_PANDA_URDF_PATH = "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
CONTROLLED_PANDA_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
EXECUTOR_JOINT_NAMES = tuple(
    [f"panda_joint{index}" for index in range(1, 8)]
    + ["panda_finger_joint1", "panda_finger_joint2"]
)
EXPECTED_COLLISION_LINKS = (
    "panda_hand",
    "panda_leftfinger",
    "panda_link0",
    "panda_link1",
    "panda_link2",
    "panda_link3",
    "panda_link4",
    "panda_link5",
    "panda_link6",
    "panda_link7",
    "panda_link8",
    "panda_rightfinger",
)
EXPECTED_LINK_PATHS = tuple(f"/World/Robot/{name}" for name in EXPECTED_COLLISION_LINKS)
FROZEN_STATES = (
    (0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0, 0.02, 0.02),
    (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.02, 0.02),
    (-2.5, -1.5, -2.5, -3.0, -2.5, 0.0, -2.5, 0.0, 0.0),
    (2.5, 1.5, 2.5, 0.0, 2.5, 3.5, 2.5, 0.04, 0.04),
    (0.3, -1.1, 1.4, -2.2, -0.9, 2.4, 0.7, 0.0, 0.0),
    (-0.7, 0.8, -1.2, -0.5, 1.6, 0.4, -2.0, 0.04, 0.04),
    (1.9, -1.3, 0.6, -2.8, 2.1, 3.2, -1.5, 0.01, 0.01),
    (-2.2, 1.4, -2.0, -1.0, -1.7, 0.2, 2.3, 0.035, 0.035),
    (0.001, -0.002, 0.003, -0.004, 0.005, 0.006, -0.007, 0.015, 0.015),
    (2.8973, 1.7628, -2.8973, -3.0718, 2.8973, -0.0175, 2.8973, 0.04, 0.04),
    (-2.8973, -1.7628, 2.8973, 0.0175, -2.8973, 3.7525, -2.8973, 0.0, 0.0),
    (1.234, -0.987, 0.456, -2.345, -1.111, 2.222, 0.333, 0.027, 0.027),
)
KDL_PARSER_LIBRARY = {
    "path": "/opt/ros/jazzy/lib/libkdl_parser.so",
    "sha256": "3eeabbfcc1a565dd02d04739a05fd126381df77523d0dfbe1dcb10e23061cad5",
}
OROCOS_KDL_LIBRARY = {
    "path": "/usr/lib/x86_64-linux-gnu/liborocos-kdl.so.1.5.1",
    "sha256": "c826b6c210d0ab1fcdfb64503fabbe7158e85103fb7a91d03eee881d5206a5ba",
}
COMPILER = {
    "path": "/usr/bin/x86_64-linux-gnu-g++-11",
    "sha256": "f844ef5aa5bf42cf748cb98fede125791729c6e0c4f640709736104771413fac",
    "version": "x86_64-linux-gnu-g++-11 (Ubuntu 11.4.0-9ubuntu1) 11.4.0",
}
INCLUDE_FLAGS = (
    "-I/usr/include/eigen3",
    "-I/opt/ros/jazzy/include/kdl_parser",
    "-I/opt/ros/jazzy/include/urdf",
    "-I/opt/ros/jazzy/include/urdfdom_headers",
    "-I/opt/ros/jazzy/include/rcutils",
    "-I/opt/ros/jazzy/include/ament_index_cpp",
    "-I/opt/ros/jazzy/include/rcpputils",
    "-I/opt/ros/jazzy/include/class_loader",
)
ROS_LIBRARY_PATHS = (
    "/opt/ros/jazzy/opt/gz_sim_vendor/lib",
    "/opt/ros/jazzy/opt/gz_sensors_vendor/lib",
    "/opt/ros/jazzy/opt/gz_physics_vendor/lib",
    "/opt/ros/jazzy/opt/sdformat_vendor/lib",
    "/opt/ros/jazzy/opt/rviz_ogre_vendor/lib",
    "/opt/ros/jazzy/lib/x86_64-linux-gnu",
    "/opt/ros/jazzy/opt/gz_gui_vendor/lib",
    "/opt/ros/jazzy/opt/gz_transport_vendor/lib",
    "/opt/ros/jazzy/opt/gz_rendering_vendor/lib",
    "/opt/ros/jazzy/opt/gz_plugin_vendor/lib",
    "/opt/ros/jazzy/opt/gz_fuel_tools_vendor/lib",
    "/opt/ros/jazzy/opt/gz_msgs_vendor/lib",
    "/opt/ros/jazzy/opt/gz_common_vendor/lib",
    "/opt/ros/jazzy/opt/gz_math_vendor/lib",
    "/opt/ros/jazzy/opt/gz_utils_vendor/lib",
    "/opt/ros/jazzy/opt/gz_tools_vendor/lib",
    "/opt/ros/jazzy/opt/gz_ogre_next_vendor/lib",
    "/opt/ros/jazzy/opt/gz_dartsim_vendor/lib",
    "/opt/ros/jazzy/opt/gz_cmake_vendor/lib",
    "/opt/ros/jazzy/lib",
)


class KDLBuildFailure(RuntimeError):
    """The node2 KDL source/runtime closure or query failed closed."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise KDLBuildFailure(f"independent FK input is not regular: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise KDLBuildFailure(f"independent FK input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _require_binding(binding: dict[str, str]) -> None:
    if _sha256(read_regular_file_once(Path(binding["path"]))) != binding["sha256"]:
        raise KDLBuildFailure(f"independent FK dependency digest differs: {binding['path']}")


def _write_create_only(path: Path, payload: bytes, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise KDLBuildFailure(f"short write while publishing: {path}")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _run(argv: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            check=True,
            close_fds=True,
            env={
                "PATH": "/usr/bin:/bin:/opt/ros/jazzy/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "LD_LIBRARY_PATH": ":".join(ROS_LIBRARY_PATHS),
                "AMENT_PREFIX_PATH": "/opt/ros/jazzy",
                "ROS_DISTRO": "jazzy",
                "TZ": "UTC",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise KDLBuildFailure(f"independent FK command failed: {argv[0]}") from exc


def build(*, source_root: Path, output_root: Path) -> dict[str, Any]:
    source = source_root.resolve(strict=True)
    output = output_root.resolve()
    if output.exists() and any(output.iterdir()):
        raise KDLBuildFailure("independent FK output is not create-only/empty")
    _require_binding(KDL_PARSER_LIBRARY)
    _require_binding(OROCOS_KDL_LIBRARY)
    _require_binding(COMPILER)
    verifier_source = read_regular_file_once(source / VERIFIER_REPO_PATH)
    builder_source = read_regular_file_once(Path(__file__).resolve())
    urdf = read_regular_file_once(source / CONTROLLED_PANDA_URDF_PATH)
    if _sha256(urdf) != CONTROLLED_PANDA_URDF_SHA256:
        raise KDLBuildFailure("controlled Panda URDF digest differs")
    compiler_version = _run([COMPILER["path"], "--version"]).stdout.splitlines()[0]
    if compiler_version != COMPILER["version"]:
        raise KDLBuildFailure("independent FK compiler version differs")
    output.mkdir(parents=True, exist_ok=True, mode=0o755)
    copied_source = output / "controlled_panda_fk_kdl_verifier_v1.cpp"
    copied_builder = output / "build_controlled_panda_fk_kdl_evidence.py"
    copied_urdf = output / "panda_controlled.urdf"
    _write_create_only(copied_source, verifier_source, 0o444)
    _write_create_only(copied_builder, builder_source, 0o444)
    _write_create_only(copied_urdf, urdf, 0o444)
    binary = output / "controlled_panda_fk_kdl_verifier_v1"
    compile_command = [
        COMPILER["path"],
        "-std=c++17",
        "-O2",
        "-fno-fast-math",
        "-ffp-contract=off",
        *INCLUDE_FLAGS,
        str(copied_source),
        "-L/opt/ros/jazzy/lib",
        "-Wl,-rpath,/opt/ros/jazzy/lib",
        "-Wl,-z,defs",
        "-Wl,-z,now",
        "-Wl,-z,relro",
        "-lkdl_parser",
        "-lorocos-kdl",
        "-o",
        str(binary),
    ]
    _run(compile_command)
    os.chmod(binary, 0o555)
    rows: list[str] = []
    for state_index, state in enumerate(FROZEN_STATES):
        result = _run(
            [
                str(binary),
                str(copied_urdf),
                str(state_index),
                *(format(value, ".17g") for value in state),
            ]
        )
        rows.extend(result.stdout.splitlines())
    csv_payload = ("\n".join(rows) + "\n").encode("ascii")
    if len(rows) != len(FROZEN_STATES) * len(EXPECTED_LINK_PATHS):
        raise KDLBuildFailure("independent FK row coverage differs")
    _write_create_only(output / "kdl-transforms.csv", csv_payload, 0o444)
    core = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "host": "node2",
        "operating_system": "Ubuntu 22.04.5 LTS; Linux 6.11.0-25-generic",
        "architecture": "x86_64",
        "ros_distribution": "jazzy",
        "orocos_kdl_version": "1.5.1",
        "kdl_parser_library": KDL_PARSER_LIBRARY,
        "orocos_kdl_library": OROCOS_KDL_LIBRARY,
        "compiler": COMPILER,
        "compile_command": compile_command,
        "builder_source_sha256": _sha256(builder_source),
        "verifier_source_sha256": _sha256(verifier_source),
        "verifier_binary_sha256": _sha256(read_regular_file_once(binary)),
        "urdf_sha256": CONTROLLED_PANDA_URDF_SHA256,
        "joint_names": list(EXECUTOR_JOINT_NAMES),
        "states": [list(state) for state in FROZEN_STATES],
        "state_count": len(FROZEN_STATES),
        "link_paths": list(EXPECTED_LINK_PATHS),
        "row_count": len(rows),
        "query_only": True,
        "isaac_started": False,
        "physical_execution_performed": False,
        "training_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_execution_eligible": False,
    }
    manifest = {**core, "manifest_sha256": canonical_sha256(core)}
    _write_create_only(
        output / "evidence-manifest.json",
        canonical_json_bytes(manifest) + b"\n",
        0o444,
    )
    descriptor = os.open(output, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build(source_root=args.source_root, output_root=args.output_root)
    except (OSError, ValueError, KDLBuildFailure) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
