#!/usr/bin/env python3
"""Replay the ADR-0024 A.3 native build and geometry evidence without Isaac."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from m2c.build_a3_bullet_native_closure import (  # noqa: E402
    ADAPTER_SHA256,
    BUILD_FLAGS,
    COLLISION_LIBRARY_SHA256,
    CORE_SHA256,
    EXPECTED_HEADERS,
    EXPECTED_NEEDED,
    EXPECTED_RUNPATH,
    LINEAR_MATH_LIBRARY_SHA256,
    canonical_json_bytes,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (  # noqa: E402
    A3BulletFloat64BuildManifestV1,
    LINK2_STL_SHA256,
    LINK4_STL_SHA256,
    build_controlled_panda_geometry_v1,
)


SCHEMA_VERSION = "M2CPhase2A3NativeBuildAuditV1"
EXPECTED_RELATIVE_FILES = (
    "build-stdout.json",
    "builder-image-id.txt",
    "builder-readback.txt",
    "docker-build.log",
    "meshes/link2.stl",
    "meshes/link4.stl",
    "native/a3-bullet-build-manifest.json",
    "native/compiler-inputs.json",
    "native/libm2c_a3_bullet_float64.so",
    "native/native-build-receipt.json",
)
EXPECTED_BLOCKERS = (
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
    "REAL_QUERY_ONLY_FK_PROVIDER_BINDING_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
)
IMPLEMENTATION_PATHS = (
    "docker/m2c-a3-bullet-builder/Dockerfile",
    "scripts/m2c/build_a3_bullet_native_closure.py",
    "scripts/m2c/audit_phase2_a3_native_build.py",
)


class A3BuildAuditError(RuntimeError):
    """The copied native-build evidence differs or overclaims readiness."""


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise A3BuildAuditError(f"evidence is not a single-link regular file: {path}")
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
            raise A3BuildAuditError(f"evidence changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise A3BuildAuditError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise A3BuildAuditError(f"{label} is not a JSON object")
    return value


def _inventory(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise A3BuildAuditError(f"evidence contains a symlink: {relative}")
        if path.is_dir():
            if path.stat().st_mode & 0o222:
                raise A3BuildAuditError(f"evidence directory is writable: {relative}")
            continue
        if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_mode & 0o222:
            raise A3BuildAuditError(f"evidence file is mutable/non-regular: {relative}")
        files[relative] = sha256_bytes(read_regular_file_once(path))
    if tuple(files) != EXPECTED_RELATIVE_FILES:
        raise A3BuildAuditError("native-build evidence inventory differs")
    return files


def _canonical_file(raw: bytes, *, label: str) -> dict[str, Any]:
    value = json_object(raw, label=label)
    if raw != canonical_json_bytes(value) + b"\n":
        raise A3BuildAuditError(f"{label} is not canonical JSON")
    return value


def build_report(project_root: Path, evidence_root: Path) -> dict[str, Any]:
    project = project_root.resolve(strict=True)
    evidence = evidence_root.resolve(strict=True)
    inventory = _inventory(evidence)

    builder_image_id = read_regular_file_once(evidence / "builder-image-id.txt").decode().strip()
    receipt_raw = read_regular_file_once(evidence / "native/native-build-receipt.json")
    receipt = _canonical_file(receipt_raw, label="native build receipt")
    receipt_core = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    build_stdout = json_object(
        read_regular_file_once(evidence / "build-stdout.json"), label="build stdout"
    )
    if receipt != build_stdout or receipt.get("receipt_sha256") != canonical_sha256(receipt_core):
        raise A3BuildAuditError("native build receipt self-hash/stdout differs")
    if (
        receipt.get("schema_version") != "M2CA3NativeBuildReceiptV1"
        or receipt.get("status") != "BUILT_QUERY_ONLY"
        or receipt.get("build_container_digest") != builder_image_id
        or receipt.get("source_bindings")
        != {
            "a3_bullet_native_adapter_v1.cpp": ADAPTER_SHA256,
            "a3_bullet_self_ccd_v1.cpp": CORE_SHA256,
        }
        or receipt.get("audited_header_bindings") != dict(sorted(EXPECTED_HEADERS.items()))
        or receipt.get("build_flags") != list(BUILD_FLAGS)
        or receipt.get("bullet_collision_library_sha256") != COLLISION_LIBRARY_SHA256
        or receipt.get("bullet_linear_math_library_sha256") != LINEAR_MATH_LIBRARY_SHA256
        or receipt.get("dynamic_needed") != list(EXPECTED_NEEDED)
        or receipt.get("dynamic_runpath") != EXPECTED_RUNPATH
        or receipt.get("query_only") is not True
        or any(
            receipt.get(field) is not False
            for field in (
                "isaac_started",
                "physical_execution_performed",
                "training_performed",
                "teacher_used",
                "privileged_truth_policy_input",
                "formal_execution_eligible",
            )
        )
    ):
        raise A3BuildAuditError("native build receipt contract differs")

    inputs_raw = read_regular_file_once(evidence / "native/compiler-inputs.json")
    inputs = _canonical_file(inputs_raw, label="compiler inputs")
    dependencies = inputs.get("dependencies")
    if (
        receipt.get("compiler_inputs_sha256") != sha256_bytes(inputs_raw)
        or not isinstance(dependencies, list)
        or len(dependencies) < len(EXPECTED_HEADERS) + 2
        or len({item.get("path") for item in dependencies if isinstance(item, dict)})
        != len(dependencies)
        or inputs.get("build_container_digest") != builder_image_id
    ):
        raise A3BuildAuditError("compiler input closure differs")

    manifest_raw = read_regular_file_once(evidence / "native/a3-bullet-build-manifest.json")
    _canonical_file(manifest_raw, label="adapter build manifest")
    try:
        manifest = A3BulletFloat64BuildManifestV1.model_validate_json(manifest_raw)
    except Exception as exc:
        raise A3BuildAuditError("adapter build manifest schema differs") from exc
    native_raw = read_regular_file_once(evidence / "native/libm2c_a3_bullet_float64.so")
    if (
        receipt.get("adapter_build_manifest_sha256") != sha256_bytes(manifest_raw)
        or manifest.immutable_build_container_digest != builder_image_id
        or manifest.complete_transitive_compile_manifest.sha256 != sha256_bytes(inputs_raw)
        or manifest.native_shared_object.sha256 != sha256_bytes(native_raw)
        or receipt.get("native_shared_object_sha256") != sha256_bytes(native_raw)
        or receipt.get("native_shared_object_size_bytes") != len(native_raw)
    ):
        raise A3BuildAuditError("native artifact/build manifest cross-binding differs")

    link2 = evidence / "meshes/link2.stl"
    link4 = evidence / "meshes/link4.stl"
    if (
        inventory["meshes/link2.stl"] != LINK2_STL_SHA256
        or inventory["meshes/link4.stl"] != LINK4_STL_SHA256
    ):
        raise A3BuildAuditError("original controlled-Panda STL binding differs")
    geometry = build_controlled_panda_geometry_v1(
        project_root=project,
        link2_stl_path=link2,
        link4_stl_path=link4,
        contract_test_only=False,
    )
    shape_counts = {
        kind: sum(1 for item in geometry.shape_payloads if item.shape_kind == kind)
        for kind in ("BOX", "CYLINDER", "CONVEX_HULL")
    }
    if len(geometry.children) != 14 or shape_counts != {
        "BOX": 11,
        "CYLINDER": 1,
        "CONVEX_HULL": 2,
    }:
        raise A3BuildAuditError("controlled-Panda collision geometry coverage differs")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY",
        "implementation_bindings": {
            path: sha256_bytes(read_regular_file_once(project / path))
            for path in IMPLEMENTATION_PATHS
        },
        "evidence_inventory": {
            "regular_file_count": len(inventory),
            "canonical_path_sha256_map_digest": canonical_sha256(inventory),
            "files": inventory,
        },
        "native_build": {
            "builder_image_id": builder_image_id,
            "build_receipt_sha256": sha256_bytes(receipt_raw),
            "receipt_core_sha256": receipt["receipt_sha256"],
            "adapter_build_manifest_file_sha256": sha256_bytes(manifest_raw),
            "adapter_build_manifest_core_sha256": manifest.build_manifest_sha256,
            "compiler_inputs_sha256": sha256_bytes(inputs_raw),
            "native_shared_object_sha256": sha256_bytes(native_raw),
            "native_shared_object_size_bytes": len(native_raw),
            "dynamic_needed": receipt["dynamic_needed"],
            "dynamic_runpath": receipt["dynamic_runpath"],
            "query_only": True,
        },
        "controlled_panda_geometry_replay": {
            "geometry_receipt_sha256": geometry.receipt_sha256,
            "collision_child_count": len(geometry.children),
            "shape_counts": shape_counts,
            "per_shape_collision_margins_m": {
                f"{item.link_path}#{item.child_index}": item.collision_margin_m
                for item in geometry.shape_payloads
            },
            "all_compounds_expanded": geometry.all_compounds_expanded,
            "unknown_or_concave_shape_rejects": geometry.unknown_or_concave_shape_rejects,
            "contract_test_only": geometry.contract_test_only,
            "formal_evidence": geometry.formal_evidence,
        },
        "evidence_claims": {
            "native_build_completed": True,
            "original_meshes_replayed": True,
            "isaac_started": False,
            "physical_execution_performed": False,
            "training_performed": False,
            "q_b_evaluation_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "formal_execution_eligible": False,
            "production_binding_set": False,
        },
        "remaining_blockers": list(EXPECTED_BLOCKERS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.project_root, args.evidence_root)
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.expected_json is not None:
            if read_regular_file_once(args.expected_json).decode("utf-8") != payload:
                raise A3BuildAuditError("expected JSON report differs from replay")
    except (A3BuildAuditError, OSError) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
