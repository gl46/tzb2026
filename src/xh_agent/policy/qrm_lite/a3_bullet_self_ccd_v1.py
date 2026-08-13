"""ADR-0024 A.3 conservative self-collision contract.

This module is intentionally non-actuating.  It decodes byte-bound binary STL
vertices, represents every collision element as one or more convex children,
constructs the complete non-ACM child-pair/subdivision request, and validates
the receipt returned by a separately built double-precision Bullet backend.
It never imports Isaac, creates a scene, writes a target, or steps physics.

The native backend is not optional for a production PASS.  Contract tests use
an explicitly synthetic backend and can prove schema/order/fail-closed
behavior only; their receipts are permanently ineligible for formal evidence.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import stat
import struct
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


ADR_0024_PATH = "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"
BULLET_VERSION = "3.24"
EXPECTED_BULLET_FLOAT64_COLLISION_SHA256 = (
    "baa16598bc6a54aa51c825af6680807b548decb33ff11f469ac24c09f54826c2"
)
EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256 = (
    "5d3fe859ad08f78fac1e51ed85dddd9e39da501a0d566e86e00da5565d9e5343"
)
SUPPORTED_SHAPES = frozenset({"BOX", "CYLINDER", "CONVEX_HULL"})


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3SelfCollisionRejected(RuntimeError):
    """A missing/ambiguous input rejects the complete plan before actuation."""


def _canonical_model_sha256(model: BaseModel, field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={field}))


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise A3SelfCollisionRejected(f"A.3 input is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)

        def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after):
            raise A3SelfCollisionRejected(f"A.3 input changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


class A3BulletNumericConfigurationV1(FrozenModel):
    """Implementation-selected values within ADR-0024's human bounds."""

    schema_version: Literal["A3BulletNumericConfigurationV1"] = "A3BulletNumericConfigurationV1"
    bullet_version: Literal["3.24"] = BULLET_VERSION
    scalar_abi: Literal["float64"] = "float64"
    convex_hull_construction_tolerance_m: float = Field(ge=0.0, le=1e-6)
    convex_hull_outward_padding_m: float = Field(ge=0.002)
    box_collision_margin_m: float = Field(ge=0.04)
    cylinder_collision_margin_m: float = Field(ge=0.04)
    convex_hull_collision_margin_m: float = Field(ge=0.04)
    allowed_penetration_m: Literal[0.0] = 0.0
    contact_distance_threshold_m: float = Field(ge=0.001)
    toi_min: Literal[0.0] = 0.0
    toi_max: Literal[1.0] = 1.0
    toi_comparison_tolerance: float = Field(gt=0.0, le=1e-6)
    maximum_ccd_iterations: int = Field(ge=32)
    native_continuous_algorithm_iteration_cap: Literal[64] = 64
    maximum_subdivisions_per_executor_segment: int = Field(ge=1)
    query_timeout_ns: int = Field(gt=0)
    iteration_exhaustion_rejects: Literal[True] = True
    nonfinite_rejects: Literal[True] = True
    degenerate_shape_rejects: Literal[True] = True
    initial_overlap_rejects: Literal[True] = True
    endpoint_overlap_rejects: Literal[True] = True
    subdivision_boundary_overlap_rejects: Literal[True] = True
    unknown_or_concave_shape_rejects: Literal[True] = True
    compound_expansion_required: Literal[True] = True
    all_ambiguity_resolves_to_rejection: Literal[True] = True
    provenance: dict[str, str] = Field(min_length=15)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_bounds_and_digest(self) -> "A3BulletNumericConfigurationV1":
        values = (
            self.convex_hull_construction_tolerance_m,
            self.convex_hull_outward_padding_m,
            self.box_collision_margin_m,
            self.cylinder_collision_margin_m,
            self.convex_hull_collision_margin_m,
            self.contact_distance_threshold_m,
            self.toi_comparison_tolerance,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A.3 numeric configuration contains NaN/Inf")
        if self.maximum_ccd_iterations > self.native_continuous_algorithm_iteration_cap:
            raise ValueError("configured CCD iterations exceed the pinned native cap")
        required_provenance = {
            "scalar_abi",
            "hull_tolerance",
            "outward_padding",
            "shape_margins",
            "allowed_penetration",
            "contact_threshold",
            "toi_interval",
            "toi_tolerance",
            "maximum_iterations",
            "subdivision",
            "unknown_shapes",
            "initial_overlap",
            "endpoint_overlap",
            "iteration_exhaustion",
            "ambiguity",
        }
        if set(self.provenance) != required_provenance or any(
            not value for value in self.provenance.values()
        ):
            raise ValueError("A.3 numeric provenance set is incomplete or extra")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("A.3 numeric configuration digest differs")
        return self


def canonical_a3_bullet_numeric_configuration_v1() -> A3BulletNumericConfigurationV1:
    """Return conservative values and source notes for the Phase-2 candidate."""

    payload = {
        "schema_version": "A3BulletNumericConfigurationV1",
        "bullet_version": BULLET_VERSION,
        "scalar_abi": "float64",
        "convex_hull_construction_tolerance_m": 1e-7,
        "convex_hull_outward_padding_m": 0.002,
        "box_collision_margin_m": 0.04,
        "cylinder_collision_margin_m": 0.04,
        "convex_hull_collision_margin_m": 0.04,
        "allowed_penetration_m": 0.0,
        "contact_distance_threshold_m": 0.001,
        "toi_min": 0.0,
        "toi_max": 1.0,
        "toi_comparison_tolerance": 1e-7,
        "maximum_ccd_iterations": 64,
        "native_continuous_algorithm_iteration_cap": 64,
        "maximum_subdivisions_per_executor_segment": 4096,
        "query_timeout_ns": 5_000_000_000,
        "iteration_exhaustion_rejects": True,
        "nonfinite_rejects": True,
        "degenerate_shape_rejects": True,
        "initial_overlap_rejects": True,
        "endpoint_overlap_rejects": True,
        "subdivision_boundary_overlap_rejects": True,
        "unknown_or_concave_shape_rejects": True,
        "compound_expansion_required": True,
        "all_ambiguity_resolves_to_rejection": True,
        "provenance": {
            "scalar_abi": "ADR-0024 section 3; float64 package/build digest required",
            "hull_tolerance": "implementation value 1e-7 m within ADR-0024 <=1e-6 m bound",
            "outward_padding": "ADR-0024 minimum 0.002 m; selected exact lower bound",
            "shape_margins": "Bullet shipped btConvexInternalShape default 0.04 m; never reduced",
            "allowed_penetration": "ADR-0024 fixed 0.0 m",
            "contact_threshold": "ADR-0024 minimum 0.001 m; selected exact lower bound",
            "toi_interval": "ADR-0024 closed interval [0,1]",
            "toi_tolerance": "implementation value 1e-7 within ADR-0024 <=1e-6 bound",
            "maximum_iterations": "Bullet 3.24 btContinuousConvexCollision MAX_ITERATIONS=64",
            "subdivision": "ceil(max child swept displacement / smallest conservative radius)",
            "unknown_shapes": "ADR-0024 unknown/concave/malformed/non-finite fail closed",
            "initial_overlap": "ADR-0024 separate discrete initial-overlap rejection",
            "endpoint_overlap": "ADR-0024 separate endpoint/boundary discrete rejection",
            "iteration_exhaustion": "CastResult reportFailure(-2) maps to whole-plan rejection",
            "ambiguity": "ADR-0024 every ambiguity resolves toward rejection",
        },
    }
    return A3BulletNumericConfigurationV1(
        **payload,
        configuration_sha256=canonical_sha256(payload),
    )


class A3RigidTransformV1(FrozenModel):
    translation_world_m: tuple[float, float, float]
    rotation_world_wxyz: tuple[float, float, float, float]

    @model_validator(mode="after")
    def finite_normalized(self) -> "A3RigidTransformV1":
        values = (*self.translation_world_m, *self.rotation_world_wxyz)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A.3 transform contains NaN/Inf")
        norm = math.sqrt(sum(value * value for value in self.rotation_world_wxyz))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("A.3 transform quaternion is not normalized")
        return self


class A3ConvexChildV1(FrozenModel):
    schema_version: Literal["A3ConvexChildV1"] = "A3ConvexChildV1"
    link_path: str = Field(pattern=r"^/World/(?:Robot|M1B)/.+")
    child_index: int = Field(ge=0)
    shape_kind: Literal["BOX", "CYLINDER", "CONVEX_HULL"]
    local_transform: A3RigidTransformV1
    shape_parameters_sha256: str = Field(pattern=SHA256_PATTERN)
    source_asset_path: str = Field(min_length=1)
    source_asset_sha256: str = Field(pattern=SHA256_PATTERN)
    source_vertex_count: int = Field(ge=0)
    decoded_vertices_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    smallest_conservative_radius_m: float = Field(gt=0.0)
    maximum_angular_motion_radius_m: float = Field(gt=0.0)
    collision_margin_m: float = Field(ge=0.04)
    outward_padding_m: float = Field(ge=0.002)
    conservative_outer_envelope: Literal[True] = True
    geometry_equality_claimed: Literal[False] = False
    child_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def shape_is_supported_and_canonical(self) -> "A3ConvexChildV1":
        if not all(
            math.isfinite(value)
            for value in (
                self.smallest_conservative_radius_m,
                self.maximum_angular_motion_radius_m,
            )
        ):
            raise ValueError("A.3 child radius contains NaN/Inf")
        if self.maximum_angular_motion_radius_m < self.smallest_conservative_radius_m:
            raise ValueError("A.3 maximum angular-motion radius is smaller than its inner radius")
        is_hull = self.shape_kind == "CONVEX_HULL"
        if is_hull != (self.decoded_vertices_sha256 is not None and self.source_vertex_count >= 4):
            raise ValueError("A.3 convex-hull vertex binding is incomplete or on a primitive")
        if self.child_sha256 != _canonical_model_sha256(self, "child_sha256"):
            raise ValueError("A.3 child digest differs")
        return self


def decode_binary_stl_vertices_v1(
    path: Path, *, expected_sha256: str
) -> tuple[tuple[tuple[float, float, float], ...], str]:
    """Strictly decode every binary-STL triangle vertex through one FD."""

    raw = _read_regular_file_once(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise A3SelfCollisionRejected("binary STL SHA-256 differs")
    if len(raw) < 84:
        raise A3SelfCollisionRejected("binary STL is truncated")
    triangle_count = struct.unpack_from("<I", raw, 80)[0]
    if triangle_count == 0 or len(raw) != 84 + 50 * triangle_count:
        raise A3SelfCollisionRejected("binary STL byte length/count differs")
    vertices: set[tuple[float, float, float]] = set()
    for index in range(triangle_count):
        offset = 84 + index * 50
        values = struct.unpack_from("<12fH", raw, offset)
        triangle = values[3:12]
        if not all(math.isfinite(value) for value in triangle):
            raise A3SelfCollisionRejected("binary STL contains NaN/Inf vertex")
        for vertex in range(3):
            vertices.add(tuple(float(value) for value in triangle[vertex * 3 : vertex * 3 + 3]))
    ordered = tuple(sorted(vertices))
    if len(ordered) < 4:
        raise A3SelfCollisionRejected("binary STL has fewer than four unique vertices")
    digest = canonical_sha256(ordered)
    return ordered, digest


class A3LinkChildTransformSequenceV1(FrozenModel):
    link_path: str = Field(pattern=r"^/World/(?:Robot|M1B)/.+")
    child_index: int = Field(ge=0)
    transforms: tuple[A3RigidTransformV1, ...] = Field(min_length=2)


class A3SelfCollisionWorldV1(FrozenModel):
    schema_version: Literal["A3SelfCollisionWorldV1"] = "A3SelfCollisionWorldV1"
    children: tuple[A3ConvexChildV1, ...] = Field(min_length=2)
    transforms: tuple[A3LinkChildTransformSequenceV1, ...] = Field(min_length=2)
    acm_link_pairs: tuple[tuple[str, str], ...]
    attached_object_paths: tuple[str, ...]
    executor_state_count: int = Field(ge=2)
    world_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "A3SelfCollisionWorldV1":
        keys = tuple((item.link_path, item.child_index) for item in self.children)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("A.3 children are not unique canonical order")
        transform_keys = tuple((item.link_path, item.child_index) for item in self.transforms)
        if transform_keys != keys or any(
            len(item.transforms) != self.executor_state_count for item in self.transforms
        ):
            raise ValueError("A.3 transform sequences do not cover every child/state")
        canonical_acm = tuple(sorted(tuple(sorted(pair)) for pair in self.acm_link_pairs))
        if self.acm_link_pairs != canonical_acm or len(canonical_acm) != len(set(canonical_acm)):
            raise ValueError("A.3 ACM pairs are not unique canonical order")
        if tuple(sorted(self.attached_object_paths)) != self.attached_object_paths:
            raise ValueError("A.3 attached-object paths are not canonical")
        if self.world_sha256 != _canonical_model_sha256(self, "world_sha256"):
            raise ValueError("A.3 world digest differs")
        return self


class A3ChildPairSegmentV1(FrozenModel):
    pair_index: int = Field(ge=0)
    link_a: str
    child_a: int = Field(ge=0)
    link_b: str
    child_b: int = Field(ge=0)
    executor_segment_index: int = Field(ge=0)
    subdivision_index: int = Field(ge=0)
    subdivision_count: int = Field(ge=1)
    from_a: A3RigidTransformV1
    to_a: A3RigidTransformV1
    from_b: A3RigidTransformV1
    to_b: A3RigidTransformV1
    discrete_check_at_start_required: Literal[True] = True
    discrete_check_at_end_required: Literal[True] = True


class A3ChildPairCCDRequestV1(FrozenModel):
    schema_version: Literal["A3ChildPairCCDRequestV1"] = "A3ChildPairCCDRequestV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    world_sha256: str = Field(pattern=SHA256_PATTERN)
    numeric_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    segments: tuple[A3ChildPairSegmentV1, ...] = Field(min_length=1)
    expected_non_acm_child_pair_count: int = Field(gt=0)
    expected_executor_segment_count: int = Field(gt=0)
    complete_child_pair_product: Literal[True] = True
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    request_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "A3ChildPairCCDRequestV1":
        if tuple(item.pair_index for item in self.segments) != tuple(range(len(self.segments))):
            raise ValueError("A.3 CCD segment indices are not contiguous")
        if self.request_sha256 != _canonical_model_sha256(self, "request_sha256"):
            raise ValueError("A.3 CCD request digest differs")
        return self


def _translation_distance(a: A3RigidTransformV1, b: A3RigidTransformV1) -> float:
    return math.sqrt(
        sum(
            (left - right) ** 2 for left, right in zip(a.translation_world_m, b.translation_world_m)
        )
    )


def _quaternion_angle(a: A3RigidTransformV1, b: A3RigidTransformV1) -> float:
    dot = abs(
        sum(left * right for left, right in zip(a.rotation_world_wxyz, b.rotation_world_wxyz))
    )
    return 2.0 * math.acos(max(-1.0, min(1.0, dot)))


def _interpolate_transform(
    start: A3RigidTransformV1, end: A3RigidTransformV1, fraction: float
) -> A3RigidTransformV1:
    translation = tuple(
        left + (right - left) * fraction
        for left, right in zip(start.translation_world_m, end.translation_world_m)
    )
    q0 = start.rotation_world_wxyz
    q1 = end.rotation_world_wxyz
    dot = sum(left * right for left, right in zip(q0, q1))
    if dot < 0.0:
        q1 = tuple(-value for value in q1)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 1.0 - 1e-12:
        raw = tuple(left + (right - left) * fraction for left, right in zip(q0, q1))
    else:
        angle = math.acos(dot)
        denominator = math.sin(angle)
        if denominator <= 0.0 or not math.isfinite(denominator):
            raise A3SelfCollisionRejected("A.3 quaternion interpolation is degenerate")
        left_weight = math.sin((1.0 - fraction) * angle) / denominator
        right_weight = math.sin(fraction * angle) / denominator
        raw = tuple(left_weight * left + right_weight * right for left, right in zip(q0, q1))
    norm = math.sqrt(sum(value * value for value in raw))
    if norm <= 0.0 or not math.isfinite(norm):
        raise A3SelfCollisionRejected("A.3 quaternion interpolation is degenerate")
    return A3RigidTransformV1(
        translation_world_m=translation,
        rotation_world_wxyz=tuple(value / norm for value in raw),
    )


def build_child_pair_ccd_request_v1(
    *,
    bound_plan_sha256: str,
    world: A3SelfCollisionWorldV1,
    configuration: A3BulletNumericConfigurationV1,
) -> A3ChildPairCCDRequestV1:
    """Expand every non-ACM child pair and conservatively subdivide each path."""

    transforms = {(item.link_path, item.child_index): item.transforms for item in world.transforms}
    acm = set(world.acm_link_pairs)
    child_pairs: list[tuple[A3ConvexChildV1, A3ConvexChildV1]] = []
    for index, left in enumerate(world.children):
        for right in world.children[index + 1 :]:
            if left.link_path == right.link_path:
                continue
            link_pair = tuple(sorted((left.link_path, right.link_path)))
            if link_pair in acm:
                continue
            child_pairs.append((left, right))
    if not child_pairs:
        raise A3SelfCollisionRejected("A.3 world contains no non-ACM child pair")
    segments: list[A3ChildPairSegmentV1] = []
    for executor_index in range(world.executor_state_count - 1):
        for left, right in child_pairs:
            left_start, left_end = transforms[(left.link_path, left.child_index)][
                executor_index : executor_index + 2
            ]
            right_start, right_end = transforms[(right.link_path, right.child_index)][
                executor_index : executor_index + 2
            ]
            smallest_radius = min(
                left.smallest_conservative_radius_m,
                right.smallest_conservative_radius_m,
            )
            swept = max(
                _translation_distance(left_start, left_end)
                + _quaternion_angle(left_start, left_end) * left.maximum_angular_motion_radius_m,
                _translation_distance(right_start, right_end)
                + _quaternion_angle(right_start, right_end) * right.maximum_angular_motion_radius_m,
            )
            subdivisions = max(1, math.ceil(swept / smallest_radius))
            if subdivisions > configuration.maximum_subdivisions_per_executor_segment:
                raise A3SelfCollisionRejected("A.3 subdivision cap reached")
            for subdivision in range(subdivisions):
                start_fraction = subdivision / subdivisions
                end_fraction = (subdivision + 1) / subdivisions
                segments.append(
                    A3ChildPairSegmentV1(
                        pair_index=len(segments),
                        link_a=left.link_path,
                        child_a=left.child_index,
                        link_b=right.link_path,
                        child_b=right.child_index,
                        executor_segment_index=executor_index,
                        subdivision_index=subdivision,
                        subdivision_count=subdivisions,
                        from_a=_interpolate_transform(left_start, left_end, start_fraction),
                        to_a=_interpolate_transform(left_start, left_end, end_fraction),
                        from_b=_interpolate_transform(right_start, right_end, start_fraction),
                        to_b=_interpolate_transform(right_start, right_end, end_fraction),
                    )
                )
    payload = {
        "schema_version": "A3ChildPairCCDRequestV1",
        "bound_plan_sha256": bound_plan_sha256,
        "world_sha256": world.world_sha256,
        "numeric_configuration_sha256": configuration.configuration_sha256,
        "segments": [item.model_dump(mode="json") for item in segments],
        "expected_non_acm_child_pair_count": len(child_pairs),
        "expected_executor_segment_count": world.executor_state_count - 1,
        "complete_child_pair_product": True,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
    }
    return A3ChildPairCCDRequestV1(**payload, request_sha256=canonical_sha256(payload))


class A3ChildPairCCDResultV1(FrozenModel):
    pair_index: int = Field(ge=0)
    status: Literal["CLEAR", "REJECT_COLLISION", "REJECT_QUERY_FAILURE"]
    discrete_start_clear: bool
    discrete_end_clear: bool
    continuous_query_completed: bool
    time_of_impact: float | None = None
    failure_code: int | None = None
    iteration_count: int = Field(ge=0)

    @model_validator(mode="after")
    def fail_closed(self) -> "A3ChildPairCCDResultV1":
        if self.time_of_impact is not None and (
            not math.isfinite(self.time_of_impact) or not 0.0 <= self.time_of_impact <= 1.0
        ):
            raise ValueError("A.3 CCD result has invalid TOI")
        if self.status == "CLEAR" and (
            not self.discrete_start_clear
            or not self.discrete_end_clear
            or not self.continuous_query_completed
            or self.time_of_impact is not None
            or self.failure_code is not None
        ):
            raise ValueError("A.3 CLEAR result is incomplete or contradictory")
        if self.status != "CLEAR" and self.failure_code is None and self.time_of_impact is None:
            raise ValueError("A.3 rejection lacks collision/failure evidence")
        return self


class A3ChildPairCCDReceiptV1(FrozenModel):
    schema_version: Literal["A3ChildPairCCDReceiptV1"] = "A3ChildPairCCDReceiptV1"
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    backend_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    bullet_collision_library_sha256: str = Field(pattern=SHA256_PATTERN)
    bullet_linear_math_library_sha256: str = Field(pattern=SHA256_PATTERN)
    scalar_abi: Literal["float64"] = "float64"
    results: tuple[A3ChildPairCCDResultV1, ...] = Field(min_length=1)
    status: Literal["PASS", "REJECT"]
    real_native_backend: bool
    contract_test_only: bool
    formal_evidence: Literal[False] = False
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "A3ChildPairCCDReceiptV1":
        if self.real_native_backend == self.contract_test_only:
            raise ValueError("A.3 receipt must be exactly native or contract-test")
        expected = "PASS" if all(item.status == "CLEAR" for item in self.results) else "REJECT"
        if self.status != expected:
            raise ValueError("A.3 aggregate status differs from child results")
        if tuple(item.pair_index for item in self.results) != tuple(range(len(self.results))):
            raise ValueError("A.3 result indices are not contiguous")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 CCD receipt digest differs")
        return self


class A3ChildPairCCDBackendV1(Protocol):
    implementation_sha256: str
    real_native_backend: bool

    def query(
        self,
        request: A3ChildPairCCDRequestV1,
        *,
        children: Sequence[A3ConvexChildV1],
        configuration: A3BulletNumericConfigurationV1,
    ) -> A3ChildPairCCDReceiptV1: ...


def verify_child_pair_ccd_receipt_v1(
    request: A3ChildPairCCDRequestV1,
    receipt: A3ChildPairCCDReceiptV1,
    *,
    configuration: A3BulletNumericConfigurationV1,
    require_real_native_backend: bool,
) -> A3ChildPairCCDReceiptV1:
    if (
        receipt.request_sha256 != request.request_sha256
        or len(receipt.results) != len(request.segments)
        or receipt.scalar_abi != configuration.scalar_abi
    ):
        raise A3SelfCollisionRejected("A.3 CCD receipt crossed request/configuration")
    if require_real_native_backend and (
        not receipt.real_native_backend
        or receipt.contract_test_only
        or receipt.bullet_collision_library_sha256 != EXPECTED_BULLET_FLOAT64_COLLISION_SHA256
        or receipt.bullet_linear_math_library_sha256 != EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256
    ):
        raise A3SelfCollisionRejected("A.3 native float64 Bullet closure is absent or mismatched")
    for result in receipt.results:
        if result.iteration_count > configuration.maximum_ccd_iterations:
            raise A3SelfCollisionRejected("A.3 CCD iteration cap exceeded")
        if result.failure_code is not None or result.status != "CLEAR":
            raise A3SelfCollisionRejected("A.3 child pair collided or query failed")
    return receipt
