from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3RigidTransformV1
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3SceneEnvironmentUnavailable,
    IsaacSceneRigidPrimReadOnlySourceV1,
    build_a3_scene_collision_geometry_v1,
    produce_a3_scene_state_receipt_v1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCountersV1,
)


DIGEST = "a" * 64


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sdf_bytes(*, unsupported: bool = False, extra_collision: bool = False) -> bytes:
    cylinders = []
    for index in range(1, 7):
        geometry = (
            "<sphere><radius>0.015</radius></sphere>"
            if unsupported and index == 1
            else "<cylinder><radius>0.015</radius><length>0.08</length></cylinder>"
        )
        cylinders.append(
            f"""
    <model name="cylinder_{index:02d}">
      <pose>{-0.05 - index * 0.01:.9f} {0.10 + index * 0.01:.9f} 0.490100000 0 0 0</pose>
      <link name="link">
        <collision name="collision"><geometry>{geometry}</geometry></collision>
      </link>
    </model>"""
        )
    intruder = (
        """
    <model name="unregistered_obstacle"><static>true</static><link name="link">
      <collision name="collision"><geometry><box><size>1 1 1</size></box></geometry></collision>
    </link></model>"""
        if extra_collision
        else ""
    )
    return f"""<sdf version="1.9">
  <world name="industrial_cylinder_v1">
    <model name="industrial_work_table"><static>true</static><link name="link">
      <pose>0 0 0.4 0 0 0</pose>
      <collision name="collision"><geometry><box><size>1.5 1.0 0.1</size></box></geometry></collision>
    </link></model>
    <model name="camera_fixture"><static>true</static><link name="camera_rgbd"/></model>
    {"".join(cylinders)}
    <model name="blue_partition_bin"><static>true</static><pose>0.2 0.15 0.45 0 0 1.57079632679</pose>
      <link name="link"><collision name="floor"><pose>0 0 0.01 0 0 0</pose>
        <geometry><box><size>0.42 0.32 0.02</size></box></geometry>
      </collision></link>
    </model>{intruder}
  </world>
</sdf>""".encode()


def _supervision_bytes(*, mismatch: bool = False) -> bytes:
    objects = []
    for index in range(1, 7):
        position = [-0.05 - index * 0.01, 0.10 + index * 0.01, 0.4901]
        if mismatch and index == 1:
            position[0] += 0.1
        objects.append(
            {
                "actual_sim_entity_id": f"cylinder_{index:02d}",
                "category": "industrial_cylinder",
                "position_3d_world": position,
                "yaw": 0.0,
            }
        )
    return json.dumps(
        {
            "scene_id": "IndustrialCylinderBenchmarkV1",
            "seed": 19000,
            "simulator_supervision": {
                "training_and_evaluation_only": True,
                "objects": objects,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _write_scene(
    tmp_path: Path,
    *,
    unsupported: bool = False,
    extra_collision: bool = False,
    supervision_mismatch: bool = False,
) -> tuple[Path, Path, str, str]:
    sdf_raw = _sdf_bytes(unsupported=unsupported, extra_collision=extra_collision)
    supervision_raw = _supervision_bytes(mismatch=supervision_mismatch)
    sdf = tmp_path / "scene.sdf"
    supervision = tmp_path / "scene.supervision.json"
    sdf.write_bytes(sdf_raw)
    supervision.write_bytes(supervision_raw)
    return sdf, supervision, _sha(sdf_raw), _sha(supervision_raw)


def _geometry(tmp_path: Path) -> A3SceneCollisionGeometryReceiptV1:
    sdf, supervision, sdf_sha, supervision_sha = _write_scene(tmp_path)
    return build_a3_scene_collision_geometry_v1(
        sdf_path=sdf,
        supervision_path=supervision,
        expected_sdf_sha256=sdf_sha,
        expected_supervision_sha256=supervision_sha,
        expected_scene_seed=19000,
    )


def test_generated_scene_replays_complete_eight_primitive_environment(tmp_path: Path) -> None:
    receipt = _geometry(tmp_path)

    assert receipt.exact_collision_model_count == 8
    assert receipt.exact_collision_primitive_count == 8
    assert receipt.static_collision_link_paths == (
        "/World/M1B/blue_partition_bin/link",
        "/World/M1B/industrial_work_table/link",
    )
    assert receipt.dynamic_collision_link_paths == tuple(
        f"/World/M1B/cylinder_{index:02d}/link" for index in range(1, 7)
    )
    assert tuple(item.shape_kind for item in receipt.shape_payloads).count("BOX") == 2
    assert tuple(item.shape_kind for item in receipt.shape_payloads).count("CYLINDER") == 6
    assert all(item.source_asset_sha256 == receipt.source_sdf.sha256 for item in receipt.children)
    assert receipt.teacher_used is False
    assert receipt.privileged_truth_policy_input is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"extra_collision": True}, "model set/order"),
        ({"unsupported": True}, "unsupported SDF collision shape"),
        ({"supervision_mismatch": True}, "SDF/supervision"),
    ),
)
def test_scene_geometry_rejects_unknown_shape_or_supervision_crossing(
    tmp_path: Path,
    kwargs: dict[str, bool],
    message: str,
) -> None:
    sdf, supervision, sdf_sha, supervision_sha = _write_scene(tmp_path, **kwargs)

    with pytest.raises(A3SceneEnvironmentUnavailable, match=message):
        build_a3_scene_collision_geometry_v1(
            sdf_path=sdf,
            supervision_path=supervision,
            expected_sdf_sha256=sdf_sha,
            expected_supervision_sha256=supervision_sha,
            expected_scene_seed=19000,
        )


def test_scene_geometry_rejects_hash_tamper_and_symlink(tmp_path: Path) -> None:
    sdf, supervision, sdf_sha, supervision_sha = _write_scene(tmp_path)
    with pytest.raises(A3SceneEnvironmentUnavailable, match="byte binding"):
        build_a3_scene_collision_geometry_v1(
            sdf_path=sdf,
            supervision_path=supervision,
            expected_sdf_sha256="0" * 64,
            expected_supervision_sha256=supervision_sha,
            expected_scene_seed=19000,
        )

    symlink = tmp_path / "scene-link.sdf"
    symlink.symlink_to(sdf)
    with pytest.raises(OSError):
        build_a3_scene_collision_geometry_v1(
            sdf_path=symlink,
            supervision_path=supervision,
            expected_sdf_sha256=sdf_sha,
            expected_supervision_sha256=supervision_sha,
            expected_scene_seed=19000,
        )


class _Counters:
    implementation_sha256 = "b" * 64
    real_active_session_source = False
    mocked_counter_source = True

    def __init__(self) -> None:
        self.value = 0

    def snapshot_mutation_counters(self) -> ActiveSessionMutationCountersV1:
        return ActiveSessionMutationCountersV1(
            articulation_target_writes=self.value,
            simulation_steps=0,
            scene_mutations=0,
            controller_commands=0,
            attachment_mutations=0,
        )


class _Provider:
    configuration_sha256 = "c" * 64
    real_runtime_provider = False
    contract_test_only = True

    def __init__(
        self,
        *,
        geometry: A3SceneCollisionGeometryReceiptV1,
        implementation_path: Path,
        counters: _Counters,
        missing: bool = False,
        mutate: bool = False,
    ) -> None:
        self.implementation_path = str(implementation_path)
        self.implementation_sha256 = _sha(implementation_path.read_bytes())
        self.mutation_counter_source = counters
        self.geometry = geometry
        self.missing = missing
        self.mutate = mutate

    def query_scene_link_world_poses(
        self,
        *,
        link_paths: tuple[str, ...],
        after_ns: int,
    ) -> tuple[dict[str, A3RigidTransformV1], int]:
        result = {
            item.link_path: item.source_initial_world_transform
            for item in self.geometry.source_links
        }
        if self.missing:
            result.pop(link_paths[0])
        if self.mutate:
            self.mutation_counter_source.value += 1
        return result, after_ns + 1


def test_scene_state_receipt_binds_every_link_and_shared_mutation_counter(
    tmp_path: Path,
) -> None:
    geometry = _geometry(tmp_path)
    counters = _Counters()
    provider = _Provider(
        geometry=geometry,
        implementation_path=Path(__file__),
        counters=counters,
    )

    receipt = produce_a3_scene_state_receipt_v1(
        bound_plan_sha256=DIGEST,
        runtime_snapshot_sha256="d" * 64,
        geometry=geometry,
        provider=provider,
        after_ns=100,
        require_real_runtime_provider=False,
    )

    assert tuple(item.link_path for item in receipt.link_states) == tuple(
        item.link_path for item in geometry.source_links
    )
    assert receipt.observed_at_ns == 101
    assert receipt.mutation_counters_before == receipt.mutation_counters_after
    assert receipt.query_only is True
    assert receipt.formal_evidence is False


@pytest.mark.parametrize("failure", ("missing", "mutate"))
def test_scene_state_receipt_rejects_missing_or_mutating_provider(
    tmp_path: Path,
    failure: str,
) -> None:
    geometry = _geometry(tmp_path)
    provider = _Provider(
        geometry=geometry,
        implementation_path=Path(__file__),
        counters=_Counters(),
        missing=failure == "missing",
        mutate=failure == "mutate",
    )

    with pytest.raises(A3SceneEnvironmentUnavailable, match="coverage, or mutation"):
        produce_a3_scene_state_receipt_v1(
            bound_plan_sha256=DIGEST,
            runtime_snapshot_sha256="d" * 64,
            geometry=geometry,
            provider=provider,
            after_ns=100,
            require_real_runtime_provider=False,
        )


class _Prim:
    def __init__(self, position: tuple[float, float, float]) -> None:
        self.position = position

    def get_world_poses(self) -> tuple[list[list[float]], list[list[float]]]:
        return [list(self.position)], [[1.0, 0.0, 0.0, 0.0]]


def test_concrete_rigid_prim_source_calls_getters_only(tmp_path: Path) -> None:
    geometry = _geometry(tmp_path)
    counters = _Counters()
    implementation = Path(__file__)
    prims = {
        item.link_path: _Prim(item.source_initial_world_transform.translation_world_m)
        for item in geometry.source_links
    }
    source = IsaacSceneRigidPrimReadOnlySourceV1(
        implementation_path=implementation,
        implementation_sha256=_sha(implementation.read_bytes()),
        configuration_sha256="c" * 64,
        rigid_prim_runtime_type=f"{_Prim.__module__}.{_Prim.__qualname__}",
        prims_by_path=prims,
        mutation_counter_source=counters,
        now_ns=lambda: 102,
        real_runtime_provider=False,
        contract_test_only=True,
    )

    receipt = produce_a3_scene_state_receipt_v1(
        bound_plan_sha256=DIGEST,
        runtime_snapshot_sha256="d" * 64,
        geometry=geometry,
        provider=source,
        after_ns=100,
        require_real_runtime_provider=False,
    )

    assert receipt.observed_at_ns == 102
    assert counters.value == 0
    assert len(receipt.link_states) == 8


def test_scene_receipt_rejects_missing_link_state(tmp_path: Path) -> None:
    geometry = _geometry(tmp_path)
    provider = _Provider(
        geometry=geometry,
        implementation_path=Path(__file__),
        counters=_Counters(),
    )
    receipt = produce_a3_scene_state_receipt_v1(
        bound_plan_sha256=DIGEST,
        runtime_snapshot_sha256="d" * 64,
        geometry=geometry,
        provider=provider,
        after_ns=100,
        require_real_runtime_provider=False,
    )
    dumped: dict[str, Any] = receipt.model_dump(mode="json")
    dumped["link_states"].pop()
    dumped["state_sha256"] = hashlib.sha256(b"unrelated").hexdigest()
    dumped["receipt_sha256"] = hashlib.sha256(b"unrelated-receipt").hexdigest()
    with pytest.raises(ValueError, match="at least 8"):
        type(receipt).model_validate(dumped)
