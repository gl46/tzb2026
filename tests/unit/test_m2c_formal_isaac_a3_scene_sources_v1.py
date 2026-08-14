from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from m2c.formal_isaac_v4_backend import (
    FormalIsaacV4BackendV2,
    _now_after,
)
from test_m2c_a3_attached_object_phase_geometry_v1 import _scene_bytes
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3RigidTransformV1,
    build_a3_scene_collision_geometry_v1,
    produce_a3_scene_state_receipt_v1,
)
from xh_agent.policy.qrm_lite.formal_isaac_mutation_counter_v1 import (
    FormalIsaacActiveSessionMutationCounterV1,
    build_formal_isaac_mutation_counter_activation_v1,
)


ROOT = Path(__file__).resolve().parents[2]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class _StagePrim:
    def IsValid(self) -> bool:  # noqa: N802 - USD API spelling
        return True


class _Stage:
    def GetPrimAtPath(self, path: str) -> _StagePrim:  # noqa: N802 - USD API spelling
        del path
        return _StagePrim()


class _Prim:
    transforms: dict[str, A3RigidTransformV1] = {}

    def __init__(self, path: str) -> None:
        self.path = path

    def get_world_poses(self):
        transform = self.transforms[self.path]
        return (
            [list(transform.translation_world_m)],
            [list(transform.rotation_world_wxyz)],
        )


def test_backend_materializes_complete_getter_only_scene_source(tmp_path: Path) -> None:
    sdf_raw, supervision_raw = _scene_bytes()
    sdf = tmp_path / "scene.sdf"
    supervision = tmp_path / "scene.supervision.json"
    stage = tmp_path / "scene.usdc"
    sdf.write_bytes(sdf_raw)
    supervision.write_bytes(supervision_raw)
    stage.write_bytes(b"contract-stage")
    geometry = build_a3_scene_collision_geometry_v1(
        sdf_path=sdf,
        supervision_path=supervision,
        expected_sdf_sha256=_sha(sdf_raw),
        expected_supervision_sha256=_sha(supervision_raw),
        expected_scene_seed=19000,
    )
    _Prim.transforms = {
        item.link_path: item.source_initial_world_transform for item in geometry.source_links
    }
    backend = object.__new__(FormalIsaacV4BackendV2)
    backend.probe = SimpleNamespace(
        ARGS=SimpleNamespace(seed=19000),
        RigidPrim=_Prim,
    )
    backend.sdf_path = sdf
    backend.supervision_path = supervision
    backend.stage_path = stage
    backend.stage_sha256 = _sha(stage.read_bytes())
    backend.stage = _Stage()
    backend.scene_dynamic_prims = {
        item.model_name: _Prim(item.link_path) for item in geometry.source_links if item.dynamic
    }

    backend._initialize_a3_query_sources()

    assert backend.a3_scene_geometry == geometry
    assert backend.a3_mutation_counter.snapshot_mutation_counters() == (
        backend.a3_mutation_counter_activation.initial_counters
    )
    receipt = produce_a3_scene_state_receipt_v1(
        bound_plan_sha256="a" * 64,
        runtime_snapshot_sha256="b" * 64,
        geometry=backend.a3_scene_geometry,
        provider=backend.a3_scene_pose_source,
        after_ns=1,
        require_real_runtime_provider=True,
    )
    assert len(receipt.link_states) == 8
    assert receipt.real_runtime_provider is True
    assert receipt.contract_test_only is False
    assert receipt.mutation_counters_before == receipt.mutation_counters_after


class _SimulationApp:
    def __init__(self) -> None:
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


class _SimulationManager:
    @staticmethod
    def get_num_physics_steps() -> int:
        return 2

    @staticmethod
    def get_physics_dt() -> float:
        return 1.0 / 60.0


def test_post_activation_update_is_counted_before_kit_update() -> None:
    activation = build_formal_isaac_mutation_counter_activation_v1(
        project_root=ROOT,
        scene_owner_path=Path(__file__),
        stage_sha256="1" * 64,
        sdf_sha256="2" * 64,
        supervision_sha256="3" * 64,
        activated_at_ns=1,
    )
    counter = FormalIsaacActiveSessionMutationCounterV1(activation=activation)
    app = _SimulationApp()
    probe = SimpleNamespace(
        simulation_app=app,
        SimulationManager=_SimulationManager,
    )

    observed = _now_after(probe, 0, counter)

    assert observed > 0
    assert app.updates == 1
    assert counter.snapshot_mutation_counters().simulation_steps == 1


def test_backend_source_orders_scene_stability_before_counter_activation() -> None:
    source = (ROOT / "scripts/m2c/formal_isaac_v4_backend.py").read_text(encoding="utf-8")
    constructor = source[source.index("class FormalIsaacV4BackendV2") :]
    assert constructor.index("self._initialize_scene_once()") < constructor.index(
        "self._initialize_a3_query_sources()"
    )
    capture = source[source.index("    def _capture_public") : source.index("    def capture")]
    assert capture.index("record_simulation_steps()") < capture.index("p.rep.orchestrator.step(")
    assert (
        "privileged_truth"
        not in source[
            source.index("    def _initialize_a3_query_sources") : source.index("    def start")
        ]
    )
