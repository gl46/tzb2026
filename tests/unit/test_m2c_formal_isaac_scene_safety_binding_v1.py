from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_m2c_a3_scene_environment_v1 import _geometry
from test_m2c_formal_exact_plan_synthesis_v1 import _request_and_mapping
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3RigidTransformV1
from xh_agent.policy.qrm_lite.formal_isaac_scene_safety_binding_v1 import (
    PUBLIC_SCENE_BINDING_AMBIGUITY_MARGIN_M,
    PUBLIC_SCENE_BINDING_DISTANCE_QUANTUM_M,
    PUBLIC_SCENE_BINDING_RESIDUAL_GATE_M,
    FormalIsaacActiveAttachmentRegistryV1,
    FormalIsaacPublicTrackSceneSafetySourceV1,
    FormalIsaacSceneSafetyBindingUnavailable,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCountersV1,
)


ROOT = Path(__file__).resolve().parents[2]


class _Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, dict(payload)))


class _Counters:
    implementation_sha256 = "a" * 64
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


class _PoseSource:
    implementation_path = str(Path(__file__).resolve())
    implementation_sha256 = "b" * 64
    configuration_sha256 = "c" * 64
    real_runtime_provider = False
    contract_test_only = True

    def __init__(
        self,
        *,
        counters: _Counters,
        positions: dict[str, tuple[float, float, float]],
    ) -> None:
        self.mutation_counter_source = counters
        self.positions = positions

    def query_scene_link_world_poses(
        self,
        *,
        link_paths: tuple[str, ...],
        after_ns: int,
    ) -> tuple[dict[str, A3RigidTransformV1], int]:
        return (
            {
                path: A3RigidTransformV1(
                    translation_world_m=self.positions[path],
                    rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
                )
                for path in link_paths
            },
            after_ns + 1,
        )


def _source(
    tmp_path: Path,
    *,
    request: Any,
    ambiguous_path: bool = False,
) -> tuple[FormalIsaacPublicTrackSceneSafetySourceV1, _Journal, Any]:
    geometry = _geometry(tmp_path)
    target = request.runtime_request.model_target_track_id
    assert target is not None
    track = next(
        item
        for item in request.observation.observation.perception_tracks
        if item.track_id == target
    )
    assert track.pose_xyzquat is not None
    target_position = tuple(float(value) for value in track.pose_xyzquat[:3])
    positions: dict[str, tuple[float, float, float]] = {}
    for index, item in enumerate(geometry.source_links):
        positions[item.link_path] = (
            target_position[0] + 0.10 + index * 0.10,
            target_position[1],
            target_position[2],
        )
    first = geometry.dynamic_collision_link_paths[0]
    second = geometry.dynamic_collision_link_paths[1]
    positions[first] = (target_position[0] + 0.005, *target_position[1:])
    if ambiguous_path:
        positions[second] = (target_position[0] + 0.010, *target_position[1:])
    counters = _Counters()
    journal = _Journal()
    registry = FormalIsaacActiveAttachmentRegistryV1(
        mode="CONTRACT_TEST",
        journal=journal,
        now_ns=lambda: 10_000,
    )
    source = FormalIsaacPublicTrackSceneSafetySourceV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        association_deployment=request.observation.association_deployment,
        scene_geometry=geometry,
        scene_pose_source=_PoseSource(counters=counters, positions=positions),
        mutation_counter_source=counters,
        active_attachment_source=registry,
        journal=journal,
    )
    return source, journal, registry


def test_selected_public_track_is_uniquely_bound_for_a3_only(tmp_path: Path) -> None:
    request, _ = _request_and_mapping("GRASP")
    source, journal, _registry = _source(tmp_path, request=request)

    binding = source.query_scene_safety_binding(
        request=request,
        observation=request.observation,
        after_ns=request.observation.captured_at_ns,
    )

    assert binding.target_public_track_id == request.runtime_request.model_target_track_id
    assert binding.target_external_contact_path == "/World/M1B/cylinder_01/link"
    assert binding.target_binding_receipt_sha256
    assert binding.simulator_paths_exposed_to_model is False
    assert binding.simulator_paths_used_only_for_a3_gates is True
    event, payload = journal.events[-1]
    assert event == "PUBLIC_TRACK_SCENE_SAFETY_BINDING_COMMITTED"
    target_receipt = payload["target_binding"]
    assert target_receipt["selected_residual_quanta"] == 5_000
    assert len(target_receipt["scene_path_distances"]) == 6
    assert PUBLIC_SCENE_BINDING_DISTANCE_QUANTUM_M == 0.000001
    assert PUBLIC_SCENE_BINDING_RESIDUAL_GATE_M == 0.02
    assert PUBLIC_SCENE_BINDING_AMBIGUITY_MARGIN_M == 0.02


def test_scene_path_ambiguity_rejects_without_journal_commit(tmp_path: Path) -> None:
    request, _ = _request_and_mapping("GRASP")
    source, journal, _registry = _source(
        tmp_path,
        request=request,
        ambiguous_path=True,
    )

    with pytest.raises(FormalIsaacSceneSafetyBindingUnavailable, match="two plausible"):
        source.query_scene_safety_binding(
            request=request,
            observation=request.observation,
            after_ns=request.observation.captured_at_ns,
        )

    assert journal.events == []


def test_active_attachment_is_cross_bound_to_fresh_public_mapping(tmp_path: Path) -> None:
    request, _ = _request_and_mapping("MOVE")
    source, journal, registry = _source(tmp_path, request=request)
    target = request.runtime_request.model_target_track_id
    assert target is not None
    active = registry.commit_attachment(
        public_track_id=target,
        external_contact_path="/World/M1B/cylinder_01/link",
        bound_plan_sha256="d" * 64,
        phase_sha256="e" * 64,
    )

    binding = source.query_scene_safety_binding(
        request=request,
        observation=request.observation,
        after_ns=request.observation.captured_at_ns,
    )

    assert binding.attached_public_track_id == target
    assert binding.attached_external_contact_path == binding.target_external_contact_path
    assert binding.active_attachment_receipt_sha256 == active.receipt_sha256
    assert [event for event, _payload in journal.events] == [
        "FORMAL_ACTIVE_ATTACHMENT_COMMITTED",
        "PUBLIC_TRACK_SCENE_SAFETY_BINDING_COMMITTED",
    ]


def test_attachment_registry_is_single_active_state_and_removal_is_create_once() -> None:
    journal = _Journal()
    times = iter((10, 20))
    registry = FormalIsaacActiveAttachmentRegistryV1(
        mode="CONTRACT_TEST",
        journal=journal,
        now_ns=lambda: next(times),
    )
    active = registry.commit_attachment(
        public_track_id="track-deadbeef",
        external_contact_path="/World/M1B/cylinder_01/link",
        bound_plan_sha256="1" * 64,
        phase_sha256="2" * 64,
    )
    with pytest.raises(FormalIsaacSceneSafetyBindingUnavailable, match="already exists"):
        registry.commit_attachment(
            public_track_id="track-deadbeef",
            external_contact_path="/World/M1B/cylinder_01/link",
            bound_plan_sha256="1" * 64,
            phase_sha256="2" * 64,
        )
    removed = registry.commit_removal(
        bound_plan_sha256="3" * 64,
        phase_sha256="4" * 64,
    )

    assert removed.removed_attachment_receipt_sha256 == active.receipt_sha256
    assert registry.snapshot_active_attachment() is None
    with pytest.raises(FormalIsaacSceneSafetyBindingUnavailable, match="absent"):
        registry.commit_removal(
            bound_plan_sha256="3" * 64,
            phase_sha256="4" * 64,
        )
