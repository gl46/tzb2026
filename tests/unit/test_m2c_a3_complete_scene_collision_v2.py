from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from m2c.s4_scene_family import materialize_scene
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3ShapePayloadV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3ConvexChildV1,
    A3LinkChildTransformSequenceV1,
    A3RigidTransformV1,
    A3SelfCollisionWorldV1,
    bullet_shipped_margin_for_shape_v1,
    build_child_pair_ccd_request_v1,
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_collision_v2 import (
    A3CompleteSceneCollisionUnavailable,
    build_a3_complete_scene_collision_world_v2,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    build_a3_scene_collision_geometry_v1,
    produce_a3_scene_state_receipt_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCountersV1,
)


ROOT = Path(__file__).resolve().parents[2]
DIGEST = "a" * 64
IDENTITY = A3RigidTransformV1(
    translation_world_m=(0.0, 0.0, 0.0),
    rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scene_geometry(tmp_path: Path) -> A3SceneCollisionGeometryReceiptV1:
    manifest = json.loads((ROOT / "configs/m2c_s4_v4_training_keys.json").read_bytes())
    record = manifest["training_keys"][0]
    template = (ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf").read_text()
    result = materialize_scene(
        template,
        int(record["scene_seed"]),
        tuple(record["anchor_xy_m"]),
    )
    assert result is not None
    sdf_raw, supervision_raw, _ = result
    assert hashlib.sha256(sdf_raw).hexdigest() == record["sdf_sha256"]
    assert hashlib.sha256(supervision_raw).hexdigest() == record["supervision_sha256"]
    sdf = tmp_path / "scene.sdf"
    supervision = tmp_path / "scene.supervision.json"
    sdf.write_bytes(sdf_raw)
    supervision.write_bytes(supervision_raw)
    return build_a3_scene_collision_geometry_v1(
        sdf_path=sdf,
        supervision_path=supervision,
        expected_sdf_sha256=record["sdf_sha256"],
        expected_supervision_sha256=record["supervision_sha256"],
        expected_scene_seed=record["scene_seed"],
    )


class _Counters:
    implementation_sha256 = "b" * 64
    real_active_session_source = False
    mocked_counter_source = True

    def snapshot_mutation_counters(self) -> ActiveSessionMutationCountersV1:
        return ActiveSessionMutationCountersV1(
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            controller_commands=0,
            attachment_mutations=0,
        )


class _SceneProvider:
    configuration_sha256 = "c" * 64
    real_runtime_provider = False
    contract_test_only = True
    mutation_counter_source = _Counters()
    implementation_path = str(Path(__file__))
    implementation_sha256 = _sha(Path(__file__))

    def __init__(self, geometry: A3SceneCollisionGeometryReceiptV1) -> None:
        self.geometry = geometry

    def query_scene_link_world_poses(
        self,
        *,
        link_paths: tuple[str, ...],
        after_ns: int,
    ) -> tuple[dict[str, A3RigidTransformV1], int]:
        return (
            {
                item.link_path: item.source_initial_world_transform
                for item in self.geometry.source_links
            },
            after_ns + 1,
        )


def _scene_state(tmp_path: Path) -> tuple[A3SceneCollisionGeometryReceiptV1, Any]:
    geometry = _scene_geometry(tmp_path)
    state = produce_a3_scene_state_receipt_v1(
        bound_plan_sha256=DIGEST,
        runtime_snapshot_sha256="d" * 64,
        geometry=geometry,
        provider=_SceneProvider(geometry),
        after_ns=100,
        require_real_runtime_provider=False,
    )
    return geometry, state


def _payload(path: str) -> A3ShapePayloadV1:
    margin = bullet_shipped_margin_for_shape_v1("BOX", (0.1, 0.1, 0.1))
    data = {
        "schema_version": "A3ShapePayloadV1",
        "link_path": path,
        "child_index": 0,
        "shape_kind": "BOX",
        "shape_parameters": (0.1, 0.1, 0.1),
        "decoded_vertices_xyz_m": (),
        "hull_construction_tolerance_m": 1e-7,
        "outward_padding_m": 0.002,
        "collision_margin_m": margin,
        "every_decoded_stl_vertex_retained": False,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    return A3ShapePayloadV1(**data, payload_sha256=canonical_sha256(data))


def _child(payload: A3ShapePayloadV1) -> A3ConvexChildV1:
    data = {
        "schema_version": "A3ConvexChildV1",
        "link_path": payload.link_path,
        "child_index": 0,
        "shape_kind": "BOX",
        "local_transform": IDENTITY.model_dump(mode="json"),
        "shape_parameters_sha256": payload.payload_sha256,
        "source_asset_path": "contract.urdf",
        "source_asset_sha256": DIGEST,
        "source_vertex_count": 0,
        "decoded_vertices_sha256": None,
        "smallest_conservative_radius_m": 0.05,
        "maximum_angular_motion_radius_m": 0.095,
        "collision_margin_m": payload.collision_margin_m,
        "outward_padding_m": 0.002,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    return A3ConvexChildV1(**data, child_sha256=canonical_sha256(data))


def _base_world(
    *,
    scene_geometry: A3SceneCollisionGeometryReceiptV1,
    attached_path: str | None = None,
) -> tuple[A3SelfCollisionWorldV1, tuple[A3ShapePayloadV1, ...]]:
    payloads = [_payload("/World/Robot/link_a"), _payload("/World/Robot/link_b")]
    children = [_child(payload) for payload in payloads]
    transforms = [
        A3LinkChildTransformSequenceV1(
            link_path=child.link_path,
            child_index=0,
            transforms=(
                IDENTITY,
                A3RigidTransformV1(
                    translation_world_m=(0.01, 0.0, 0.0),
                    rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
                ),
                A3RigidTransformV1(
                    translation_world_m=(0.02, 0.0, 0.0),
                    rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
                ),
            ),
        )
        for child in children
    ]
    acm: set[tuple[str, str]] = set()
    attached_paths: tuple[str, ...] = ()
    if attached_path is not None:
        scene_child = next(
            item for item in scene_geometry.children if item.link_path == attached_path
        )
        scene_payload = next(
            item for item in scene_geometry.shape_payloads if item.link_path == attached_path
        )
        children.append(scene_child)
        payloads.append(scene_payload)
        transforms.append(
            A3LinkChildTransformSequenceV1(
                link_path=attached_path,
                child_index=0,
                transforms=(IDENTITY, IDENTITY, IDENTITY),
            )
        )
        attached_paths = (attached_path,)
        acm.add(tuple(sorted(("/World/Robot/link_a", attached_path))))
    ordered = sorted(
        zip(children, payloads, transforms, strict=True),
        key=lambda item: item[0].link_path,
    )
    data = {
        "schema_version": "A3SelfCollisionWorldV1",
        "children": [item[0].model_dump(mode="json") for item in ordered],
        "transforms": [item[2].model_dump(mode="json") for item in ordered],
        "acm_link_pairs": sorted(acm),
        "attached_object_paths": attached_paths,
        "executor_state_count": 3,
    }
    return (
        A3SelfCollisionWorldV1(**data, world_sha256=canonical_sha256(data)),
        tuple(item[1] for item in ordered),
    )


def _build(
    tmp_path: Path,
    *,
    allowed_robot: tuple[str, ...] = (),
    allowed_external: tuple[str, ...] = (),
    attached_path: str | None = None,
):
    geometry, state = _scene_state(tmp_path)
    base, payloads = _base_world(
        scene_geometry=geometry,
        attached_path=attached_path,
    )
    evidence = build_a3_complete_scene_collision_world_v2(
        bound_plan_sha256=DIGEST,
        phase_index=0,
        phase_sha256="e" * 64,
        path_sha256="f" * 64,
        base_world=base,
        base_shape_payloads=payloads,
        scene_geometry=geometry,
        scene_state=state,
        allowed_robot_contact_paths=allowed_robot,
        allowed_external_contact_paths=allowed_external,
        real_attached_geometry_resolver=False,
        contract_test_only=True,
    )
    return evidence


def test_complete_scene_world_checks_robot_environment_and_not_environment_environment(
    tmp_path: Path,
) -> None:
    evidence = _build(tmp_path)
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256=DIGEST,
        world=evidence.collision_world,
        configuration=canonical_a3_bullet_numeric_configuration_v1(),
    )

    assert len(evidence.collision_world.children) == 10
    assert len(evidence.environment_environment_acm_pairs) == 28
    assert request.expected_non_acm_child_pair_count == 17
    request_link_pairs = {tuple(sorted((item.link_a, item.link_b))) for item in request.segments}
    assert any(
        {left.split("/")[2], right.split("/")[2]} == {"M1B", "Robot"}
        for left, right in request_link_pairs
    )
    assert not any(
        left.startswith("/World/M1B/") and right.startswith("/World/M1B/")
        for left, right in request_link_pairs
    )
    assert evidence.formal_query_evidence_eligible is False


def test_only_exact_frozen_phase_contact_pair_is_excluded(tmp_path: Path) -> None:
    evidence = _build(
        tmp_path,
        allowed_robot=("/World/Robot/link_a",),
        allowed_external=("/World/M1B/cylinder_01",),
    )
    assert evidence.phase_allowed_contact_acm_pairs == (
        ("/World/M1B/cylinder_01/link", "/World/Robot/link_a"),
    )
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256=DIGEST,
        world=evidence.collision_world,
        configuration=canonical_a3_bullet_numeric_configuration_v1(),
    )
    assert request.expected_non_acm_child_pair_count == 16


@pytest.mark.parametrize(
    ("robot", "external"),
    (
        (("/World/Robot/link_a",), ()),
        (("/World/Robot/missing",), ("/World/M1B/cylinder_01",)),
        (("/World/Robot/link_a",), ("/World/M1B/missing",)),
    ),
)
def test_one_sided_or_unresolved_phase_allowlist_rejects(
    tmp_path: Path,
    robot: tuple[str, ...],
    external: tuple[str, ...],
) -> None:
    with pytest.raises(A3CompleteSceneCollisionUnavailable, match="allowlist"):
        _build(tmp_path, allowed_robot=robot, allowed_external=external)


def test_attached_object_is_not_duplicated_and_still_checks_other_environment(
    tmp_path: Path,
) -> None:
    attached = "/World/M1B/cylinder_01/link"
    evidence = _build(tmp_path, attached_path=attached)
    assert evidence.attached_object_paths == (attached,)
    assert attached not in evidence.ordinary_environment_link_paths
    assert sum(item.link_path == attached for item in evidence.collision_world.children) == 1
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256=DIGEST,
        world=evidence.collision_world,
        configuration=canonical_a3_bullet_numeric_configuration_v1(),
    )
    request_link_pairs = {tuple(sorted((item.link_a, item.link_b))) for item in request.segments}
    assert tuple(sorted((attached, "/World/M1B/cylinder_02/link"))) in request_link_pairs
    assert evidence.formal_query_evidence_eligible is False


def test_complete_scene_evidence_replays_and_rejects_acm_tamper(tmp_path: Path) -> None:
    evidence = _build(tmp_path)
    dumped: dict[str, Any] = evidence.model_dump(mode="json")
    dumped["collision_world"]["acm_link_pairs"].pop()
    world = dumped["collision_world"]
    world["world_sha256"] = canonical_sha256(
        {key: value for key, value in world.items() if key != "world_sha256"}
    )
    dumped["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in dumped.items() if key != "evidence_sha256"}
    )
    with pytest.raises(ValueError, match="not reproducible"):
        type(evidence).model_validate(dumped)


def test_attached_geometry_must_equal_frozen_scene_source(tmp_path: Path) -> None:
    geometry, state = _scene_state(tmp_path)
    attached = "/World/M1B/cylinder_01/link"
    base, payloads = _base_world(scene_geometry=geometry, attached_path=attached)
    attached_index = next(
        index for index, item in enumerate(payloads) if item.link_path == attached
    )
    dumped = payloads[attached_index].model_dump(mode="json")
    dumped["shape_parameters"] = [0.02, 0.08]
    dumped["collision_margin_m"] = bullet_shipped_margin_for_shape_v1("CYLINDER", (0.02, 0.08))
    dumped["payload_sha256"] = canonical_sha256(
        {key: value for key, value in dumped.items() if key != "payload_sha256"}
    )
    changed = type(payloads[attached_index]).model_validate(dumped)
    changed_payloads = list(payloads)
    changed_payloads[attached_index] = changed

    base_dump = base.model_dump(mode="json")
    child_dump = base_dump["children"][attached_index]
    child_dump["shape_parameters_sha256"] = changed.payload_sha256
    child_dump["collision_margin_m"] = changed.collision_margin_m
    child_dump["child_sha256"] = canonical_sha256(
        {key: value for key, value in child_dump.items() if key != "child_sha256"}
    )
    base_dump["world_sha256"] = canonical_sha256(
        {key: value for key, value in base_dump.items() if key != "world_sha256"}
    )
    changed_base = type(base).model_validate(base_dump)

    with pytest.raises(A3CompleteSceneCollisionUnavailable, match="attached geometry"):
        build_a3_complete_scene_collision_world_v2(
            bound_plan_sha256=DIGEST,
            phase_index=0,
            phase_sha256="e" * 64,
            path_sha256="f" * 64,
            base_world=changed_base,
            base_shape_payloads=tuple(changed_payloads),
            scene_geometry=geometry,
            scene_state=state,
            allowed_robot_contact_paths=(),
            allowed_external_contact_paths=(),
            real_attached_geometry_resolver=False,
            contract_test_only=True,
        )
