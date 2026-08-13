#!/usr/bin/env python3
"""Replay an independent node2 KDL comparison of the query-only Panda FK.

The evidence root must contain the exact controlled URDF, the repository's
small C++ verifier, the verifier binary, its compiler/dependency manifest, and
the CSV produced for every frozen state/link pair.  This auditor independently
recomputes the Python provider output and the comparison metrics.  It starts no
simulator, loads no controller, performs no physical action, and cannot set a
production binding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from xh_agent.policy.qrm_lite.controlled_panda_fk_v1 import (  # noqa: E402
    CONTROLLED_PANDA_URDF_PATH,
    CONTROLLED_PANDA_URDF_SHA256,
    EXECUTOR_JOINT_NAMES,
    EXPECTED_LINK_PATHS,
    IMPLEMENTATION_REPO_PATH,
    ControlledPandaReadOnlyFKProviderV1,
)


SCHEMA_VERSION = "M2CControlledPandaFKKDLComparisonAuditV1"
EVIDENCE_SCHEMA_VERSION = "M2CControlledPandaFKKDLEvidenceV1"
VERIFIER_REPO_PATH = "scripts/m2c/controlled_panda_fk_kdl_verifier_v1.cpp"
BUILDER_REPO_PATH = "scripts/m2c/build_controlled_panda_fk_kdl_evidence.py"
EXPECTED_STATE_COUNT = 12
EXPECTED_ROW_COUNT = EXPECTED_STATE_COUNT * len(EXPECTED_LINK_PATHS)
MAXIMUM_TRANSLATION_ERROR_M = 1e-12
MAXIMUM_ORIENTATION_ERROR_RAD = 1e-12
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


class FKComparisonAuditFailure(RuntimeError):
    """Evidence bytes or an independent FK result differ."""


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
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FKComparisonAuditFailure(f"FK evidence is not a single-link file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise FKComparisonAuditFailure(f"FK evidence changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise FKComparisonAuditFailure(f"FK evidence contains a symlink: {path}")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        files[relative] = _sha256(read_regular_file_once(path))
    return files


def _parse_csv(raw: bytes) -> dict[tuple[int, str], tuple[float, ...]]:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise FKComparisonAuditFailure("KDL comparison CSV is not ASCII") from exc
    if not text.endswith("\n"):
        raise FKComparisonAuditFailure("KDL comparison CSV has an incomplete last line")
    output: dict[tuple[int, str], tuple[float, ...]] = {}
    for line in text.splitlines():
        fields = line.split(",")
        if len(fields) != 9:
            raise FKComparisonAuditFailure("KDL comparison CSV row width differs")
        try:
            state_index = int(fields[0])
            values = tuple(float(value) for value in fields[2:])
        except ValueError as exc:
            raise FKComparisonAuditFailure("KDL comparison CSV contains malformed values") from exc
        if not all(math.isfinite(value) for value in values):
            raise FKComparisonAuditFailure("KDL comparison CSV contains NaN/Inf")
        key = (state_index, fields[1])
        if key in output:
            raise FKComparisonAuditFailure("KDL comparison CSV repeats a state/link")
        output[key] = values
    return output


def build_audit(*, project_root: Path, evidence_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    evidence = evidence_root.resolve()
    manifest_raw = read_regular_file_once(evidence / "evidence-manifest.json")
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise FKComparisonAuditFailure("FK evidence manifest is not JSON") from exc
    exact_keys = {
        "schema_version",
        "host",
        "operating_system",
        "architecture",
        "ros_distribution",
        "orocos_kdl_version",
        "kdl_parser_library",
        "orocos_kdl_library",
        "compiler",
        "compile_command",
        "builder_source_sha256",
        "verifier_source_sha256",
        "verifier_binary_sha256",
        "urdf_sha256",
        "joint_names",
        "states",
        "state_count",
        "link_paths",
        "row_count",
        "query_only",
        "isaac_started",
        "physical_execution_performed",
        "training_performed",
        "teacher_used",
        "privileged_truth_policy_input",
        "formal_execution_eligible",
        "manifest_sha256",
    }
    if set(manifest) != exact_keys or manifest.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise FKComparisonAuditFailure("FK evidence manifest fields/schema differ")
    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest["manifest_sha256"] != canonical_sha256(core):
        raise FKComparisonAuditFailure("FK evidence manifest digest differs")
    verifier_source = read_regular_file_once(root / VERIFIER_REPO_PATH)
    builder_source = read_regular_file_once(root / BUILDER_REPO_PATH)
    provider_source = read_regular_file_once(root / IMPLEMENTATION_REPO_PATH)
    urdf = read_regular_file_once(root / CONTROLLED_PANDA_URDF_PATH)
    evidence_verifier = read_regular_file_once(evidence / "controlled_panda_fk_kdl_verifier_v1.cpp")
    evidence_builder = read_regular_file_once(
        evidence / "build_controlled_panda_fk_kdl_evidence.py"
    )
    evidence_binary = read_regular_file_once(evidence / "controlled_panda_fk_kdl_verifier_v1")
    evidence_urdf = read_regular_file_once(evidence / "panda_controlled.urdf")
    if (
        _sha256(verifier_source) != manifest["verifier_source_sha256"]
        or evidence_verifier != verifier_source
        or _sha256(evidence_binary) != manifest["verifier_binary_sha256"]
        or _sha256(builder_source) != manifest["builder_source_sha256"]
        or evidence_builder != builder_source
    ):
        raise FKComparisonAuditFailure("FK independent verifier source/binary differs")
    if (
        _sha256(urdf) != CONTROLLED_PANDA_URDF_SHA256
        or manifest["urdf_sha256"] != CONTROLLED_PANDA_URDF_SHA256
        or evidence_urdf != urdf
    ):
        raise FKComparisonAuditFailure("FK controlled URDF bytes differ")
    expected_governance = {
        "host": "node2",
        "architecture": "x86_64",
        "ros_distribution": "jazzy",
        "orocos_kdl_version": "1.5.1",
        "joint_names": list(EXECUTOR_JOINT_NAMES),
        "state_count": EXPECTED_STATE_COUNT,
        "link_paths": list(EXPECTED_LINK_PATHS),
        "row_count": EXPECTED_ROW_COUNT,
        "query_only": True,
        "isaac_started": False,
        "physical_execution_performed": False,
        "training_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_execution_eligible": False,
    }
    for key, expected in expected_governance.items():
        if manifest.get(key) != expected:
            raise FKComparisonAuditFailure(f"FK evidence governance differs: {key}")
    states = tuple(tuple(float(value) for value in state) for state in manifest["states"])
    if (
        states != FROZEN_STATES
        or len(states) != EXPECTED_STATE_COUNT
        or any(
            len(state) != len(EXECUTOR_JOINT_NAMES)
            or not all(math.isfinite(value) for value in state)
            for state in states
        )
    ):
        raise FKComparisonAuditFailure("FK frozen comparison states differ")
    provider = ControlledPandaReadOnlyFKProviderV1(project_root=root)
    calculated = provider.query_link_transforms(
        joint_names=EXECUTOR_JOINT_NAMES,
        joint_state_sequence=states,
        link_paths=EXPECTED_LINK_PATHS,
    )
    kdl = _parse_csv(read_regular_file_once(evidence / "kdl-transforms.csv"))
    expected_keys = {
        (state_index, link_path.rsplit("/", 1)[1])
        for state_index in range(EXPECTED_STATE_COUNT)
        for link_path in EXPECTED_LINK_PATHS
    }
    if set(kdl) != expected_keys or len(kdl) != EXPECTED_ROW_COUNT:
        raise FKComparisonAuditFailure("KDL comparison state/link coverage differs")
    maximum_translation = 0.0
    maximum_orientation = 0.0
    worst_translation: dict[str, Any] | None = None
    worst_orientation: dict[str, Any] | None = None
    for state_index in range(EXPECTED_STATE_COUNT):
        for link_path in EXPECTED_LINK_PATHS:
            transform = calculated[link_path][state_index]
            values = kdl[(state_index, link_path.rsplit("/", 1)[1])]
            translation_error = math.dist(transform.translation_world_m, values[:3])
            left_quaternion = transform.rotation_world_wxyz
            right_quaternion = values[3:]
            # The relative-quaternion vector norm is stable near identity;
            # acos(dot) would amplify harmless last-bit rounding into a
            # spurious ~4e-8 rad error.
            lw, lx, ly, lz = left_quaternion
            rw, rx, ry, rz = right_quaternion
            relative_vector_norm = math.sqrt(
                (lw * rx - lx * rw - ly * rz + lz * ry) ** 2
                + (lw * ry + lx * rz - ly * rw - lz * rx) ** 2
                + (lw * rz - lx * ry + ly * rx - lz * rw) ** 2
            )
            quaternion_dot = abs(
                sum(left * right for left, right in zip(left_quaternion, right_quaternion))
            )
            orientation_error = 2.0 * math.atan2(relative_vector_norm, quaternion_dot)
            if translation_error > maximum_translation:
                maximum_translation = translation_error
                worst_translation = {"state_index": state_index, "link_path": link_path}
            if orientation_error > maximum_orientation:
                maximum_orientation = orientation_error
                worst_orientation = {"state_index": state_index, "link_path": link_path}
    if (
        maximum_translation > MAXIMUM_TRANSLATION_ERROR_M
        or maximum_orientation > MAXIMUM_ORIENTATION_ERROR_RAD
    ):
        raise FKComparisonAuditFailure("Python FK differs from independent Orocos KDL")
    inventory = _inventory(evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_QUERY_ONLY_FK_MATCHES_INDEPENDENT_NODE2_KDL",
        "provider": {
            "path": IMPLEMENTATION_REPO_PATH,
            "sha256": _sha256(provider_source),
            "configuration_sha256": provider.configuration_sha256,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
        },
        "independent_verifier": {
            "path": VERIFIER_REPO_PATH,
            "sha256": _sha256(verifier_source),
            "host": manifest["host"],
            "orocos_kdl_version": manifest["orocos_kdl_version"],
            "kdl_parser_library": manifest["kdl_parser_library"],
            "orocos_kdl_library": manifest["orocos_kdl_library"],
            "compiler": manifest["compiler"],
            "compile_command": manifest["compile_command"],
            "binary_sha256": manifest["verifier_binary_sha256"],
        },
        "comparison": {
            "state_count": EXPECTED_STATE_COUNT,
            "collision_link_count": len(EXPECTED_LINK_PATHS),
            "row_count": EXPECTED_ROW_COUNT,
            "maximum_translation_error_m": maximum_translation,
            "maximum_orientation_error_rad": maximum_orientation,
            "translation_tolerance_m": MAXIMUM_TRANSLATION_ERROR_M,
            "orientation_tolerance_rad": MAXIMUM_ORIENTATION_ERROR_RAD,
            "worst_translation": worst_translation,
            "worst_orientation": worst_orientation,
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "files": inventory,
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
        },
        "evidence_claims": {
            "formal_execution_eligible": False,
            "isaac_started": False,
            "physical_execution_performed": False,
            "production_binding_set": False,
            "training_performed": False,
            "q_b_evaluation_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        },
        "remaining_blockers": [
            "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
            "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
            "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
            "REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING",
            "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    try:
        report = build_audit(project_root=args.project_root, evidence_root=args.evidence_root)
    except (OSError, ValueError, FKComparisonAuditFailure) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.expected_json is not None:
        if read_regular_file_once(args.expected_json).decode("utf-8") != payload:
            print("BLOCKED: expected FK audit report differs")
            return 2
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
