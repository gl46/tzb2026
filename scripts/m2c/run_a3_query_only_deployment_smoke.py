#!/usr/bin/env python3
"""Run the ADR-0024 A.3 query-only deployment smoke without starting Isaac.

This program is intended to run under ``/isaac-sim/python.sh`` inside the
hash-pinned Isaac 6 image.  The project snapshot, native build evidence, two
original STL files, compiler/header closure, and Bullet float64 libraries must
all be mounted read-only at their byte-bound paths.  It loads no Kit/Isaac
module and performs no scene, articulation, controller, or simulation action.

The smoke has two deliberately separate outcomes:

* ``deployment_query_completed`` proves that the real FK provider and the
  real native float64 ABI loaded and returned a complete receipt;
* ``static_state_preflight_clear`` records the collision decision.  A
  collision is an honest fail-closed result and never becomes authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
from typing import Any

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3BulletFloat64BuildManifestV1,
    A3NativeBulletBackendV1,
    build_controlled_panda_geometry_v1,
    build_self_collision_world_from_fk_v1,
    produce_read_only_fk_receipt_v1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    build_child_pair_ccd_request_v1,
    canonical_a3_bullet_numeric_configuration_v1,
    verify_child_pair_ccd_receipt_v1,
)
from xh_agent.policy.qrm_lite.controlled_panda_fk_v1 import (
    ControlledPandaReadOnlyFKProviderV1,
    EXECUTOR_JOINT_NAMES,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_json_bytes, canonical_sha256


SCHEMA_VERSION = "M2CA3QueryOnlyDeploymentSmokeV1"
EXPECTED_RUNTIME_IMAGE_ID = (
    "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
)
EXPECTED_BUILDER_IMAGE_ID = (
    "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
)
HOME_OPEN_STATE = (0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0, 0.04, 0.04)


class DeploymentSmokeFailure(RuntimeError):
    """The query-only deployment closure is missing, crossed, or mutable."""


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise DeploymentSmokeFailure(f"smoke input is not single-link regular: {path}")
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
            raise DeploymentSmokeFailure(f"smoke input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def write_create_only(path: Path, payload: bytes) -> None:
    if not path.parent.is_dir():
        raise DeploymentSmokeFailure("smoke output parent must already exist")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o444)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise DeploymentSmokeFailure("short write while publishing smoke receipt")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _assert_query_only_process() -> None:
    forbidden = tuple(
        name
        for name in sys.modules
        if name == "isaacsim"
        or name.startswith("isaacsim.")
        or name == "omni"
        or name.startswith("omni.")
    )
    if forbidden:
        raise DeploymentSmokeFailure("Isaac/Kit module was loaded in query-only smoke")
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise DeploymentSmokeFailure("query-only native smoke requires Linux x86_64")


def build_smoke_report(
    *,
    project_root: Path,
    native_evidence_root: Path,
    immutable_commit: str,
    runtime_image_id: str,
) -> dict[str, Any]:
    _assert_query_only_process()
    if runtime_image_id != EXPECTED_RUNTIME_IMAGE_ID:
        raise DeploymentSmokeFailure("runtime container image ID differs")
    if len(immutable_commit) != 40 or any(ch not in "0123456789abcdef" for ch in immutable_commit):
        raise DeploymentSmokeFailure("immutable commit is malformed")

    root = project_root.resolve()
    evidence = native_evidence_root.resolve()
    manifest_path = evidence / "native/a3-bullet-build-manifest.json"
    manifest = A3BulletFloat64BuildManifestV1.model_validate_json(
        read_regular_file_once(manifest_path)
    )
    if manifest.immutable_build_container_digest != EXPECTED_BUILDER_IMAGE_ID:
        raise DeploymentSmokeFailure("native builder image ID differs")

    geometry = build_controlled_panda_geometry_v1(
        project_root=root,
        link2_stl_path=evidence / "meshes/link2.stl",
        link4_stl_path=evidence / "meshes/link4.stl",
    )
    provider = ControlledPandaReadOnlyFKProviderV1(project_root=root)
    states = (HOME_OPEN_STATE, HOME_OPEN_STATE)
    bound_plan_sha256 = canonical_sha256(
        {
            "schema_version": "M2CA3StaticQueryPlanIdentityV1",
            "immutable_commit": immutable_commit,
            "joint_names": EXECUTOR_JOINT_NAMES,
            "joint_state_sequence": states,
            "purpose": "QUERY_ONLY_DEPLOYMENT_SMOKE_NO_EXECUTION",
        }
    )
    fk_receipt = produce_read_only_fk_receipt_v1(
        bound_plan_sha256=bound_plan_sha256,
        geometry=geometry,
        joint_names=EXECUTOR_JOINT_NAMES,
        joint_state_sequence=states,
        provider=provider,
    )
    world = build_self_collision_world_from_fk_v1(
        geometry=geometry,
        fk_receipt=fk_receipt,
        require_real_runtime_provider=True,
    )
    configuration = canonical_a3_bullet_numeric_configuration_v1()
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256=bound_plan_sha256,
        world=world,
        configuration=configuration,
    )
    backend = A3NativeBulletBackendV1(project_root=root, manifest=manifest)
    receipt = backend.query(
        request,
        children=world.children,
        shape_payloads=geometry.shape_payloads,
        configuration=configuration,
    )
    query_failures = tuple(
        item for item in receipt.results if item.status == "REJECT_QUERY_FAILURE"
    )
    if query_failures:
        raise DeploymentSmokeFailure("native query returned an internal/ambiguous failure")
    if receipt.status == "PASS":
        verify_child_pair_ccd_receipt_v1(
            request,
            receipt,
            configuration=configuration,
            require_real_native_backend=True,
        )

    rejected_pairs = []
    for segment, result in zip(request.segments, receipt.results):
        if result.status == "CLEAR":
            continue
        rejected_pairs.append(
            {
                "pair_index": result.pair_index,
                "link_a": segment.link_a,
                "child_a": segment.child_a,
                "link_b": segment.link_b,
                "child_b": segment.child_b,
                "status": result.status,
                "failure_code": result.failure_code,
                "time_of_impact": result.time_of_impact,
                "discrete_start_clear": result.discrete_start_clear,
                "discrete_end_clear": result.discrete_end_clear,
                "continuous_query_completed": result.continuous_query_completed,
            }
        )

    script_path = Path(__file__).resolve()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_QUERY_ONLY_DEPLOYMENT_SMOKE_CLEAR"
            if receipt.status == "PASS"
            else "PASS_QUERY_ONLY_DEPLOYMENT_SMOKE_FAIL_CLOSED_COLLISION_REJECTION"
        ),
        "immutable_commit": immutable_commit,
        "runtime": {
            "container_image_id": runtime_image_id,
            "python_version": platform.python_version(),
            "platform_system": platform.system(),
            "platform_machine": platform.machine(),
            "isaac_or_kit_module_loaded": False,
        },
        "source_bindings": {
            "scripts/m2c/run_a3_query_only_deployment_smoke.py": sha256_file(script_path),
            provider.implementation_path.removeprefix(f"{root}/"): provider.implementation_sha256,
            manifest.native_core.path: manifest.native_core.sha256,
            manifest.native_adapter.path: manifest.native_adapter.sha256,
            geometry.robot_description.path: geometry.robot_description.sha256,
            geometry.semantic_collision_matrix.path: geometry.semantic_collision_matrix.sha256,
        },
        "native_closure": {
            "build_manifest_file_sha256": sha256_file(manifest_path),
            "build_manifest_core_sha256": manifest.build_manifest_sha256,
            "builder_image_id": manifest.immutable_build_container_digest,
            "native_shared_object_sha256": manifest.native_shared_object.sha256,
            "bullet_collision_library_sha256": manifest.bullet_collision_library.sha256,
            "bullet_linear_math_library_sha256": manifest.bullet_linear_math_library.sha256,
        },
        "query": {
            "bound_plan_sha256": bound_plan_sha256,
            "joint_names": EXECUTOR_JOINT_NAMES,
            "joint_state_sequence_sha256": canonical_sha256(states),
            "geometry_receipt_sha256": geometry.receipt_sha256,
            "fk_receipt_sha256": fk_receipt.receipt_sha256,
            "fk_provider_configuration_sha256": provider.configuration_sha256,
            "world_sha256": world.world_sha256,
            "numeric_configuration_sha256": configuration.configuration_sha256,
            "request_sha256": request.request_sha256,
            "request_segment_count": len(request.segments),
            "receipt_sha256": receipt.receipt_sha256,
            "receipt_status": receipt.status,
            "clear_result_count": sum(item.status == "CLEAR" for item in receipt.results),
            "collision_rejection_count": len(rejected_pairs),
            "query_failure_count": 0,
            "rejected_pairs": rejected_pairs,
        },
        "evidence_claims": {
            "deployment_query_completed": True,
            "static_state_preflight_clear": receipt.status == "PASS",
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
        },
        "remaining_blockers": [
            "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
            "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
            "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
            "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
        ],
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--native-evidence-root", type=Path, required=True)
    parser.add_argument("--immutable-commit", required=True)
    parser.add_argument("--runtime-image-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_smoke_report(
        project_root=args.project_root,
        native_evidence_root=args.native_evidence_root,
        immutable_commit=args.immutable_commit,
        runtime_image_id=args.runtime_image_id,
    )
    payload = canonical_json_bytes(report) + b"\n"
    write_create_only(args.output.resolve(), payload)
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
