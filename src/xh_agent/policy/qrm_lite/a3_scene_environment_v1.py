"""Complete query-only A.3 scene-environment geometry and state contract.

The frozen M2C V4 scene contains collision geometry outside the controlled
Panda.  A complete swept-path preflight therefore cannot stop at robot self
collision.  This module byte-binds one generated SDF and its supervision,
rejects every unknown collision-bearing model or unsupported shape, expands
all supported collisions into the same conservative Bullet child payloads as
the robot adapter, and binds one getter-only active-session pose for every
collision-bearing link.

No simulator is imported and no command is executed here.  Runtime poses are
accepted only from a separately byte-bound provider protected by the same
active-session mutation counter used by the rest of A.3 preflight.  Contract
fixtures remain permanently ineligible for formal evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3FileBindingV1,
    A3ShapePayloadV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3BulletNumericConfigurationV1,
    A3ConvexChildV1,
    A3RigidTransformV1,
    bullet_shipped_margin_for_shape_v1,
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
    ActiveSessionMutationCountersV1,
)


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_scene_environment_v1.py"
STATIC_COLLISION_MODEL_NAMES = ("blue_partition_bin", "industrial_work_table")
SCENE_ROOT_PATH = "/World/M1B"
SDF_WORLD_NAME = "industrial_cylinder_v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3SceneEnvironmentUnavailable(RuntimeError):
    """The complete scene/environment query cannot be proven."""


def _model_sha256(model: BaseModel, field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={field}))


def _read_single_link_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise A3SceneEnvironmentUnavailable(
                f"A.3 scene input is not a single-link regular file: {path}"
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
        raw = b"".join(chunks)
        if identity(before) != identity(after) or len(raw) != before.st_size:
            raise A3SceneEnvironmentUnavailable(f"A.3 scene input changed: {path}")
        return raw
    finally:
        os.close(descriptor)


def _bound_bytes(path: Path, expected_sha256: str) -> bytes:
    raw = _read_single_link_regular_file(path)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise A3SceneEnvironmentUnavailable(f"A.3 scene byte binding differs: {path}")
    return raw


def _finite_tuple(raw: str | None, width: int, *, default: tuple[float, ...]) -> tuple[float, ...]:
    if raw is None:
        return default
    try:
        values = tuple(float(value) for value in raw.split())
    except ValueError as exc:
        raise A3SceneEnvironmentUnavailable("A.3 SDF numeric field is malformed") from exc
    if len(values) != width or not all(math.isfinite(value) for value in values):
        raise A3SceneEnvironmentUnavailable("A.3 SDF numeric field width/value differs")
    return values


def _pose(element: ET.Element) -> A3RigidTransformV1:
    values = _finite_tuple(
        element.findtext("pose"),
        6,
        default=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    return A3RigidTransformV1(
        translation_world_m=values[:3],
        rotation_world_wxyz=_rpy_to_wxyz(values[3:]),
    )


def _canonical_quaternion(
    value: Sequence[float],
) -> tuple[float, float, float, float]:
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise A3SceneEnvironmentUnavailable("A.3 scene quaternion is non-numeric") from exc
    if len(result) != 4 or not all(math.isfinite(item) for item in result):
        raise A3SceneEnvironmentUnavailable("A.3 scene quaternion is malformed")
    norm = math.sqrt(sum(item * item for item in result))
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise A3SceneEnvironmentUnavailable("A.3 scene quaternion is not normalized")
    normalized = tuple(item / norm for item in result)
    for item in normalized:
        if abs(item) > 1e-15:
            return tuple(-part for part in normalized) if item < 0.0 else normalized
    raise A3SceneEnvironmentUnavailable("A.3 scene quaternion is degenerate")


def _rpy_to_wxyz(rpy: Sequence[float]) -> tuple[float, float, float, float]:
    roll, pitch, yaw = (float(value) for value in rpy)
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return _canonical_quaternion(
        (
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        )
    )


def _compose_transform(
    left: A3RigidTransformV1,
    right: A3RigidTransformV1,
) -> A3RigidTransformV1:
    lw, lx, ly, lz = left.rotation_world_wxyz
    rw, rx, ry, rz = right.rotation_world_wxyz
    rotation = _canonical_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
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
            origin + offset
            for origin, offset in zip(left.translation_world_m, translated, strict=True)
        ),
        rotation_world_wxyz=rotation,
    )


class A3SceneSourceLinkV1(_FrozenModel):
    link_path: str = Field(pattern=r"^/World/M1B/[^/]+/[^/]+$")
    model_name: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    link_name: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    dynamic: bool
    source_initial_world_transform: A3RigidTransformV1
    collision_child_count: Literal[1] = 1


class A3SceneCollisionGeometryReceiptV1(_FrozenModel):
    schema_version: Literal["A3SceneCollisionGeometryReceiptV1"] = (
        "A3SceneCollisionGeometryReceiptV1"
    )
    source_sdf: A3FileBindingV1
    source_supervision: A3FileBindingV1
    scene_seed: int = Field(ge=0)
    source_links: tuple[A3SceneSourceLinkV1, ...] = Field(min_length=8)
    static_collision_link_paths: tuple[str, ...] = Field(min_length=2)
    dynamic_collision_link_paths: tuple[str, ...] = Field(min_length=6)
    children: tuple[A3ConvexChildV1, ...] = Field(min_length=8)
    shape_payloads: tuple[A3ShapePayloadV1, ...] = Field(min_length=8)
    exact_collision_model_count: int = Field(ge=8)
    exact_collision_primitive_count: int = Field(ge=8)
    all_sdf_collisions_covered: Literal[True] = True
    unknown_collision_model_rejects: Literal[True] = True
    unsupported_collision_shape_rejects: Literal[True] = True
    complete_compound_expansion: Literal[True] = True
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    formal_evidence: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "A3SceneCollisionGeometryReceiptV1":
        links = tuple(item.link_path for item in self.source_links)
        child_keys = tuple((item.link_path, item.child_index) for item in self.children)
        payload_keys = tuple((item.link_path, item.child_index) for item in self.shape_payloads)
        expected_keys = tuple((path, 0) for path in links)
        if (
            links != tuple(sorted(links))
            or len(links) != len(set(links))
            or child_keys != expected_keys
            or payload_keys != expected_keys
            or tuple(item.shape_parameters_sha256 for item in self.children)
            != tuple(item.payload_sha256 for item in self.shape_payloads)
            or tuple(item.collision_margin_m for item in self.children)
            != tuple(item.collision_margin_m for item in self.shape_payloads)
        ):
            raise ValueError("A.3 scene child/payload/link coverage differs")
        static = tuple(item.link_path for item in self.source_links if not item.dynamic)
        dynamic = tuple(item.link_path for item in self.source_links if item.dynamic)
        if (
            self.static_collision_link_paths != static
            or self.dynamic_collision_link_paths != dynamic
            or self.exact_collision_model_count != len(links)
            or self.exact_collision_primitive_count != len(self.children)
        ):
            raise ValueError("A.3 scene static/dynamic collision coverage differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 scene geometry receipt digest differs")
        return self


def _supervised_cylinder_names(raw: bytes, *, expected_scene_seed: int) -> tuple[str, ...]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise A3SceneEnvironmentUnavailable("A.3 scene supervision is malformed") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("scene_id") != "IndustrialCylinderBenchmarkV1"
        or payload.get("seed") != expected_scene_seed
    ):
        raise A3SceneEnvironmentUnavailable("A.3 scene supervision identity differs")
    supervision = payload.get("simulator_supervision")
    if (
        not isinstance(supervision, dict)
        or supervision.get("training_and_evaluation_only") is not True
        or not isinstance(supervision.get("objects"), list)
    ):
        raise A3SceneEnvironmentUnavailable("A.3 simulator supervision contract differs")
    objects = supervision["objects"]
    names = tuple(str(item.get("actual_sim_entity_id", "")) for item in objects)
    if (
        not 6 <= len(names) <= 12
        or names != tuple(f"cylinder_{index:02d}" for index in range(1, len(names) + 1))
        or any(item.get("category") != "industrial_cylinder" for item in objects)
    ):
        raise A3SceneEnvironmentUnavailable("A.3 supervised cylinder set differs")
    return names


def _shape_from_collision(
    *,
    collision: ET.Element,
    link_path: str,
    child_index: int,
    sdf_path: Path,
    sdf_sha256: str,
    configuration: A3BulletNumericConfigurationV1,
) -> tuple[A3ConvexChildV1, A3ShapePayloadV1]:
    geometry = collision.find("geometry")
    if geometry is None or len(geometry) != 1:
        raise A3SceneEnvironmentUnavailable("A.3 SDF collision geometry is missing/compound")
    shape = geometry[0]
    if shape.tag == "box":
        kind: Literal["BOX", "CYLINDER"] = "BOX"
        parameters = _finite_tuple(shape.findtext("size"), 3, default=())
        smallest = min(parameters) * 0.5
        maximum = math.sqrt(sum((value * 0.5) ** 2 for value in parameters))
    elif shape.tag == "cylinder":
        kind = "CYLINDER"
        parameters = (
            *_finite_tuple(shape.findtext("radius"), 1, default=()),
            *_finite_tuple(shape.findtext("length"), 1, default=()),
        )
        radius, length = parameters
        smallest = min(radius, length * 0.5)
        maximum = math.hypot(radius, length * 0.5)
    else:
        raise A3SceneEnvironmentUnavailable(f"A.3 unsupported SDF collision shape: {shape.tag}")
    if any(value <= 0.0 for value in parameters):
        raise A3SceneEnvironmentUnavailable("A.3 SDF collision dimension is non-positive")
    margin = bullet_shipped_margin_for_shape_v1(kind, parameters)
    payload_data = {
        "schema_version": "A3ShapePayloadV1",
        "link_path": link_path,
        "child_index": child_index,
        "shape_kind": kind,
        "shape_parameters": parameters,
        "decoded_vertices_xyz_m": (),
        "hull_construction_tolerance_m": (configuration.convex_hull_construction_tolerance_m),
        "outward_padding_m": configuration.convex_hull_outward_padding_m,
        "collision_margin_m": margin,
        "every_decoded_stl_vertex_retained": False,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    payload = A3ShapePayloadV1(
        **payload_data,
        payload_sha256=canonical_sha256(payload_data),
    )
    child_data = {
        "schema_version": "A3ConvexChildV1",
        "link_path": link_path,
        "child_index": child_index,
        "shape_kind": kind,
        "local_transform": _pose(collision).model_dump(mode="json"),
        "shape_parameters_sha256": payload.payload_sha256,
        "source_asset_path": str(sdf_path),
        "source_asset_sha256": sdf_sha256,
        "source_vertex_count": 0,
        "decoded_vertices_sha256": None,
        "smallest_conservative_radius_m": smallest,
        "maximum_angular_motion_radius_m": (
            maximum + payload.outward_padding_m + payload.collision_margin_m
        ),
        "collision_margin_m": payload.collision_margin_m,
        "outward_padding_m": payload.outward_padding_m,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    child = A3ConvexChildV1(
        **child_data,
        child_sha256=canonical_sha256(child_data),
    )
    return child, payload


def build_a3_scene_collision_geometry_v1(
    *,
    sdf_path: Path,
    supervision_path: Path,
    expected_sdf_sha256: str,
    expected_supervision_sha256: str,
    expected_scene_seed: int,
    configuration: A3BulletNumericConfigurationV1 | None = None,
) -> A3SceneCollisionGeometryReceiptV1:
    """Replay the entire generated SDF collision tree through immutable bytes."""

    config = configuration or canonical_a3_bullet_numeric_configuration_v1()
    # Keep the lexical path so O_NOFOLLOW below can reject a symlink instead
    # of resolving it before the single-descriptor read.
    sdf = sdf_path.absolute()
    supervision = supervision_path.absolute()
    sdf_raw = _bound_bytes(sdf, expected_sdf_sha256)
    supervision_raw = _bound_bytes(supervision, expected_supervision_sha256)
    cylinder_names = _supervised_cylinder_names(
        supervision_raw,
        expected_scene_seed=expected_scene_seed,
    )
    try:
        root = ET.fromstring(sdf_raw)
    except ET.ParseError as exc:
        raise A3SceneEnvironmentUnavailable("A.3 generated SDF is malformed") from exc
    worlds = root.findall("world")
    if (
        root.tag != "sdf"
        or root.attrib.get("version") != "1.9"
        or len(worlds) != 1
        or worlds[0].attrib.get("name") != SDF_WORLD_NAME
    ):
        raise A3SceneEnvironmentUnavailable("A.3 generated SDF world identity differs")
    world = worlds[0]
    collision_models = tuple(
        model for model in world.findall("model") if model.findall("./link/collision")
    )
    observed_names = tuple(model.attrib.get("name", "") for model in collision_models)
    expected_names = ("industrial_work_table", *cylinder_names, "blue_partition_bin")
    if observed_names != expected_names or len(observed_names) != len(set(observed_names)):
        raise A3SceneEnvironmentUnavailable("A.3 collision-bearing SDF model set/order differs")
    # Contact sensors also contain a scalar <collision> reference.  Only
    # elements that own <geometry> are collision primitives.
    all_collision_elements = [
        item for item in world.findall(".//collision") if item.find("geometry") is not None
    ]
    expected_collision_elements = [
        collision for model in collision_models for collision in model.findall("./link/collision")
    ]
    if len(all_collision_elements) != len(expected_collision_elements):
        raise A3SceneEnvironmentUnavailable(
            "A.3 nested or unowned SDF collision geometry is present"
        )
    sources: list[A3SceneSourceLinkV1] = []
    children: list[A3ConvexChildV1] = []
    payloads: list[A3ShapePayloadV1] = []
    supervised_objects = json.loads(supervision_raw)["simulator_supervision"]["objects"]
    supervision_by_name = {item["actual_sim_entity_id"]: item for item in supervised_objects}
    for model in collision_models:
        model_name = model.attrib["name"]
        expected_static = model_name in STATIC_COLLISION_MODEL_NAMES
        observed_static = model.findtext("static", default="false").strip().lower() in {
            "1",
            "true",
        }
        if observed_static != expected_static:
            raise A3SceneEnvironmentUnavailable("A.3 SDF model static/dynamic role differs")
        links = tuple(link for link in model.findall("link") if link.findall("collision"))
        if len(links) != 1 or len(links[0].findall("collision")) != 1:
            raise A3SceneEnvironmentUnavailable(
                "A.3 collision-bearing model must have exactly one collision link/child"
            )
        link = links[0]
        link_name = link.attrib.get("name", "")
        if not link_name:
            raise A3SceneEnvironmentUnavailable("A.3 collision-bearing SDF link has no name")
        link_path = f"{SCENE_ROOT_PATH}/{model_name}/{link_name}"
        model_transform = _pose(model)
        source_transform = _compose_transform(model_transform, _pose(link))
        if not expected_static:
            supervised = supervision_by_name.get(model_name)
            try:
                supervised_position = tuple(
                    round(float(value), 9) for value in supervised["position_3d_world"]
                )
                supervised_yaw = round(float(supervised["yaw"]), 9)
            except (KeyError, TypeError, ValueError) as exc:
                raise A3SceneEnvironmentUnavailable(
                    "A.3 dynamic-object supervision pose is malformed"
                ) from exc
            source_position = tuple(
                round(value, 9) for value in model_transform.translation_world_m
            )
            source_rpy = _finite_tuple(
                model.findtext("pose"),
                6,
                default=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            )[3:]
            if (
                supervised_position != source_position
                or supervised_yaw != round(source_rpy[2], 9)
                or source_rpy[:2] != (0.0, 0.0)
            ):
                raise A3SceneEnvironmentUnavailable(
                    "A.3 SDF/supervision dynamic-object pose differs"
                )
        child, payload = _shape_from_collision(
            collision=links[0].findall("collision")[0],
            link_path=link_path,
            child_index=0,
            sdf_path=sdf,
            sdf_sha256=expected_sdf_sha256,
            configuration=config,
        )
        sources.append(
            A3SceneSourceLinkV1(
                link_path=link_path,
                model_name=model_name,
                link_name=link_name,
                dynamic=not expected_static,
                source_initial_world_transform=source_transform,
            )
        )
        children.append(child)
        payloads.append(payload)
    ordered = sorted(
        zip(sources, children, payloads, strict=True),
        key=lambda item: item[0].link_path,
    )
    ordered_sources = tuple(item[0] for item in ordered)
    data: dict[str, Any] = {
        "schema_version": "A3SceneCollisionGeometryReceiptV1",
        "source_sdf": {"path": str(sdf), "sha256": expected_sdf_sha256},
        "source_supervision": {
            "path": str(supervision),
            "sha256": expected_supervision_sha256,
        },
        "scene_seed": expected_scene_seed,
        "source_links": [item.model_dump(mode="json") for item in ordered_sources],
        "static_collision_link_paths": [
            item.link_path for item in ordered_sources if not item.dynamic
        ],
        "dynamic_collision_link_paths": [
            item.link_path for item in ordered_sources if item.dynamic
        ],
        "children": [item[1].model_dump(mode="json") for item in ordered],
        "shape_payloads": [item[2].model_dump(mode="json") for item in ordered],
        "exact_collision_model_count": len(ordered),
        "exact_collision_primitive_count": len(ordered),
        "all_sdf_collisions_covered": True,
        "unknown_collision_model_rejects": True,
        "unsupported_collision_shape_rejects": True,
        "complete_compound_expansion": True,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_evidence": False,
    }
    return A3SceneCollisionGeometryReceiptV1(
        **data,
        receipt_sha256=canonical_sha256(data),
    )


class A3SceneLinkStateV1(_FrozenModel):
    link_path: str = Field(pattern=r"^/World/M1B/[^/]+/[^/]+$")
    world_transform: A3RigidTransformV1


class A3SceneStateReceiptV1(_FrozenModel):
    schema_version: Literal["A3SceneStateReceiptV1"] = "A3SceneStateReceiptV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_snapshot_sha256: str = Field(pattern=SHA256_PATTERN)
    geometry_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    source_sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    source_supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_seed: int = Field(ge=0)
    link_states: tuple[A3SceneLinkStateV1, ...] = Field(min_length=8)
    observed_at_ns: int = Field(gt=0)
    provider_implementation: A3FileBindingV1
    provider_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    real_runtime_provider: bool
    contract_test_only: bool
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    controller_commands: Literal[0] = 0
    attachment_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    formal_evidence: Literal[False] = False
    state_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "A3SceneStateReceiptV1":
        paths = tuple(item.link_path for item in self.link_states)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("A.3 scene state paths are not unique canonical order")
        if self.real_runtime_provider == self.contract_test_only:
            raise ValueError("A.3 scene state must be exactly real-runtime or contract-test")
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("A.3 scene state query mutated the active session")
        expected_state = canonical_sha256(
            [item.model_dump(mode="json") for item in self.link_states]
        )
        if self.state_sha256 != expected_state:
            raise ValueError("A.3 scene state digest differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 scene state receipt digest differs")
        return self


class A3ScenePoseProviderV1(Protocol):
    implementation_path: str
    implementation_sha256: str
    configuration_sha256: str
    real_runtime_provider: bool
    contract_test_only: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1

    def query_scene_link_world_poses(
        self,
        *,
        link_paths: tuple[str, ...],
        after_ns: int,
    ) -> tuple[Mapping[str, A3RigidTransformV1], int]: ...


def produce_a3_scene_state_receipt_v1(
    *,
    bound_plan_sha256: str,
    runtime_snapshot_sha256: str,
    geometry: A3SceneCollisionGeometryReceiptV1,
    provider: A3ScenePoseProviderV1,
    after_ns: int,
    require_real_runtime_provider: bool,
) -> A3SceneStateReceiptV1:
    if provider.real_runtime_provider == provider.contract_test_only or (
        require_real_runtime_provider and not provider.real_runtime_provider
    ):
        raise A3SceneEnvironmentUnavailable("A.3 scene pose provider scope differs")
    implementation_path = Path(provider.implementation_path)
    if (
        hashlib.sha256(_read_single_link_regular_file(implementation_path)).hexdigest()
        != provider.implementation_sha256
    ):
        raise A3SceneEnvironmentUnavailable("A.3 scene pose provider bytes differ")
    paths = tuple(item.link_path for item in geometry.source_links)
    before = provider.mutation_counter_source.snapshot_mutation_counters()
    try:
        raw_states, observed_at_ns = provider.query_scene_link_world_poses(
            link_paths=paths,
            after_ns=after_ns,
        )
    except Exception as exc:
        raise A3SceneEnvironmentUnavailable("A.3 scene pose query failed") from exc
    after = provider.mutation_counter_source.snapshot_mutation_counters()
    if before != after or observed_at_ns <= after_ns or set(raw_states) != set(paths):
        raise A3SceneEnvironmentUnavailable(
            "A.3 scene pose query crossed time, coverage, or mutation boundary"
        )
    states = tuple(
        A3SceneLinkStateV1(
            link_path=path,
            world_transform=A3RigidTransformV1.model_validate(
                raw_states[path].model_dump(mode="json")
                if isinstance(raw_states[path], BaseModel)
                else raw_states[path]
            ),
        )
        for path in paths
    )
    state_sha256 = canonical_sha256([item.model_dump(mode="json") for item in states])
    data: dict[str, Any] = {
        "schema_version": "A3SceneStateReceiptV1",
        "bound_plan_sha256": bound_plan_sha256,
        "runtime_snapshot_sha256": runtime_snapshot_sha256,
        "geometry_receipt_sha256": geometry.receipt_sha256,
        "source_sdf_sha256": geometry.source_sdf.sha256,
        "source_supervision_sha256": geometry.source_supervision.sha256,
        "scene_seed": geometry.scene_seed,
        "link_states": [item.model_dump(mode="json") for item in states],
        "observed_at_ns": observed_at_ns,
        "provider_implementation": {
            "path": provider.implementation_path,
            "sha256": provider.implementation_sha256,
        },
        "provider_configuration_sha256": provider.configuration_sha256,
        "real_runtime_provider": provider.real_runtime_provider,
        "contract_test_only": provider.contract_test_only,
        "mutation_counters_before": before,
        "mutation_counters_after": after,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "controller_commands": 0,
        "attachment_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_evidence": False,
        "state_sha256": state_sha256,
    }
    return A3SceneStateReceiptV1(
        **data,
        receipt_sha256=canonical_sha256(data),
    )


def _runtime_type(value: object) -> str:
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"


def _first_row(value: Any, *, width: int, label: str) -> tuple[float, ...]:
    if hasattr(value, "numpy"):
        value = value.numpy()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)) and len(value) == 1 and isinstance(value[0], (list, tuple)):
        value = value[0]
    if not isinstance(value, (list, tuple)):
        raise A3SceneEnvironmentUnavailable(f"{label} is not an array")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise A3SceneEnvironmentUnavailable(f"{label} is non-numeric") from exc
    if len(result) != width or not all(math.isfinite(item) for item in result):
        raise A3SceneEnvironmentUnavailable(f"{label} width/value differs")
    return result


class IsaacSceneRigidPrimReadOnlySourceV1:
    """Getter-only adapter over the active scene owner's exact RigidPrims."""

    def __init__(
        self,
        *,
        implementation_path: Path,
        implementation_sha256: str,
        configuration_sha256: str,
        rigid_prim_runtime_type: str,
        prims_by_path: Mapping[str, Any],
        mutation_counter_source: ActiveSessionMutationCounterSourceV1,
        now_ns: Callable[[], int],
        real_runtime_provider: bool,
        contract_test_only: bool,
    ) -> None:
        if (
            real_runtime_provider == contract_test_only
            or hashlib.sha256(_read_single_link_regular_file(implementation_path)).hexdigest()
            != implementation_sha256
            or not prims_by_path
            or any(
                _runtime_type(prim) != rigid_prim_runtime_type for prim in prims_by_path.values()
            )
        ):
            raise A3SceneEnvironmentUnavailable("A.3 scene RigidPrim deployment identity differs")
        if real_runtime_provider and (
            not mutation_counter_source.real_active_session_source
            or mutation_counter_source.mocked_counter_source
        ):
            raise A3SceneEnvironmentUnavailable(
                "A.3 real scene source lacks real mutation counters"
            )
        if contract_test_only and (
            mutation_counter_source.real_active_session_source
            or not mutation_counter_source.mocked_counter_source
        ):
            raise A3SceneEnvironmentUnavailable(
                "A.3 contract scene source crossed production counters"
            )
        self.implementation_path = str(implementation_path)
        self.implementation_sha256 = implementation_sha256
        self.configuration_sha256 = configuration_sha256
        self.real_runtime_provider = real_runtime_provider
        self.contract_test_only = contract_test_only
        self.prims_by_path = dict(prims_by_path)
        self.mutation_counter_source = mutation_counter_source
        self.now_ns = now_ns

    def query_scene_link_world_poses(
        self,
        *,
        link_paths: tuple[str, ...],
        after_ns: int,
    ) -> tuple[Mapping[str, A3RigidTransformV1], int]:
        if tuple(sorted(self.prims_by_path)) != link_paths:
            raise A3SceneEnvironmentUnavailable("A.3 scene RigidPrim coverage differs")
        before = self.mutation_counter_source.snapshot_mutation_counters()
        result: dict[str, A3RigidTransformV1] = {}
        for path in link_paths:
            getter = getattr(self.prims_by_path[path], "get_world_poses", None)
            if not callable(getter):
                raise A3SceneEnvironmentUnavailable("A.3 scene prim lacks get_world_poses")
            position, orientation = getter()
            result[path] = A3RigidTransformV1(
                translation_world_m=_first_row(
                    position,
                    width=3,
                    label=f"{path} world position",
                ),
                rotation_world_wxyz=_canonical_quaternion(
                    _first_row(
                        orientation,
                        width=4,
                        label=f"{path} world orientation",
                    )
                ),
            )
        observed_at_ns = int(self.now_ns())
        after = self.mutation_counter_source.snapshot_mutation_counters()
        if before != after or observed_at_ns <= after_ns:
            raise A3SceneEnvironmentUnavailable(
                "A.3 scene RigidPrim query crossed time/mutation boundary"
            )
        return result, observed_at_ns
