"""Compose complete robot, attached-object, and scene A.3 collision worlds.

The historical A.3 provider covered continuous robot self collision.  This
module adds the complete generated-scene environment without changing any
numeric threshold or safety allowlist.  Ordinary environment/environment
pairs are excluded because the robot plan cannot affect their relative state;
robot/environment and attached-object/environment pairs remain mandatory.
Only contact pairs already frozen in the exact phase may be excluded.

This is a pure, query-only world composer.  It does not call Bullet, Isaac, a
controller, or an attachment mutator.  The returned world is consumed by the
same float64 child-pair CCD request builder used by the self-collision path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3ShapePayloadV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3LinkChildTransformSequenceV1,
    A3SelfCollisionWorldV1,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3SceneStateReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_complete_scene_collision_v2.py"
ROBOT_ROOT_PATH = "/World/Robot"
SCENE_ROOT_PATH = "/World/M1B"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3CompleteSceneCollisionUnavailable(RuntimeError):
    """The combined complete-scene CCD world cannot be proven."""


def _model_sha256(model: BaseModel, field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={field}))


def _matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def _canonical_pairs(pairs: set[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if any(left == right for left, right in pairs):
        raise A3CompleteSceneCollisionUnavailable("A.3 complete-scene ACM repeats one link")
    return tuple(sorted(tuple(sorted(pair)) for pair in pairs))


def _compose_transform(left: Any, right: Any) -> Any:
    """Compose two already validated A3RigidTransformV1 values."""

    from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3RigidTransformV1

    lw, lx, ly, lz = left.rotation_world_wxyz
    rw, rx, ry, rz = right.rotation_world_wxyz
    rotation = (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )
    norm = sum(value * value for value in rotation) ** 0.5
    if norm <= 0.0:
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 complete-scene transform quaternion is degenerate"
        )
    rotation = tuple(value / norm for value in rotation)
    for value in rotation:
        if abs(value) > 1e-15:
            if value < 0.0:
                rotation = tuple(-item for item in rotation)
            break
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


def _expected_components(
    *,
    base_world: A3SelfCollisionWorldV1,
    base_shape_payloads: tuple[A3ShapePayloadV1, ...],
    scene_geometry: A3SceneCollisionGeometryReceiptV1,
    scene_state: A3SceneStateReceiptV1,
    allowed_robot_contact_paths: tuple[str, ...],
    allowed_external_contact_paths: tuple[str, ...],
) -> dict[str, Any]:
    base_keys = tuple((item.link_path, item.child_index) for item in base_world.children)
    base_payload_keys = tuple((item.link_path, item.child_index) for item in base_shape_payloads)
    if (
        base_keys != base_payload_keys
        or tuple(item.shape_parameters_sha256 for item in base_world.children)
        != tuple(item.payload_sha256 for item in base_shape_payloads)
        or tuple(item.collision_margin_m for item in base_world.children)
        != tuple(item.collision_margin_m for item in base_shape_payloads)
    ):
        raise A3CompleteSceneCollisionUnavailable("A.3 base world child/payload coverage differs")
    robot_paths = tuple(
        sorted(
            {
                item.link_path
                for item in base_world.children
                if item.link_path.startswith(ROBOT_ROOT_PATH + "/")
            }
        )
    )
    attached_paths = base_world.attached_object_paths
    unexpected_base_paths = {
        item.link_path
        for item in base_world.children
        if not item.link_path.startswith(ROBOT_ROOT_PATH + "/")
        and item.link_path not in attached_paths
    }
    if not robot_paths or unexpected_base_paths:
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 base world contains an unknown non-robot/non-attached link"
        )
    scene_children = {(item.link_path, item.child_index): item for item in scene_geometry.children}
    scene_payloads = {
        (item.link_path, item.child_index): item for item in scene_geometry.shape_payloads
    }
    scene_state_by_path = {item.link_path: item.world_transform for item in scene_state.link_states}
    scene_paths = tuple(item.link_path for item in scene_geometry.source_links)
    if (
        tuple(sorted(scene_state_by_path)) != scene_paths
        or scene_state.geometry_receipt_sha256 != scene_geometry.receipt_sha256
        or scene_state.source_sdf_sha256 != scene_geometry.source_sdf.sha256
        or scene_state.source_supervision_sha256 != scene_geometry.source_supervision.sha256
        or scene_state.scene_seed != scene_geometry.scene_seed
    ):
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 scene geometry/state coverage or source binding differs"
        )
    if not set(attached_paths).issubset(scene_paths):
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 attached object is absent from the frozen scene"
        )
    base_child_by_key = {(item.link_path, item.child_index): item for item in base_world.children}
    base_payload_by_key = {(item.link_path, item.child_index): item for item in base_shape_payloads}
    for path in attached_paths:
        scene_keys = tuple(key for key in scene_children if key[0] == path)
        base_attached_keys = tuple(key for key in base_child_by_key if key[0] == path)
        if (
            scene_keys != base_attached_keys
            or any(base_child_by_key[key] != scene_children[key] for key in scene_keys)
            or any(base_payload_by_key[key] != scene_payloads[key] for key in scene_keys)
        ):
            raise A3CompleteSceneCollisionUnavailable(
                "A.3 attached geometry differs from its frozen scene source"
            )
    ordinary_environment_paths = tuple(path for path in scene_paths if path not in attached_paths)
    ordinary_keys = tuple(key for key in scene_children if key[0] in ordinary_environment_paths)
    environment_transforms = {
        key: A3LinkChildTransformSequenceV1(
            link_path=key[0],
            child_index=key[1],
            transforms=tuple(
                _compose_transform(
                    scene_state_by_path[key[0]],
                    scene_children[key].local_transform,
                )
                for _ in range(base_world.executor_state_count)
            ),
        )
        for key in ordinary_keys
    }
    child_by_key = {
        **base_child_by_key,
        **{key: scene_children[key] for key in ordinary_keys},
    }
    payload_by_key = {
        **base_payload_by_key,
        **{key: scene_payloads[key] for key in ordinary_keys},
    }
    transform_by_key = {(item.link_path, item.child_index): item for item in base_world.transforms}
    transform_by_key.update(environment_transforms)
    if (
        len(child_by_key) != len(base_child_by_key) + len(ordinary_keys)
        or set(child_by_key) != set(payload_by_key)
        or set(child_by_key) != set(transform_by_key)
    ):
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 complete-scene child/payload/transform identity collides"
        )

    environment_environment_pairs = {
        tuple(sorted((left, right)))
        for index, left in enumerate(ordinary_environment_paths)
        for right in ordinary_environment_paths[index + 1 :]
    }
    external_paths = tuple(sorted((*ordinary_environment_paths, *attached_paths)))
    matched_robot = tuple(
        path for path in robot_paths if _matches(path, allowed_robot_contact_paths)
    )
    matched_external = tuple(
        path for path in external_paths if _matches(path, allowed_external_contact_paths)
    )
    if bool(allowed_robot_contact_paths) != bool(allowed_external_contact_paths):
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 frozen phase contact allowlists are one-sided"
        )
    if allowed_robot_contact_paths and (
        not matched_robot
        or not matched_external
        or any(
            not any(_matches(path, (prefix,)) for path in robot_paths)
            for prefix in allowed_robot_contact_paths
        )
        or any(
            not any(_matches(path, (prefix,)) for path in external_paths)
            for prefix in allowed_external_contact_paths
        )
    ):
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 frozen phase contact allowlist does not resolve in the collision world"
        )
    allowed_phase_pairs = {
        tuple(sorted((robot, external))) for robot in matched_robot for external in matched_external
    }
    acm = _canonical_pairs(
        set(base_world.acm_link_pairs) | environment_environment_pairs | allowed_phase_pairs
    )
    ordered_keys = tuple(sorted(child_by_key))
    children = tuple(child_by_key[key] for key in ordered_keys)
    payloads = tuple(payload_by_key[key] for key in ordered_keys)
    transforms = tuple(transform_by_key[key] for key in ordered_keys)
    world_data = {
        "schema_version": "A3SelfCollisionWorldV1",
        "children": [item.model_dump(mode="json") for item in children],
        "transforms": [item.model_dump(mode="json") for item in transforms],
        "acm_link_pairs": acm,
        "attached_object_paths": attached_paths,
        "executor_state_count": base_world.executor_state_count,
    }
    world = A3SelfCollisionWorldV1(
        **world_data,
        world_sha256=canonical_sha256(world_data),
    )
    return {
        "robot_link_paths": robot_paths,
        "ordinary_environment_link_paths": ordinary_environment_paths,
        "attached_object_paths": attached_paths,
        "environment_environment_acm_pairs": _canonical_pairs(environment_environment_pairs),
        "phase_allowed_contact_acm_pairs": _canonical_pairs(allowed_phase_pairs),
        "shape_payloads": payloads,
        "collision_world": world,
    }


class A3CompleteSceneCollisionWorldV2(_FrozenModel):
    schema_version: Literal["A3CompleteSceneCollisionWorldV2"] = "A3CompleteSceneCollisionWorldV2"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    base_world: A3SelfCollisionWorldV1
    base_shape_payloads: tuple[A3ShapePayloadV1, ...] = Field(min_length=2)
    scene_geometry: A3SceneCollisionGeometryReceiptV1
    scene_state: A3SceneStateReceiptV1
    allowed_robot_contact_paths: tuple[str, ...]
    allowed_external_contact_paths: tuple[str, ...]
    robot_link_paths: tuple[str, ...] = Field(min_length=1)
    ordinary_environment_link_paths: tuple[str, ...] = Field(min_length=1)
    attached_object_paths: tuple[str, ...]
    environment_environment_acm_pairs: tuple[tuple[str, str], ...]
    phase_allowed_contact_acm_pairs: tuple[tuple[str, str], ...]
    shape_payloads: tuple[A3ShapePayloadV1, ...] = Field(min_length=3)
    collision_world: A3SelfCollisionWorldV1
    complete_robot_self_coverage: Literal[True] = True
    complete_robot_environment_coverage: Literal[True] = True
    complete_attached_object_environment_coverage: Literal[True] = True
    environment_environment_pairs_intentionally_excluded: Literal[True] = True
    only_frozen_phase_contacts_excluded: Literal[True] = True
    real_attached_geometry_resolver: bool
    contract_test_only: bool
    formal_query_evidence_eligible: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def replay_complete_scene_world(self) -> "A3CompleteSceneCollisionWorldV2":
        try:
            expected = _expected_components(
                base_world=self.base_world,
                base_shape_payloads=self.base_shape_payloads,
                scene_geometry=self.scene_geometry,
                scene_state=self.scene_state,
                allowed_robot_contact_paths=self.allowed_robot_contact_paths,
                allowed_external_contact_paths=self.allowed_external_contact_paths,
            )
        except Exception as exc:
            raise ValueError("A.3 complete-scene collision world replay failed") from exc
        observed = {
            "robot_link_paths": self.robot_link_paths,
            "ordinary_environment_link_paths": self.ordinary_environment_link_paths,
            "attached_object_paths": self.attached_object_paths,
            "environment_environment_acm_pairs": self.environment_environment_acm_pairs,
            "phase_allowed_contact_acm_pairs": self.phase_allowed_contact_acm_pairs,
            "shape_payloads": self.shape_payloads,
            "collision_world": self.collision_world,
        }
        if observed != expected:
            raise ValueError("A.3 complete-scene collision world is not reproducible")
        expected_formal = bool(
            not self.contract_test_only
            and self.scene_state.real_runtime_provider
            and not self.scene_state.contract_test_only
            and (not self.attached_object_paths or self.real_attached_geometry_resolver)
        )
        if self.formal_query_evidence_eligible != expected_formal:
            raise ValueError("A.3 complete-scene formal eligibility differs")
        if self.evidence_sha256 != _model_sha256(self, "evidence_sha256"):
            raise ValueError("A.3 complete-scene evidence digest differs")
        return self


def build_a3_complete_scene_collision_world_v2(
    *,
    bound_plan_sha256: str,
    phase_index: int,
    phase_sha256: str,
    path_sha256: str,
    base_world: A3SelfCollisionWorldV1,
    base_shape_payloads: tuple[A3ShapePayloadV1, ...],
    scene_geometry: A3SceneCollisionGeometryReceiptV1,
    scene_state: A3SceneStateReceiptV1,
    allowed_robot_contact_paths: tuple[str, ...],
    allowed_external_contact_paths: tuple[str, ...],
    real_attached_geometry_resolver: bool,
    contract_test_only: bool,
) -> A3CompleteSceneCollisionWorldV2:
    if scene_state.bound_plan_sha256 != bound_plan_sha256:
        raise A3CompleteSceneCollisionUnavailable("A.3 scene state crossed the bound exact plan")
    expected = _expected_components(
        base_world=base_world,
        base_shape_payloads=base_shape_payloads,
        scene_geometry=scene_geometry,
        scene_state=scene_state,
        allowed_robot_contact_paths=allowed_robot_contact_paths,
        allowed_external_contact_paths=allowed_external_contact_paths,
    )
    attached = expected["attached_object_paths"]
    if contract_test_only and real_attached_geometry_resolver:
        raise A3CompleteSceneCollisionUnavailable(
            "A.3 contract world cannot claim a real attachment resolver"
        )
    formal_eligible = bool(
        not contract_test_only
        and scene_state.real_runtime_provider
        and not scene_state.contract_test_only
        and (not attached or real_attached_geometry_resolver)
    )
    data: dict[str, Any] = {
        "schema_version": "A3CompleteSceneCollisionWorldV2",
        "bound_plan_sha256": bound_plan_sha256,
        "phase_index": phase_index,
        "phase_sha256": phase_sha256,
        "path_sha256": path_sha256,
        "base_world": base_world.model_dump(mode="json"),
        "base_shape_payloads": [item.model_dump(mode="json") for item in base_shape_payloads],
        "scene_geometry": scene_geometry.model_dump(mode="json"),
        "scene_state": scene_state.model_dump(mode="json"),
        "allowed_robot_contact_paths": allowed_robot_contact_paths,
        "allowed_external_contact_paths": allowed_external_contact_paths,
        "robot_link_paths": expected["robot_link_paths"],
        "ordinary_environment_link_paths": expected["ordinary_environment_link_paths"],
        "attached_object_paths": attached,
        "environment_environment_acm_pairs": expected["environment_environment_acm_pairs"],
        "phase_allowed_contact_acm_pairs": expected["phase_allowed_contact_acm_pairs"],
        "shape_payloads": [item.model_dump(mode="json") for item in expected["shape_payloads"]],
        "collision_world": expected["collision_world"].model_dump(mode="json"),
        "complete_robot_self_coverage": True,
        "complete_robot_environment_coverage": True,
        "complete_attached_object_environment_coverage": True,
        "environment_environment_pairs_intentionally_excluded": True,
        "only_frozen_phase_contacts_excluded": True,
        "real_attached_geometry_resolver": real_attached_geometry_resolver,
        "contract_test_only": contract_test_only,
        "formal_query_evidence_eligible": formal_eligible,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return A3CompleteSceneCollisionWorldV2(
        **data,
        evidence_sha256=canonical_sha256(data),
    )
