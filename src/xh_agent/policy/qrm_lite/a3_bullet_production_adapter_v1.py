"""Fail-closed production adapter contract for ADR-0024 A.3.

The module is query-only.  It can byte-bind and decode the controlled Panda
URDF/SRDF and the two original binary STL files, produce conservative Bullet
shape payloads, bind transforms returned by a separately frozen read-only FK
provider, and call the pinned float64 native CCD ABI.  It never imports Isaac,
creates a scene, writes an articulation target, steps physics, or executes a
robot command.

No local fixture can become production evidence.  A production query requires
the immutable build/container manifest, exact Bullet libraries, original mesh
bytes, and a real read-only FK provider.  Missing closure raises before native
code is loaded and is reported as ``NOT_AVAILABLE`` by the inspection helper.
"""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
from pathlib import Path
import stat
import struct
import time
from typing import Literal, Mapping, Protocol, Sequence
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3BulletNumericConfigurationV1,
    A3ChildPairCCDReceiptV1,
    A3ChildPairCCDRequestV1,
    A3ChildPairCCDResultV1,
    A3ConvexChildV1,
    A3LinkChildTransformSequenceV1,
    A3RigidTransformV1,
    A3SelfCollisionRejected,
    A3SelfCollisionWorldV1,
    EXPECTED_BULLET_FLOAT64_COLLISION_SHA256,
    EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256,
    bullet_shipped_margin_for_shape_v1,
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


CONTROLLED_PANDA_URDF_PATH = "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
CONTROLLED_PANDA_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
CONTROLLED_PANDA_SRDF_PATH = "robot_ws/src/xh_sim/config/m1a_panda.srdf"
CONTROLLED_PANDA_SRDF_SHA256 = "9e139275cb11f0403abf10894f1424b80a5024e94f7d4e6fadb8bb637017edda"
LINK2_STL_URI = "package://moveit_resources_panda_description/meshes/collision/link2.stl"
LINK4_STL_URI = "package://moveit_resources_panda_description/meshes/collision/link4.stl"
LINK2_STL_PATH = (
    "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link2.stl"
)
LINK4_STL_PATH = (
    "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link4.stl"
)
LINK2_STL_SHA256 = "370f7605a0fae3529db169ded50f52f171024aa792d4d773bc84197301f6a039"
LINK4_STL_SHA256 = "0180ebb5772ec9840cb049750cffb29a9ddc90311752a16ea34757782ef9e48d"
EXPECTED_CONTROLLED_PANDA_COLLISION_CHILDREN = 14
NATIVE_CORE_PATH = "src/xh_agent/policy/qrm_lite/a3_bullet_self_ccd_v1.cpp"
NATIVE_ADAPTER_PATH = "src/xh_agent/policy/qrm_lite/a3_bullet_native_adapter_v1.cpp"
FLOAT64_COLLISION_LIBRARY_PATH = "/usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24"
FLOAT64_LINEAR_MATH_LIBRARY_PATH = "/usr/lib/x86_64-linux-gnu/libLinearMath-float64.so.3.24"

EXPECTED_AUDITED_BULLET_HEADERS: Mapping[str, str] = {
    "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btConvexCast.h": (
        "5eca7f5931c6f954dc4d8b58ff75ec58112c46f96783b1c8de5a117c663a6c6b"
    ),
    "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btContinuousConvexCollision.h": (
        "7ba73189495d70659b257899352f3688585d8bff536db11f8c86cfa6931fe2e4"
    ),
    "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btGjkConvexCast.h": (
        "3409007ce88c742edba270851d8122fead8c766febf2de193525e0cc2a4694db"
    ),
    "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btSubSimplexConvexCast.h": (
        "74ffb324a2268abeca5c6757c09b238240be5de12a10f7443652df3f52d1c876"
    ),
    "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h": (
        "5771fe6eb5b51e91ca83c00c746216b821920b7a147875e01422add194e81805"
    ),
    "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h": (
        "bc5e3baf33e296de9367c247b25b9cd8803decee3d57896f87ec161568bedff0"
    ),
    "/usr/include/bullet/BulletCollision/CollisionShapes/btConvexShape.h": (
        "8d636b8b1ef7ec75926d48b03a4a448a44373ecf362329ce2150586bae4fb0c9"
    ),
    "/usr/include/bullet/BulletCollision/CollisionShapes/btConvexHullShape.h": (
        "209211f19fa98cc6a085d95266c4c15ee8a2bf3be5cc29403d858e8f26e97929"
    ),
    "/usr/include/bullet/BulletCollision/CollisionShapes/btBoxShape.h": (
        "8ec85f0c79e746088a186979c174a1ec5007a150e5281030f2e8321e4c1eeac7"
    ),
    "/usr/include/bullet/BulletCollision/CollisionShapes/btCylinderShape.h": (
        "097a80dbf01b8f5add103a0802ffab1201c285e7aaaf2aef8d94c17c193f6167"
    ),
    "/usr/include/bullet/BulletCollision/CollisionShapes/btCompoundShape.h": (
        "34413f9e250e66ec5f12f9c6e96c16b5f9eb06e842961c08085475b4c1478357"
    ),
    "/usr/include/bullet/LinearMath/btTransformUtil.h": (
        "add9774d16afa59c5cf0529df82133712cad28411e952b9c4cc00ffa8bfa37ee"
    ),
}
CANONICAL_BUILD_FLAGS = (
    "-std=c++17",
    "-O2",
    "-fPIC",
    "-shared",
    "-DBT_USE_DOUBLE_PRECISION",
    "-fno-fast-math",
    "-ffp-contract=off",
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3ProductionClosureUnavailable(A3SelfCollisionRejected):
    """Production geometry/FK/native closure is incomplete or crossed."""


def _canonical_model_sha256(model: BaseModel, field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={field}))


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise A3ProductionClosureUnavailable(
                f"A.3 production input is not a single-link regular file: {path}"
            )
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
            raise A3ProductionClosureUnavailable(f"A.3 production input changed: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_bound_bytes(path: Path, expected_sha256: str) -> bytes:
    raw = _read_regular_file_once(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise A3ProductionClosureUnavailable(f"A.3 byte binding differs: {path}")
    return raw


class A3FileBindingV1(FrozenModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)


class A3BulletFloat64BuildManifestV1(FrozenModel):
    """Immutable compiler/package/dependency identity for the native adapter."""

    schema_version: Literal["A3BulletFloat64BuildManifestV1"] = "A3BulletFloat64BuildManifestV1"
    bullet_package_version: Literal["3.24+dfsg-2.1build1"] = "3.24+dfsg-2.1build1"
    scalar_abi: Literal["float64"] = "float64"
    compiler: A3FileBindingV1
    compiler_version: str = Field(min_length=1)
    build_flags: tuple[str, ...]
    native_core: A3FileBindingV1
    native_adapter: A3FileBindingV1
    audited_bullet_headers: tuple[A3FileBindingV1, ...]
    complete_transitive_compile_manifest: A3FileBindingV1
    bullet_collision_library: A3FileBindingV1
    bullet_linear_math_library: A3FileBindingV1
    native_shared_object: A3FileBindingV1
    immutable_build_container_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    absolute_float64_rpath_only: Literal[True] = True
    no_fast_math: Literal[True] = True
    build_manifest_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_float64_closure(self) -> "A3BulletFloat64BuildManifestV1":
        if self.build_flags != CANONICAL_BUILD_FLAGS:
            raise ValueError("A.3 native build flags differ")
        if (
            self.native_core.path != NATIVE_CORE_PATH
            or self.native_adapter.path != NATIVE_ADAPTER_PATH
        ):
            raise ValueError("A.3 native source path differs")
        if (
            self.bullet_collision_library.path != FLOAT64_COLLISION_LIBRARY_PATH
            or self.bullet_collision_library.sha256 != EXPECTED_BULLET_FLOAT64_COLLISION_SHA256
            or self.bullet_linear_math_library.path != FLOAT64_LINEAR_MATH_LIBRARY_PATH
            or self.bullet_linear_math_library.sha256 != EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256
        ):
            raise ValueError("A.3 float64 Bullet library closure differs")
        observed_headers = {item.path: item.sha256 for item in self.audited_bullet_headers}
        if len(self.audited_bullet_headers) != len(
            EXPECTED_AUDITED_BULLET_HEADERS
        ) or observed_headers != dict(EXPECTED_AUDITED_BULLET_HEADERS):
            raise ValueError("A.3 audited Bullet header set differs")
        if self.build_manifest_sha256 != _canonical_model_sha256(self, "build_manifest_sha256"):
            raise ValueError("A.3 native build manifest digest differs")
        return self


class A3ShapePayloadV1(FrozenModel):
    schema_version: Literal["A3ShapePayloadV1"] = "A3ShapePayloadV1"
    link_path: str = Field(pattern=r"^/World/(?:Robot|M1B)/.+")
    child_index: int = Field(ge=0)
    shape_kind: Literal["BOX", "CYLINDER", "CONVEX_HULL"]
    shape_parameters: tuple[float, ...]
    decoded_vertices_xyz_m: tuple[tuple[float, float, float], ...]
    hull_construction_tolerance_m: float = Field(gt=0.0, le=1e-6)
    outward_padding_m: float = Field(ge=0.002)
    collision_margin_m: float = Field(gt=0.0)
    every_decoded_stl_vertex_retained: bool
    conservative_outer_envelope: Literal[True] = True
    geometry_equality_claimed: Literal[False] = False
    payload_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_shape(self) -> "A3ShapePayloadV1":
        values = (
            *self.shape_parameters,
            *(value for vertex in self.decoded_vertices_xyz_m for value in vertex),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A.3 shape payload contains NaN/Inf")
        expected_width = {"BOX": 3, "CYLINDER": 2, "CONVEX_HULL": 1}[self.shape_kind]
        if len(self.shape_parameters) != expected_width or any(
            value <= 0.0 for value in self.shape_parameters
        ):
            raise ValueError("A.3 shape parameters differ")
        is_hull = self.shape_kind == "CONVEX_HULL"
        required_margin = bullet_shipped_margin_for_shape_v1(self.shape_kind, self.shape_parameters)
        if self.collision_margin_m < required_margin:
            raise ValueError("A.3 shape margin is below the governed shipped value")
        if is_hull:
            if self.shape_parameters != (1.0,) or len(self.decoded_vertices_xyz_m) < 4:
                raise ValueError("A.3 convex-hull payload is incomplete")
            if not self.every_decoded_stl_vertex_retained:
                raise ValueError("A.3 convex hull omitted decoded STL vertices")
        elif self.decoded_vertices_xyz_m or self.every_decoded_stl_vertex_retained:
            raise ValueError("A.3 primitive contains STL-only fields")
        if self.payload_sha256 != _canonical_model_sha256(self, "payload_sha256"):
            raise ValueError("A.3 shape payload digest differs")
        return self


class A3ControlledPandaGeometryReceiptV1(FrozenModel):
    schema_version: Literal["A3ControlledPandaGeometryReceiptV1"] = (
        "A3ControlledPandaGeometryReceiptV1"
    )
    robot_description: A3FileBindingV1
    semantic_collision_matrix: A3FileBindingV1
    mesh_bindings: tuple[A3FileBindingV1, ...]
    children: tuple[A3ConvexChildV1, ...]
    shape_payloads: tuple[A3ShapePayloadV1, ...]
    acm_link_pairs: tuple[tuple[str, str], ...]
    expected_collision_child_count: Literal[14] = 14
    all_compounds_expanded: Literal[True] = True
    unknown_or_concave_shape_rejects: Literal[True] = True
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    contract_test_only: bool
    formal_evidence: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "A3ControlledPandaGeometryReceiptV1":
        keys = tuple((item.link_path, item.child_index) for item in self.children)
        payload_keys = tuple((item.link_path, item.child_index) for item in self.shape_payloads)
        if keys != tuple(sorted(keys)) or keys != payload_keys or len(keys) != 14:
            raise ValueError("A.3 controlled-Panda child coverage differs")
        if tuple(item.shape_parameters_sha256 for item in self.children) != tuple(
            item.payload_sha256 for item in self.shape_payloads
        ):
            raise ValueError("A.3 child/payload digest binding differs")
        if tuple(item.collision_margin_m for item in self.children) != tuple(
            item.collision_margin_m for item in self.shape_payloads
        ):
            raise ValueError("A.3 child/payload margin binding differs")
        canonical_acm = tuple(sorted(tuple(sorted(pair)) for pair in self.acm_link_pairs))
        if canonical_acm != self.acm_link_pairs or len(canonical_acm) != len(set(canonical_acm)):
            raise ValueError("A.3 ACM is not unique canonical order")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 geometry receipt digest differs")
        return self


class A3FKLinkSequenceV1(FrozenModel):
    link_path: str = Field(pattern=r"^/World/Robot/.+")
    transforms: tuple[A3RigidTransformV1, ...] = Field(min_length=2)


class A3ReadOnlyFKReceiptV1(FrozenModel):
    schema_version: Literal["A3ReadOnlyFKReceiptV1"] = "A3ReadOnlyFKReceiptV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    robot_description_sha256: str = Field(pattern=SHA256_PATTERN)
    geometry_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    executor_joint_state_sequence_sha256: str = Field(pattern=SHA256_PATTERN)
    executor_state_count: int = Field(ge=2)
    provider_implementation: A3FileBindingV1
    provider_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    link_sequences: tuple[A3FKLinkSequenceV1, ...] = Field(min_length=2)
    real_runtime_provider: bool
    contract_test_only: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    formal_evidence: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "A3ReadOnlyFKReceiptV1":
        if self.real_runtime_provider == self.contract_test_only:
            raise ValueError("A.3 FK receipt must be exactly real-runtime or contract-test")
        paths = tuple(item.link_path for item in self.link_sequences)
        if (
            paths != tuple(sorted(paths))
            or len(paths) != len(set(paths))
            or any(
                len(item.transforms) != self.executor_state_count for item in self.link_sequences
            )
        ):
            raise ValueError("A.3 FK link/state coverage differs")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 FK receipt digest differs")
        return self


class A3AttachedObjectGeometryV1(FrozenModel):
    """Frozen convex children/transforms for an already attached object."""

    schema_version: Literal["A3AttachedObjectGeometryV1"] = "A3AttachedObjectGeometryV1"
    attached_object_path: str = Field(pattern=r"^/World/M1B/.+")
    attachment_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    children: tuple[A3ConvexChildV1, ...] = Field(min_length=1)
    shape_payloads: tuple[A3ShapePayloadV1, ...] = Field(min_length=1)
    transforms: tuple[A3LinkChildTransformSequenceV1, ...] = Field(min_length=1)
    allowed_touch_link_pairs: tuple[tuple[str, str], ...]
    executor_state_count: int = Field(ge=2)
    complete_compound_expansion: Literal[True] = True
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "A3AttachedObjectGeometryV1":
        keys = tuple((item.link_path, item.child_index) for item in self.children)
        payload_keys = tuple((item.link_path, item.child_index) for item in self.shape_payloads)
        transform_keys = tuple((item.link_path, item.child_index) for item in self.transforms)
        if (
            keys != tuple(sorted(keys))
            or len(keys) != len(set(keys))
            or keys != payload_keys
            or keys != transform_keys
            or any(link != self.attached_object_path for link, _ in keys)
            or any(len(item.transforms) != self.executor_state_count for item in self.transforms)
            or tuple(item.shape_parameters_sha256 for item in self.children)
            != tuple(item.payload_sha256 for item in self.shape_payloads)
            or tuple(item.collision_margin_m for item in self.children)
            != tuple(item.collision_margin_m for item in self.shape_payloads)
        ):
            raise ValueError("A.3 attached-object child/payload/transform coverage differs")
        canonical_touch = tuple(
            sorted(tuple(sorted(pair)) for pair in self.allowed_touch_link_pairs)
        )
        if (
            canonical_touch != self.allowed_touch_link_pairs
            or len(canonical_touch) != len(set(canonical_touch))
            or any(
                self.attached_object_path not in pair
                or not any(path.startswith("/World/Robot/") for path in pair)
                for pair in canonical_touch
            )
        ):
            raise ValueError("A.3 attached-object touch allowlist differs")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 attached-object geometry digest differs")
        return self


class A3ReadOnlyFKProviderV1(Protocol):
    implementation_path: str
    implementation_sha256: str
    configuration_sha256: str
    real_runtime_provider: bool
    query_only: bool

    def query_link_transforms(
        self,
        *,
        joint_names: tuple[str, ...],
        joint_state_sequence: tuple[tuple[float, ...], ...],
        link_paths: tuple[str, ...],
    ) -> Mapping[str, Sequence[A3RigidTransformV1]]: ...


class A3ProductionClosureInspectionV1(FrozenModel):
    schema_version: Literal["A3ProductionClosureInspectionV1"] = "A3ProductionClosureInspectionV1"
    status: Literal["READY_FOR_QUERY_ONLY_CONTRACT", "NOT_AVAILABLE"]
    project_root: str = Field(min_length=1)
    checked_bindings: tuple[A3FileBindingV1, ...]
    missing_requirements: tuple[str, ...]
    native_build_manifest_present: bool
    original_meshes_present: bool
    real_fk_provider_bound: bool
    real_isaac_started: Literal[False] = False
    physical_execution_performed: Literal[False] = False
    training_performed: Literal[False] = False
    production_binding_set: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    formal_execution_eligible: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def status_and_digest(self) -> "A3ProductionClosureInspectionV1":
        if (self.status == "NOT_AVAILABLE") != bool(self.missing_requirements):
            raise ValueError("A.3 closure inspection status differs from missing set")
        if self.status == "READY_FOR_QUERY_ONLY_CONTRACT" and not (
            self.native_build_manifest_present
            and self.original_meshes_present
            and self.real_fk_provider_bound
        ):
            raise ValueError("A.3 closure inspection READY lacks a required capability")
        if tuple(sorted(set(self.missing_requirements))) != self.missing_requirements:
            raise ValueError("A.3 closure blockers are not unique canonical order")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 closure inspection digest differs")
        return self


def _float_tuple(raw: str | None, width: int, *, default: tuple[float, ...]) -> tuple[float, ...]:
    if raw is None:
        return default
    try:
        values = tuple(float(value) for value in raw.split())
    except ValueError as exc:
        raise A3ProductionClosureUnavailable("A.3 URDF numeric field is malformed") from exc
    if len(values) != width or not all(math.isfinite(value) for value in values):
        raise A3ProductionClosureUnavailable("A.3 URDF numeric field width/value differs")
    return values


def _rpy_to_wxyz(rpy: tuple[float, float, float]) -> tuple[float, float, float, float]:
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )


def _compose_transform(left: A3RigidTransformV1, right: A3RigidTransformV1) -> A3RigidTransformV1:
    lw, lx, ly, lz = left.rotation_world_wxyz
    rw, rx, ry, rz = right.rotation_world_wxyz
    rotation = (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )
    x, y, z = right.translation_world_m
    translated = (
        (1 - 2 * (ly * ly + lz * lz)) * x
        + 2 * (lx * ly - lw * lz) * y
        + 2 * (lx * lz + lw * ly) * z,
        2 * (lx * ly + lw * lz) * x
        + (1 - 2 * (lx * lx + lz * lz)) * y
        + 2 * (ly * lz - lw * lx) * z,
        2 * (lx * lz - lw * ly) * x
        + 2 * (ly * lz + lw * lx) * y
        + (1 - 2 * (lx * lx + ly * ly)) * z,
    )
    return A3RigidTransformV1(
        translation_world_m=tuple(
            origin + offset for origin, offset in zip(left.translation_world_m, translated)
        ),
        rotation_world_wxyz=rotation,
    )


def _decode_all_binary_stl_vertices(raw: bytes) -> tuple[tuple[float, float, float], ...]:
    if len(raw) < 84:
        raise A3ProductionClosureUnavailable("A.3 binary STL is truncated")
    count = struct.unpack_from("<I", raw, 80)[0]
    if count == 0 or len(raw) != 84 + 50 * count:
        raise A3ProductionClosureUnavailable("A.3 binary STL count/length differs")
    vertices: list[tuple[float, float, float]] = []
    for index in range(count):
        values = struct.unpack_from("<12fH", raw, 84 + index * 50)
        for vertex_index in range(3):
            vertex = tuple(
                float(value) for value in values[3 + vertex_index * 3 : 6 + vertex_index * 3]
            )
            if not all(math.isfinite(value) for value in vertex):
                raise A3ProductionClosureUnavailable("A.3 binary STL contains NaN/Inf")
            vertices.append(vertex)
    if len(set(vertices)) < 4:
        raise A3ProductionClosureUnavailable("A.3 binary STL is degenerate")
    return tuple(vertices)


def _shape_payload(
    *,
    link_path: str,
    child_index: int,
    shape_kind: Literal["BOX", "CYLINDER", "CONVEX_HULL"],
    parameters: tuple[float, ...],
    vertices: tuple[tuple[float, float, float], ...],
    configuration: A3BulletNumericConfigurationV1,
) -> A3ShapePayloadV1:
    payload = {
        "schema_version": "A3ShapePayloadV1",
        "link_path": link_path,
        "child_index": child_index,
        "shape_kind": shape_kind,
        "shape_parameters": parameters,
        "decoded_vertices_xyz_m": vertices,
        "hull_construction_tolerance_m": configuration.convex_hull_construction_tolerance_m,
        "outward_padding_m": configuration.convex_hull_outward_padding_m,
        "collision_margin_m": bullet_shipped_margin_for_shape_v1(shape_kind, parameters),
        "every_decoded_stl_vertex_retained": shape_kind == "CONVEX_HULL",
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    return A3ShapePayloadV1(**payload, payload_sha256=canonical_sha256(payload))


def build_controlled_panda_geometry_v1(
    *,
    project_root: Path,
    link2_stl_path: Path = Path(LINK2_STL_PATH),
    link4_stl_path: Path = Path(LINK4_STL_PATH),
    configuration: A3BulletNumericConfigurationV1 | None = None,
    contract_test_only: bool = False,
) -> A3ControlledPandaGeometryReceiptV1:
    """Decode the exact controlled-Panda collision tree without loading a scene."""

    config = configuration or canonical_a3_bullet_numeric_configuration_v1()
    urdf_path = project_root / CONTROLLED_PANDA_URDF_PATH
    srdf_path = project_root / CONTROLLED_PANDA_SRDF_PATH
    urdf_raw = _read_bound_bytes(urdf_path, CONTROLLED_PANDA_URDF_SHA256)
    srdf_raw = _read_bound_bytes(srdf_path, CONTROLLED_PANDA_SRDF_SHA256)
    srdf_sha = CONTROLLED_PANDA_SRDF_SHA256
    mesh_paths = {LINK2_STL_URI: link2_stl_path, LINK4_STL_URI: link4_stl_path}
    mesh_hashes = {LINK2_STL_URI: LINK2_STL_SHA256, LINK4_STL_URI: LINK4_STL_SHA256}
    mesh_raw = {uri: _read_bound_bytes(path, mesh_hashes[uri]) for uri, path in mesh_paths.items()}
    try:
        root = ET.fromstring(urdf_raw)
        srdf_root = ET.fromstring(srdf_raw)
    except ET.ParseError as exc:
        raise A3ProductionClosureUnavailable("A.3 URDF/SRDF XML is malformed") from exc
    if root.tag != "robot" or srdf_root.tag != "robot":
        raise A3ProductionClosureUnavailable("A.3 robot description root differs")
    children: list[A3ConvexChildV1] = []
    payloads: list[A3ShapePayloadV1] = []
    for link in root.findall("link"):
        link_name = link.attrib.get("name")
        if not link_name:
            raise A3ProductionClosureUnavailable("A.3 URDF link has no name")
        link_path = f"/World/Robot/{link_name}"
        for child_index, collision in enumerate(link.findall("collision")):
            origin = collision.find("origin")
            translation = _float_tuple(
                None if origin is None else origin.attrib.get("xyz"), 3, default=(0.0, 0.0, 0.0)
            )
            rpy = _float_tuple(
                None if origin is None else origin.attrib.get("rpy"), 3, default=(0.0, 0.0, 0.0)
            )
            geometry = collision.find("geometry")
            if geometry is None or len(geometry) != 1:
                raise A3ProductionClosureUnavailable("A.3 collision geometry is missing/compound")
            shape = geometry[0]
            vertices: tuple[tuple[float, float, float], ...] = ()
            source_path = CONTROLLED_PANDA_URDF_PATH
            source_sha = CONTROLLED_PANDA_URDF_SHA256
            if shape.tag == "box":
                kind: Literal["BOX", "CYLINDER", "CONVEX_HULL"] = "BOX"
                parameters = _float_tuple(shape.attrib.get("size"), 3, default=())
                smallest = min(parameters) * 0.5
                maximum = math.sqrt(sum((value * 0.5) ** 2 for value in parameters))
            elif shape.tag == "cylinder":
                kind = "CYLINDER"
                radius, length = _float_tuple(
                    " ".join((shape.attrib.get("radius", ""), shape.attrib.get("length", ""))),
                    2,
                    default=(),
                )
                parameters = (radius, length)
                smallest = min(radius, length * 0.5)
                maximum = math.hypot(radius, length * 0.5)
            elif shape.tag == "mesh":
                kind = "CONVEX_HULL"
                uri = shape.attrib.get("filename")
                scale = _float_tuple(shape.attrib.get("scale"), 3, default=(1.0, 1.0, 1.0))
                if uri not in mesh_raw or scale != (1.0, 1.0, 1.0):
                    raise A3ProductionClosureUnavailable("A.3 mesh URI/scale is unbound")
                vertices = _decode_all_binary_stl_vertices(mesh_raw[uri])
                parameters = (1.0,)
                source_path = str(mesh_paths[uri])
                source_sha = mesh_hashes[uri]
                smallest = config.convex_hull_construction_tolerance_m
                maximum = max(
                    math.sqrt(sum(value * value for value in vertex)) for vertex in vertices
                )
            else:
                raise A3ProductionClosureUnavailable(
                    f"A.3 unsupported collision shape: {shape.tag}"
                )
            if any(value <= 0.0 for value in parameters):
                raise A3ProductionClosureUnavailable("A.3 collision dimensions are non-positive")
            payload = _shape_payload(
                link_path=link_path,
                child_index=child_index,
                shape_kind=kind,
                parameters=parameters,
                vertices=vertices,
                configuration=config,
            )
            local_transform = A3RigidTransformV1(
                translation_world_m=translation,
                rotation_world_wxyz=_rpy_to_wxyz(rpy),
            )
            child_data = {
                "schema_version": "A3ConvexChildV1",
                "link_path": link_path,
                "child_index": child_index,
                "shape_kind": kind,
                "local_transform": local_transform.model_dump(mode="json"),
                "shape_parameters_sha256": payload.payload_sha256,
                "source_asset_path": source_path,
                "source_asset_sha256": source_sha,
                "source_vertex_count": len(vertices),
                "decoded_vertices_sha256": canonical_sha256(vertices) if vertices else None,
                "smallest_conservative_radius_m": smallest,
                "maximum_angular_motion_radius_m": maximum
                + payload.outward_padding_m
                + payload.collision_margin_m,
                "collision_margin_m": payload.collision_margin_m,
                "outward_padding_m": payload.outward_padding_m,
                "conservative_outer_envelope": True,
                "geometry_equality_claimed": False,
            }
            children.append(
                A3ConvexChildV1(
                    **child_data,
                    child_sha256=canonical_sha256(child_data),
                )
            )
            payloads.append(payload)
    ordered = sorted(
        zip(children, payloads), key=lambda item: (item[0].link_path, item[0].child_index)
    )
    if len(ordered) != EXPECTED_CONTROLLED_PANDA_COLLISION_CHILDREN:
        raise A3ProductionClosureUnavailable("A.3 controlled-Panda collision count differs")
    acm = []
    for item in srdf_root.findall("disable_collisions"):
        left, right = item.attrib.get("link1"), item.attrib.get("link2")
        if not left or not right or left == right:
            raise A3ProductionClosureUnavailable("A.3 SRDF ACM entry is malformed")
        acm.append(tuple(sorted((f"/World/Robot/{left}", f"/World/Robot/{right}"))))
    data = {
        "schema_version": "A3ControlledPandaGeometryReceiptV1",
        "robot_description": {
            "path": CONTROLLED_PANDA_URDF_PATH,
            "sha256": CONTROLLED_PANDA_URDF_SHA256,
        },
        "semantic_collision_matrix": {"path": CONTROLLED_PANDA_SRDF_PATH, "sha256": srdf_sha},
        "mesh_bindings": [
            {"path": str(mesh_paths[uri]), "sha256": mesh_hashes[uri]}
            for uri in (LINK2_STL_URI, LINK4_STL_URI)
        ],
        "children": [item[0].model_dump(mode="json") for item in ordered],
        "shape_payloads": [item[1].model_dump(mode="json") for item in ordered],
        "acm_link_pairs": sorted(set(acm)),
        "expected_collision_child_count": 14,
        "all_compounds_expanded": True,
        "unknown_or_concave_shape_rejects": True,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "contract_test_only": contract_test_only,
        "formal_evidence": False,
    }
    return A3ControlledPandaGeometryReceiptV1(**data, receipt_sha256=canonical_sha256(data))


def produce_read_only_fk_receipt_v1(
    *,
    bound_plan_sha256: str,
    geometry: A3ControlledPandaGeometryReceiptV1,
    joint_names: tuple[str, ...],
    joint_state_sequence: tuple[tuple[float, ...], ...],
    provider: A3ReadOnlyFKProviderV1,
) -> A3ReadOnlyFKReceiptV1:
    """Call a frozen FK query provider and bind every input/output byte."""

    if not provider.query_only or len(joint_state_sequence) < 2 or not joint_names:
        raise A3ProductionClosureUnavailable("A.3 FK provider/state sequence is unavailable")
    if any(
        len(state) != len(joint_names) or not all(math.isfinite(value) for value in state)
        for state in joint_state_sequence
    ):
        raise A3ProductionClosureUnavailable("A.3 FK joint-state sequence is malformed")
    provider_path = Path(provider.implementation_path)
    if (
        hashlib.sha256(_read_regular_file_once(provider_path)).hexdigest()
        != provider.implementation_sha256
    ):
        raise A3ProductionClosureUnavailable("A.3 FK provider implementation digest differs")
    link_paths = tuple(sorted({child.link_path for child in geometry.children}))
    try:
        raw_sequences = provider.query_link_transforms(
            joint_names=joint_names,
            joint_state_sequence=joint_state_sequence,
            link_paths=link_paths,
        )
    except Exception as exc:
        raise A3ProductionClosureUnavailable("A.3 FK provider query failed") from exc
    if set(raw_sequences) != set(link_paths):
        raise A3ProductionClosureUnavailable("A.3 FK provider link coverage differs")
    sequences = tuple(
        A3FKLinkSequenceV1(link_path=path, transforms=tuple(raw_sequences[path]))
        for path in link_paths
    )
    if any(len(item.transforms) != len(joint_state_sequence) for item in sequences):
        raise A3ProductionClosureUnavailable("A.3 FK provider state coverage differs")
    data = {
        "schema_version": "A3ReadOnlyFKReceiptV1",
        "bound_plan_sha256": bound_plan_sha256,
        "robot_description_sha256": geometry.robot_description.sha256,
        "geometry_receipt_sha256": geometry.receipt_sha256,
        "executor_joint_state_sequence_sha256": canonical_sha256(
            {"joint_names": joint_names, "joint_state_sequence": joint_state_sequence}
        ),
        "executor_state_count": len(joint_state_sequence),
        "provider_implementation": {
            "path": provider.implementation_path,
            "sha256": provider.implementation_sha256,
        },
        "provider_configuration_sha256": provider.configuration_sha256,
        "link_sequences": [item.model_dump(mode="json") for item in sequences],
        "real_runtime_provider": provider.real_runtime_provider,
        "contract_test_only": not provider.real_runtime_provider,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_evidence": False,
    }
    return A3ReadOnlyFKReceiptV1(**data, receipt_sha256=canonical_sha256(data))


def build_self_collision_world_from_fk_v1(
    *,
    geometry: A3ControlledPandaGeometryReceiptV1,
    fk_receipt: A3ReadOnlyFKReceiptV1,
    require_real_runtime_provider: bool,
    attached_objects: tuple[A3AttachedObjectGeometryV1, ...] = (),
) -> A3SelfCollisionWorldV1:
    if (
        fk_receipt.geometry_receipt_sha256 != geometry.receipt_sha256
        or fk_receipt.robot_description_sha256 != geometry.robot_description.sha256
        or (require_real_runtime_provider and not fk_receipt.real_runtime_provider)
    ):
        raise A3ProductionClosureUnavailable("A.3 FK/geometry production binding differs")
    links = {item.link_path: item.transforms for item in fk_receipt.link_sequences}
    transforms = tuple(
        A3LinkChildTransformSequenceV1(
            link_path=child.link_path,
            child_index=child.child_index,
            transforms=tuple(
                _compose_transform(link_transform, child.local_transform)
                for link_transform in links[child.link_path]
            ),
        )
        for child in geometry.children
    )
    if any(
        item.executor_state_count != fk_receipt.executor_state_count for item in attached_objects
    ):
        raise A3ProductionClosureUnavailable("A.3 attached-object state coverage differs")
    attached_children = tuple(child for item in attached_objects for child in item.children)
    attached_transforms = tuple(
        transform for item in attached_objects for transform in item.transforms
    )
    child_by_key = {
        (item.link_path, item.child_index): item
        for item in (*geometry.children, *attached_children)
    }
    transform_by_key = {
        (item.link_path, item.child_index): item for item in (*transforms, *attached_transforms)
    }
    if len(child_by_key) != len(geometry.children) + len(attached_children) or set(
        child_by_key
    ) != set(transform_by_key):
        raise A3ProductionClosureUnavailable("A.3 combined robot/attached child coverage differs")
    ordered_keys = tuple(sorted(child_by_key))
    all_children = tuple(child_by_key[key] for key in ordered_keys)
    all_transforms = tuple(transform_by_key[key] for key in ordered_keys)
    all_acm = tuple(
        sorted(
            set(geometry.acm_link_pairs).union(
                pair for item in attached_objects for pair in item.allowed_touch_link_pairs
            )
        )
    )
    attached_paths = tuple(sorted(item.attached_object_path for item in attached_objects))
    if len(attached_paths) != len(set(attached_paths)):
        raise A3ProductionClosureUnavailable("A.3 attached-object identity repeats")
    data = {
        "schema_version": "A3SelfCollisionWorldV1",
        "children": [item.model_dump(mode="json") for item in all_children],
        "transforms": [item.model_dump(mode="json") for item in all_transforms],
        "acm_link_pairs": all_acm,
        "attached_object_paths": attached_paths,
        "executor_state_count": fk_receipt.executor_state_count,
    }
    return A3SelfCollisionWorldV1(**data, world_sha256=canonical_sha256(data))


def inspect_a3_production_closure_v1(
    *,
    project_root: Path,
    native_build_manifest_path: Path | None = None,
    real_fk_provider_binding: A3FileBindingV1 | None = None,
) -> A3ProductionClosureInspectionV1:
    """Perform a local byte-only capability check; never import/load native code."""

    root = project_root.resolve()
    expected = (
        (root / CONTROLLED_PANDA_URDF_PATH, CONTROLLED_PANDA_URDF_SHA256, "CONTROLLED_PANDA_URDF"),
        (Path(LINK2_STL_PATH), LINK2_STL_SHA256, "ORIGINAL_LINK2_STL"),
        (Path(LINK4_STL_PATH), LINK4_STL_SHA256, "ORIGINAL_LINK4_STL"),
        (
            Path(FLOAT64_COLLISION_LIBRARY_PATH),
            EXPECTED_BULLET_FLOAT64_COLLISION_SHA256,
            "PINNED_BULLET_COLLISION_FLOAT64",
        ),
        (
            Path(FLOAT64_LINEAR_MATH_LIBRARY_PATH),
            EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256,
            "PINNED_BULLET_LINEAR_MATH_FLOAT64",
        ),
    )
    checked: list[A3FileBindingV1] = []
    missing: list[str] = []
    for path, digest, name in expected:
        try:
            _read_bound_bytes(path, digest)
        except (OSError, A3ProductionClosureUnavailable):
            missing.append(name)
        else:
            checked.append(A3FileBindingV1(path=str(path), sha256=digest))
    if native_build_manifest_path is None:
        missing.append("PINNED_NATIVE_BUILD_MANIFEST_AND_SHARED_OBJECT")
    else:
        try:
            raw = _read_regular_file_once(native_build_manifest_path)
            manifest = A3BulletFloat64BuildManifestV1.model_validate_json(raw)
            for binding in (
                manifest.compiler,
                manifest.native_core,
                manifest.native_adapter,
                manifest.complete_transitive_compile_manifest,
                manifest.bullet_collision_library,
                manifest.bullet_linear_math_library,
                manifest.native_shared_object,
                *manifest.audited_bullet_headers,
            ):
                path = Path(binding.path)
                if not path.is_absolute():
                    path = root / path
                _read_bound_bytes(path, binding.sha256)
        except Exception:
            missing.append("PINNED_NATIVE_BUILD_MANIFEST_AND_SHARED_OBJECT")
    if real_fk_provider_binding is None:
        missing.append("REAL_QUERY_ONLY_FK_PROVIDER_BINDING")
    else:
        try:
            _read_bound_bytes(Path(real_fk_provider_binding.path), real_fk_provider_binding.sha256)
        except (OSError, A3ProductionClosureUnavailable):
            missing.append("REAL_QUERY_ONLY_FK_PROVIDER_BINDING")
    missing = sorted(set(missing))
    data = {
        "schema_version": "A3ProductionClosureInspectionV1",
        "status": "NOT_AVAILABLE" if missing else "READY_FOR_QUERY_ONLY_CONTRACT",
        "project_root": str(root),
        "checked_bindings": [item.model_dump(mode="json") for item in checked],
        "missing_requirements": missing,
        "native_build_manifest_present": native_build_manifest_path is not None
        and "PINNED_NATIVE_BUILD_MANIFEST_AND_SHARED_OBJECT" not in missing,
        "original_meshes_present": not {"ORIGINAL_LINK2_STL", "ORIGINAL_LINK4_STL"}.intersection(
            missing
        ),
        "real_fk_provider_bound": real_fk_provider_binding is not None
        and "REAL_QUERY_ONLY_FK_PROVIDER_BINDING" not in missing,
        "real_isaac_started": False,
        "physical_execution_performed": False,
        "training_performed": False,
        "production_binding_set": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_execution_eligible": False,
    }
    return A3ProductionClosureInspectionV1(**data, receipt_sha256=canonical_sha256(data))


class A3NativeBulletBackendV1:
    """ctypes receipt producer for the flat query-only native ABI."""

    real_native_backend = True

    def __init__(self, *, project_root: Path, manifest: A3BulletFloat64BuildManifestV1) -> None:
        self.project_root = project_root.resolve()
        self.manifest = manifest
        bindings = (
            manifest.native_core,
            manifest.native_adapter,
            manifest.complete_transitive_compile_manifest,
            manifest.bullet_collision_library,
            manifest.bullet_linear_math_library,
            manifest.native_shared_object,
            *manifest.audited_bullet_headers,
        )
        for binding in bindings:
            path = Path(binding.path)
            if not path.is_absolute():
                path = self.project_root / path
            _read_bound_bytes(path, binding.sha256)
        if os.name != "posix" or not Path("/proc/self/fd").is_dir():
            raise A3ProductionClosureUnavailable("A.3 native FD loading is unavailable")
        native_path = Path(manifest.native_shared_object.path)
        if not native_path.is_absolute():
            native_path = self.project_root / native_path
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(native_path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise A3ProductionClosureUnavailable("A.3 native module is not immutable regular")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            if digest.hexdigest() != manifest.native_shared_object.sha256:
                raise A3ProductionClosureUnavailable("A.3 native module FD digest differs")
            os.lseek(descriptor, 0, os.SEEK_SET)
            self._library = ctypes.CDLL(f"/proc/self/fd/{descriptor}")
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise A3ProductionClosureUnavailable("A.3 native module changed during load")
        finally:
            os.close(descriptor)
        self._query = self._library.m2c_a3_flat_child_pair_ccd_v1
        self._query.restype = ctypes.c_int
        pointer = ctypes.POINTER(ctypes.c_double)
        self._query.argtypes = [
            ctypes.c_int,
            pointer,
            ctypes.c_size_t,
            pointer,
            ctypes.c_size_t,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            pointer,
            pointer,
            ctypes.c_int,
            pointer,
            ctypes.c_size_t,
            pointer,
            ctypes.c_size_t,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            pointer,
            pointer,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.implementation_sha256 = manifest.native_shared_object.sha256

    @staticmethod
    def _array(values: Sequence[float]) -> ctypes.Array[ctypes.c_double]:
        return (ctypes.c_double * len(values))(*values)

    @staticmethod
    def _transform(value: A3RigidTransformV1) -> ctypes.Array[ctypes.c_double]:
        return A3NativeBulletBackendV1._array(
            (*value.translation_world_m, *value.rotation_world_wxyz)
        )

    def query(
        self,
        request: A3ChildPairCCDRequestV1,
        *,
        children: Sequence[A3ConvexChildV1],
        shape_payloads: Sequence[A3ShapePayloadV1],
        configuration: A3BulletNumericConfigurationV1,
    ) -> A3ChildPairCCDReceiptV1:
        if request.numeric_configuration_sha256 != configuration.configuration_sha256:
            raise A3ProductionClosureUnavailable("A.3 native request/configuration crossed")
        child_map = {(item.link_path, item.child_index): item for item in children}
        payload_map = {(item.link_path, item.child_index): item for item in shape_payloads}
        if set(child_map) != set(payload_map) or any(
            child_map[key].shape_parameters_sha256 != payload_map[key].payload_sha256
            for key in child_map
        ):
            raise A3ProductionClosureUnavailable("A.3 native child/payload closure differs")
        started = time.monotonic_ns()
        results: list[A3ChildPairCCDResultV1] = []
        kinds = {"BOX": 1, "CYLINDER": 2, "CONVEX_HULL": 3}
        for index, segment in enumerate(request.segments):
            if time.monotonic_ns() - started > configuration.query_timeout_ns:
                results.extend(
                    A3ChildPairCCDResultV1(
                        pair_index=remaining,
                        status="REJECT_QUERY_FAILURE",
                        discrete_start_clear=False,
                        discrete_end_clear=False,
                        continuous_query_completed=False,
                        failure_code=-205,
                        iteration_count=0,
                    )
                    for remaining in range(index, len(request.segments))
                )
                break
            left_key = (segment.link_a, segment.child_a)
            right_key = (segment.link_b, segment.child_b)
            if left_key not in payload_map or right_key not in payload_map:
                raise A3ProductionClosureUnavailable("A.3 native segment references unknown child")
            left, right = payload_map[left_key], payload_map[right_key]
            left_parameters = self._array(left.shape_parameters)
            right_parameters = self._array(right.shape_parameters)
            left_vertices_flat = tuple(
                value for vertex in left.decoded_vertices_xyz_m for value in vertex
            )
            right_vertices_flat = tuple(
                value for vertex in right.decoded_vertices_xyz_m for value in vertex
            )
            left_vertices = self._array(left_vertices_flat) if left_vertices_flat else None
            right_vertices = self._array(right_vertices_flat) if right_vertices_flat else None
            toi, failure, iterations = (
                ctypes.c_double(math.nan),
                ctypes.c_int(-999),
                ctypes.c_int(0),
            )
            start_clear, end_clear, completed = ctypes.c_int(0), ctypes.c_int(0), ctypes.c_int(0)
            code = int(
                self._query(
                    kinds[left.shape_kind],
                    left_parameters,
                    len(left.shape_parameters),
                    left_vertices,
                    len(left.decoded_vertices_xyz_m),
                    left.hull_construction_tolerance_m,
                    left.outward_padding_m,
                    left.collision_margin_m,
                    self._transform(segment.from_a),
                    self._transform(segment.to_a),
                    kinds[right.shape_kind],
                    right_parameters,
                    len(right.shape_parameters),
                    right_vertices,
                    len(right.decoded_vertices_xyz_m),
                    right.hull_construction_tolerance_m,
                    right.outward_padding_m,
                    right.collision_margin_m,
                    self._transform(segment.from_b),
                    self._transform(segment.to_b),
                    configuration.contact_distance_threshold_m,
                    configuration.toi_comparison_tolerance,
                    ctypes.byref(toi),
                    ctypes.byref(failure),
                    ctypes.byref(iterations),
                    ctypes.byref(start_clear),
                    ctypes.byref(end_clear),
                    ctypes.byref(completed),
                )
            )
            if code == 0 and failure.value == 0:
                status = "CLEAR"
                toi_value = None
                failure_value = None
            elif code == 1:
                status = "REJECT_COLLISION"
                toi_value = (
                    toi.value if math.isfinite(toi.value) and 0.0 <= toi.value <= 1.0 else None
                )
                failure_value = (
                    failure.value if failure.value != 0 else (-1 if toi_value is None else None)
                )
            else:
                status = "REJECT_QUERY_FAILURE"
                toi_value = None
                failure_value = failure.value if failure.value != 0 else -200
            results.append(
                A3ChildPairCCDResultV1(
                    pair_index=index,
                    status=status,
                    discrete_start_clear=bool(start_clear.value),
                    discrete_end_clear=bool(end_clear.value),
                    continuous_query_completed=bool(completed.value),
                    time_of_impact=toi_value,
                    failure_code=failure_value,
                    iteration_count=max(0, iterations.value),
                )
            )
        data = {
            "schema_version": "A3ChildPairCCDReceiptV1",
            "request_sha256": request.request_sha256,
            "backend_implementation_sha256": self.implementation_sha256,
            "bullet_collision_library_sha256": self.manifest.bullet_collision_library.sha256,
            "bullet_linear_math_library_sha256": self.manifest.bullet_linear_math_library.sha256,
            "scalar_abi": "float64",
            "results": [item.model_dump(mode="json") for item in results],
            "status": "PASS" if all(item.status == "CLEAR" for item in results) else "REJECT",
            "real_native_backend": True,
            "contract_test_only": False,
            "formal_evidence": False,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return A3ChildPairCCDReceiptV1(**data, receipt_sha256=canonical_sha256(data))
