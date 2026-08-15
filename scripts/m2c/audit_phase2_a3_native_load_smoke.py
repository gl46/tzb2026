#!/usr/bin/env python3
"""Replay the query-only A.3 native-load smoke from immutable evidence.

The audited process ran under ``/isaac-sim/python.sh`` in the frozen Isaac 6
image but loaded no Isaac/Kit module.  It loaded the hash-bound float64 Bullet
ABI, replayed read-only FK at the home state, and evaluated all 74 governed
self-collision child pairs.  This audit never starts Isaac, loads the native
module, creates a scene, executes a command, or trains a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3BulletFloat64BuildManifestV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_json_bytes


SCHEMA_VERSION = "M2CPhase2A3NativeLoadSmokeAuditV1"
SMOKE_SCHEMA_VERSION = "M2CA3QueryOnlyDeploymentSmokeV1"
IMMUTABLE_COMMIT = "a64ee76ec298a025f4021245211e1208847bebf0"
RUNTIME_IMAGE_ID = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
BUILDER_IMAGE_ID = "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
DEPENDENCY_INVENTORY_SHA256 = "3641a84b2e0befd0225f6127fd613c10bbc2b2abe615bce1fc28491e4533586d"
SMOKE_REPORT_SHA256 = "6b05f5923e20632c38a394758884e1a7d00ef8b27577cea915b7f323d0a1121f"

DEPENDENCY_SHA256 = {
    "meshes/link2.stl": "370f7605a0fae3529db169ded50f52f171024aa792d4d773bc84197301f6a039",
    "meshes/link4.stl": "0180ebb5772ec9840cb049750cffb29a9ddc90311752a16ea34757782ef9e48d",
    "output/a3-bullet-build-manifest.json": (
        "6285988b8aea7f5e3bdff0f3b215e483ff59a350cff5ff7aaf4a638bb12c65e3"
    ),
    "output/compiler-inputs.json": (
        "7f4f3e47272f4d5557063a026dbfa713caa69eec39ecdf9e27aeb4aa88e11875"
    ),
    "output/libm2c_a3_bullet_float64.so": (
        "2231cee659b15875fc0bed011f339ac9962168981d228f3f08c6189929ce9c23"
    ),
    "usr/include/bullet/BulletCollision/CollisionShapes/btBoxShape.h": (
        "8ec85f0c79e746088a186979c174a1ec5007a150e5281030f2e8321e4c1eeac7"
    ),
    "usr/include/bullet/BulletCollision/CollisionShapes/btCompoundShape.h": (
        "34413f9e250e66ec5f12f9c6e96c16b5f9eb06e842961c08085475b4c1478357"
    ),
    "usr/include/bullet/BulletCollision/CollisionShapes/btConvexHullShape.h": (
        "209211f19fa98cc6a085d95266c4c15ee8a2bf3be5cc29403d858e8f26e97929"
    ),
    "usr/include/bullet/BulletCollision/CollisionShapes/btConvexShape.h": (
        "8d636b8b1ef7ec75926d48b03a4a448a44373ecf362329ce2150586bae4fb0c9"
    ),
    "usr/include/bullet/BulletCollision/CollisionShapes/btCylinderShape.h": (
        "097a80dbf01b8f5add103a0802ffab1201c285e7aaaf2aef8d94c17c193f6167"
    ),
    "usr/include/bullet/BulletCollision/NarrowPhaseCollision/btContinuousConvexCollision.h": (
        "7ba73189495d70659b257899352f3688585d8bff536db11f8c86cfa6931fe2e4"
    ),
    "usr/include/bullet/BulletCollision/NarrowPhaseCollision/btConvexCast.h": (
        "5eca7f5931c6f954dc4d8b58ff75ec58112c46f96783b1c8de5a117c663a6c6b"
    ),
    "usr/include/bullet/BulletCollision/NarrowPhaseCollision/btGjkConvexCast.h": (
        "3409007ce88c742edba270851d8122fead8c766febf2de193525e0cc2a4694db"
    ),
    "usr/include/bullet/BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h": (
        "bc5e3baf33e296de9367c247b25b9cd8803decee3d57896f87ec161568bedff0"
    ),
    "usr/include/bullet/BulletCollision/NarrowPhaseCollision/btSubSimplexConvexCast.h": (
        "74ffb324a2268abeca5c6757c09b238240be5de12a10f7443652df3f52d1c876"
    ),
    "usr/include/bullet/BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h": (
        "5771fe6eb5b51e91ca83c00c746216b821920b7a147875e01422add194e81805"
    ),
    "usr/include/bullet/LinearMath/btTransformUtil.h": (
        "add9774d16afa59c5cf0529df82133712cad28411e952b9c4cc00ffa8bfa37ee"
    ),
    "usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24": (
        "baa16598bc6a54aa51c825af6680807b548decb33ff11f469ac24c09f54826c2"
    ),
    "usr/lib/x86_64-linux-gnu/libLinearMath-float64.so.3.24": (
        "5d3fe859ad08f78fac1e51ed85dddd9e39da501a0d566e86e00da5565d9e5343"
    ),
}

SMOKE_FILE_SHA256 = {
    "container-stderr.log": hashlib.sha256(b"").hexdigest(),
    "container-stdout.log": SMOKE_REPORT_SHA256,
    "exit-code.txt": hashlib.sha256(b"0\n").hexdigest(),
    "query-only-deployment-smoke.json": SMOKE_REPORT_SHA256,
}


class NativeLoadSmokeAuditFailure(RuntimeError):
    """The frozen runtime closure or smoke evidence differs."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_regular_once(path: Path, *, require_read_only: bool = True) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or (require_read_only and stat.S_IMODE(before.st_mode) != 0o444)
            or (not require_read_only and before.st_mode & 0o022)
        ):
            raise NativeLoadSmokeAuditFailure(f"evidence file is not immutable: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_uid,
            value.st_mode,
            value.st_nlink,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise NativeLoadSmokeAuditFailure(f"evidence changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_tree(root: Path, expected: dict[str, str]) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise NativeLoadSmokeAuditFailure("evidence root is not a directory")
    observed: dict[str, bytes] = {}
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(directory)
        current_stat = current.lstat()
        if (
            not stat.S_ISDIR(current_stat.st_mode)
            or current_stat.st_uid != os.geteuid()
            or stat.S_IMODE(current_stat.st_mode) != 0o555
        ):
            raise NativeLoadSmokeAuditFailure(f"evidence directory is not immutable: {current}")
        if any((current / name).is_symlink() for name in directory_names):
            raise NativeLoadSmokeAuditFailure("evidence tree contains a directory symlink")
        for name in file_names:
            path = current / name
            if path.is_symlink():
                raise NativeLoadSmokeAuditFailure("evidence tree contains a file symlink")
            relative = path.relative_to(root).as_posix()
            observed[relative] = _read_regular_once(path)
    if set(observed) != set(expected):
        raise NativeLoadSmokeAuditFailure("evidence file inventory differs")
    for path, digest in expected.items():
        if _sha256(observed[path]) != digest:
            raise NativeLoadSmokeAuditFailure(f"evidence digest differs: {path}")
    return observed


def _git_blob(project_root: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(project_root), "show", f"{commit}:{path}"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise NativeLoadSmokeAuditFailure(f"frozen source is absent from {commit}: {path}")
    return result.stdout


def _strict_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeLoadSmokeAuditFailure(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise NativeLoadSmokeAuditFailure(f"{label} must be a JSON object")
    return value


def build_report(project_root: Path, dependency_root: Path, smoke_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    dependency_root = dependency_root.resolve(strict=True)
    smoke_root = smoke_root.resolve(strict=True)

    dependency_expected = {**DEPENDENCY_SHA256, "meta/sha256sums.txt": DEPENDENCY_INVENTORY_SHA256}
    dependency_files = _validate_tree(dependency_root, dependency_expected)
    expected_inventory = b"".join(
        f"{digest}  ./{path}\n".encode("ascii") for path, digest in DEPENDENCY_SHA256.items()
    )
    if dependency_files["meta/sha256sums.txt"] != expected_inventory:
        raise NativeLoadSmokeAuditFailure("runtime dependency inventory bytes differ")

    manifest = A3BulletFloat64BuildManifestV1.model_validate_json(
        dependency_files["output/a3-bullet-build-manifest.json"]
    )
    manifest_headers = {
        item.path.lstrip("/"): item.sha256 for item in manifest.audited_bullet_headers
    }
    expected_headers = {
        path: digest
        for path, digest in DEPENDENCY_SHA256.items()
        if path.startswith("usr/include/")
    }
    if manifest_headers != expected_headers:
        raise NativeLoadSmokeAuditFailure("runtime header closure differs from build manifest")
    if (
        manifest.immutable_build_container_digest != BUILDER_IMAGE_ID
        or manifest.native_shared_object.sha256
        != DEPENDENCY_SHA256["output/libm2c_a3_bullet_float64.so"]
        or manifest.bullet_collision_library.sha256
        != DEPENDENCY_SHA256["usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24"]
        or manifest.bullet_linear_math_library.sha256
        != DEPENDENCY_SHA256["usr/lib/x86_64-linux-gnu/libLinearMath-float64.so.3.24"]
    ):
        raise NativeLoadSmokeAuditFailure("runtime native closure crosses build manifest")

    smoke_files = _validate_tree(smoke_root, SMOKE_FILE_SHA256)
    report_raw = smoke_files["query-only-deployment-smoke.json"]
    if smoke_files["container-stdout.log"] != report_raw:
        raise NativeLoadSmokeAuditFailure("container stdout differs from published smoke report")
    report = _strict_object(report_raw, "native-load smoke report")
    if report_raw != canonical_json_bytes(report) + b"\n":
        raise NativeLoadSmokeAuditFailure("native-load smoke report is not canonical JSON")

    required_top = {
        "schema_version",
        "status",
        "immutable_commit",
        "runtime",
        "source_bindings",
        "native_closure",
        "query",
        "evidence_claims",
        "remaining_blockers",
    }
    if set(report) != required_top:
        raise NativeLoadSmokeAuditFailure("native-load smoke report fields differ")
    if (
        report["schema_version"] != SMOKE_SCHEMA_VERSION
        or report["status"] != "PASS_QUERY_ONLY_DEPLOYMENT_SMOKE_CLEAR"
        or report["immutable_commit"] != IMMUTABLE_COMMIT
        or report["runtime"]
        != {
            "container_image_id": RUNTIME_IMAGE_ID,
            "python_version": "3.12.13",
            "platform_system": "Linux",
            "platform_machine": "x86_64",
            "isaac_or_kit_module_loaded": False,
        }
    ):
        raise NativeLoadSmokeAuditFailure("native-load smoke runtime identity differs")

    source_bindings = report["source_bindings"]
    if not isinstance(source_bindings, dict) or not source_bindings:
        raise NativeLoadSmokeAuditFailure("native-load source bindings are absent")
    for relative, digest in source_bindings.items():
        current = _read_regular_once(project_root / relative, require_read_only=False)
        frozen = _git_blob(project_root, IMMUTABLE_COMMIT, relative)
        if _sha256(current) != digest or _sha256(frozen) != digest or current != frozen:
            raise NativeLoadSmokeAuditFailure(f"native-load source binding differs: {relative}")

    native = report["native_closure"]
    if native != {
        "build_manifest_file_sha256": DEPENDENCY_SHA256["output/a3-bullet-build-manifest.json"],
        "build_manifest_core_sha256": manifest.build_manifest_sha256,
        "builder_image_id": BUILDER_IMAGE_ID,
        "native_shared_object_sha256": manifest.native_shared_object.sha256,
        "bullet_collision_library_sha256": manifest.bullet_collision_library.sha256,
        "bullet_linear_math_library_sha256": manifest.bullet_linear_math_library.sha256,
    }:
        raise NativeLoadSmokeAuditFailure("native-load report crosses runtime closure")

    query = report["query"]
    if (
        not isinstance(query, dict)
        or query.get("request_segment_count") != 74
        or query.get("clear_result_count") != 74
        or query.get("collision_rejection_count") != 0
        or query.get("query_failure_count") != 0
        or query.get("receipt_status") != "PASS"
        or query.get("rejected_pairs") != []
        or len(query.get("joint_names", [])) != 9
    ):
        raise NativeLoadSmokeAuditFailure("native-load query outcome differs")

    claims = {
        "deployment_query_completed": True,
        "static_state_preflight_clear": True,
        "formal_execution_eligible": False,
        "isaac_started": False,
        "physical_execution_performed": False,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    if report["evidence_claims"] != claims:
        raise NativeLoadSmokeAuditFailure("native-load non-execution claims differ")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_QUERY_ONLY_NATIVE_LOAD_IN_FROZEN_ISAAC_IMAGE",
        "immutable_commit": IMMUTABLE_COMMIT,
        "runtime_image_id": RUNTIME_IMAGE_ID,
        "builder_image_id": BUILDER_IMAGE_ID,
        "dependency_bundle": {
            "path": str(dependency_root),
            "inventory_sha256": DEPENDENCY_INVENTORY_SHA256,
            "payload_file_count": len(DEPENDENCY_SHA256),
            "audited_bullet_header_count": len(expected_headers),
            "all_bytes_read_only": True,
        },
        "smoke_evidence": {
            "path": str(smoke_root),
            "report_sha256": SMOKE_REPORT_SHA256,
            "stdout_matches_report": True,
            "stderr_empty": True,
            "exit_code": 0,
        },
        "query": {
            "request_sha256": query["request_sha256"],
            "receipt_sha256": query["receipt_sha256"],
            "request_segment_count": 74,
            "clear_result_count": 74,
            "collision_rejection_count": 0,
            "query_failure_count": 0,
            "static_state_preflight_clear": True,
        },
        "evidence_claims": claims,
        "closed_blockers": [
            "NATIVE_MODULE_LOAD_IN_FROZEN_ISAAC_IMAGE_UNMEASURED",
            "STATIC_HOME_STATE_A3_QUERY_UNMEASURED",
        ],
        "remaining_blockers": report["remaining_blockers"],
        "one_next_command": (
            "run the immutable formal V4 endpoint contract smoke with the same native/FK "
            "closure; do not set either active binding until plan-specific eight-skill "
            "evidence and deployment closure pass"
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# M2C Phase-2 A.3 native-load smoke audit",
            "",
            f"- Status: **{report['status']}**",
            f"- Runtime image: `{report['runtime_image_id']}`",
            f"- Dependency inventory: `{report['dependency_bundle']['inventory_sha256']}`",
            f"- Smoke report: `{report['smoke_evidence']['report_sha256']}`",
            "- Query-only child pairs: **74/74 CLEAR**",
            "- Isaac/Kit module loaded: **false**",
            "- Articulation writes / simulation steps / scene mutations: **0 / 0 / 0**",
            "- Formal execution eligible: **false**",
            "- Teacher used: **false**",
            "",
            "This closes the native-module-load and static-home-state A.3 smoke blockers only.",
            "It is not plan-specific eight-skill evidence and does not authorize a production",
            "binding, physical command, training run, Q-B evaluation, or S6 evaluation.",
            "",
            "## Remaining blockers",
            "",
            *(f"- `{item}`" for item in report["remaining_blockers"]),
            "",
            "## Next command",
            "",
            f"`{report['one_next_command']}`",
            "",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--smoke-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--expected-json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args.project_root, args.dependency_root, args.smoke_root)
    except (OSError, ValueError, NativeLoadSmokeAuditFailure) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.expected_json is not None:
        expected = args.expected_json.read_text()
        if expected != payload:
            print(json.dumps({"status": "BLOCKED", "error": "expected report differs"}))
            return 2
    if args.output_json is not None:
        args.output_json.write_text(payload)
    else:
        print(payload, end="")
    if args.output_md is not None:
        args.output_md.write_text(_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
