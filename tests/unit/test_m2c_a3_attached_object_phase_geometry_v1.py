from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import TypeAdapter

from xh_agent.policy.qrm_lite.a3_attached_object_phase_geometry_v1 import (
    A3AttachedObjectPhaseGeometryEvidenceV1,
    A3AttachedObjectPhaseGeometryUnavailable,
    A3PlannedAttachedObjectBindingV1,
    A3QueryOnlyAttachedObjectPhaseGeometryResolverV1,
)
from xh_agent.policy.qrm_lite.a3_active_session_attached_object_geometry_v2 import (
    A3ActiveSessionAttachedObjectPhaseGeometryResolverV2,
)
from xh_agent.policy.qrm_lite.a3_active_session_attachment_evidence_v2 import (
    A3AttachedObjectPhaseGeometryEvidenceAnyV2,
    A3AttachedObjectPhaseGeometryEvidenceV2,
    A3ExecutedAttachmentBindingV2,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3RigidTransformV1
from xh_agent.policy.qrm_lite.a3_attachment_transition_v1 import (
    A3AttachmentTransitionProviderV1,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    build_a3_scene_collision_geometry_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    ControllerCommandShapeV1,
    NonActuatingJointSampleV1,
    NonActuatingPhasePathV1,
    PreflightRuntimeSnapshotV1,
    canonical_non_actuating_state_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_isaac_scene_safety_binding_v1 import (
    FormalIsaacActiveAttachmentRegistryV2,
    FormalIsaacSceneSafetyBindingUnavailable,
)
from xh_agent.policy.qrm_lite.isaac_exact_plan_runtime_v1 import (
    ExactPlanRuntimeUnavailable,
    FrozenProbeExactPlanExecutorV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCountersV1,
)


ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    "CARTESIAN_POSE": 7,
    "GRIPPER_POSITION": 1,
    "ATTACH_CONTACT_ENTITY": 0,
    "REMOVE_ATTACHMENT": 0,
    "PUBLIC_RGBD_CAPTURE": 0,
    "PUBLIC_TRACK_REASSOCIATION": 0,
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _scene_bytes() -> tuple[bytes, bytes]:
    cylinders = "".join(
        f"""
    <model name="cylinder_{index:02d}"><pose>{-0.05 - index * 0.01} {0.10 + index * 0.01} 0.4901 0 0 0</pose>
      <link name="link"><collision name="collision"><geometry>
        <cylinder><radius>0.015</radius><length>0.08</length></cylinder>
      </geometry></collision></link></model>"""
        for index in range(1, 7)
    )
    sdf = f"""<sdf version="1.9"><world name="industrial_cylinder_v1">
    <model name="industrial_work_table"><static>true</static><link name="link"><pose>0 0 0.4 0 0 0</pose>
      <collision name="collision"><geometry><box><size>1.5 1.0 0.1</size></box></geometry></collision></link></model>
    <model name="camera_fixture"><static>true</static><link name="camera_rgbd"/></model>
    {cylinders}
    <model name="blue_partition_bin"><static>true</static><pose>0.2 0.15 0.45 0 0 1.57079632679</pose>
      <link name="link"><collision name="floor"><pose>0 0 0.01 0 0 0</pose>
        <geometry><box><size>0.42 0.32 0.02</size></box></geometry></collision></link></model>
    </world></sdf>""".encode()
    supervision = json.dumps(
        {
            "scene_id": "IndustrialCylinderBenchmarkV1",
            "seed": 19000,
            "simulator_supervision": {
                "training_and_evaluation_only": True,
                "objects": [
                    {
                        "actual_sim_entity_id": f"cylinder_{index:02d}",
                        "category": "industrial_cylinder",
                        "position_3d_world": [
                            -0.05 - index * 0.01,
                            0.10 + index * 0.01,
                            0.4901,
                        ],
                        "yaw": 0.0,
                    }
                    for index in range(1, 7)
                ],
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sdf, supervision


def _geometry(tmp_path: Path) -> A3SceneCollisionGeometryReceiptV1:
    sdf_raw, supervision_raw = _scene_bytes()
    sdf = tmp_path / "scene.sdf"
    supervision = tmp_path / "scene.supervision.json"
    sdf.write_bytes(sdf_raw)
    supervision.write_bytes(supervision_raw)
    return build_a3_scene_collision_geometry_v1(
        sdf_path=sdf,
        supervision_path=supervision,
        expected_sdf_sha256=_sha(sdf_raw),
        expected_supervision_sha256=_sha(supervision_raw),
        expected_scene_seed=19000,
    )


class _Counters:
    implementation_sha256 = "1" * 64
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


class _SceneProvider:
    configuration_sha256 = "2" * 64
    real_runtime_provider = False
    contract_test_only = True

    def __init__(
        self,
        geometry: A3SceneCollisionGeometryReceiptV1,
        *,
        mutate: bool = False,
    ) -> None:
        self.implementation_path = str(Path(__file__))
        self.implementation_sha256 = _sha(Path(__file__).read_bytes())
        self.geometry = geometry
        self.mutation_counter_source = _Counters()
        self.mutate = mutate

    def query_scene_link_world_poses(self, *, link_paths, after_ns):
        states = {
            item.link_path: item.source_initial_world_transform
            for item in self.geometry.source_links
        }
        if self.mutate:
            self.mutation_counter_source.value += 1
        return {path: states[path] for path in link_paths}, after_ns + 1


def _snapshot(plan_sha256: str) -> PreflightRuntimeSnapshotV1:
    payload = {
        "schema_version": "PreflightRuntimeSnapshotV1",
        "bound_plan_sha256": plan_sha256,
        "preplan_state_sha256": "3" * 64,
        "observed_at_ns": 100,
        "checked_at_ns": 101,
        "controller_id": "official_franka_dls",
        "controller_configuration_sha256": "4" * 64,
        "controller_ready": True,
        "controller_readiness_query_duration_ns": 1,
        "controller_rate_hz": 60.0,
        "command_shapes": [
            ControllerCommandShapeV1(command=command, dimensions=dimensions).model_dump(mode="json")
            for command, dimensions in COMMANDS.items()
        ],
        "collision_world_ready": True,
        "contact_monitor_ready": True,
        "attachment_monitor_ready": True,
        "terminal_bilateral_contact_broker_ready": True,
        "active_attachment_present": False,
        "active_attachment_sha256": None,
        "emergency_stop_active": False,
        "state_stale": False,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return PreflightRuntimeSnapshotV1(
        **payload,
        snapshot_sha256=canonical_sha256(payload),
    )


def _attachment_configuration(provider: A3AttachmentTransitionProviderV1):
    payload = {
        "schema_version": "AttachmentPreflightConfigurationV1",
        "algorithm_id": "A3_PLANNED_ATTACHMENT_TRANSITION_CONTRACT_V1",
        "algorithm_sha256": provider.algorithm_sha256,
        "contact_monitor_configuration_sha256": "5" * 64,
        "attachment_monitor_configuration_sha256": "6" * 64,
        "timeout_ns_per_phase": 1_000_000,
        "require_unique_bilateral_contact_pair": True,
        "require_terminal_bilateral_contact_selector": True,
        "query_only_required": True,
    }
    config = AttachmentPreflightConfigurationV1(
        **payload,
        configuration_sha256=canonical_sha256(payload),
    )
    return SimpleNamespace(attachment=config)


def _sample(index: int, position: tuple[float, float, float]) -> NonActuatingJointSampleV1:
    payload = {
        "schema_version": "NonActuatingJointSampleV1",
        "sample_index": index,
        "joint_positions": (0.0, 0.0),
        "estimated_abs_efforts": (0.0, 0.0),
        "end_effector_world_m": position,
        "end_effector_world_wxyz": (1.0, 0.0, 0.0, 0.0),
        "gripper_position_m": 0.04,
        "ik_applicable": False,
        "ik_converged": True,
        "ik_position_residual_m": 0.0,
        "ik_orientation_residual_rad": 0.0,
        "iterations": 0,
    }
    return NonActuatingJointSampleV1(
        **payload,
        state_sha256=canonical_non_actuating_state_sha256(payload),
    )


def _path(
    plan_sha256: str,
    phase,
    positions: tuple[tuple[float, float, float], ...],
) -> NonActuatingPhasePathV1:
    samples = tuple(_sample(index, position) for index, position in enumerate(positions))
    payload = {
        "schema_version": "NonActuatingPhasePathV1",
        "bound_plan_sha256": plan_sha256,
        "phase_index": phase.phase.phase_index,
        "phase_sha256": phase.phase_sha256,
        "start_state_sha256": samples[0].state_sha256,
        "terminal_state_sha256": samples[-1].state_sha256,
        "joint_names": ("joint_a", "joint_b"),
        "sample_rate_hz": 60.0,
        "samples": [item.model_dump(mode="json") for item in samples],
        "ik_algorithm_sha256": "7" * 64,
        "ik_configuration_sha256": "8" * 64,
        "joint_limit_configuration_sha256": "9" * 64,
        "gripper_limit_configuration_sha256": "a" * 64,
        "effort_estimator_sha256": "b" * 64,
        "query_duration_ns": 1,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return NonActuatingPhasePathV1(
        **payload,
        path_sha256=canonical_sha256(payload),
    )


def _phase(index: int, command: str):
    robot = (
        "/World/Robot/panda_leftfinger",
        "/World/Robot/panda_rightfinger",
    )
    external = ("/World/M1B/cylinder_01/link",)
    return SimpleNamespace(
        phase=SimpleNamespace(
            phase_index=index,
            command=command,
            allowed_robot_contact_paths=robot if command == "ATTACH_CONTACT_ENTITY" else (),
            allowed_external_contact_paths=external if command == "ATTACH_CONTACT_ENTITY" else (),
        ),
        phase_sha256=canonical_sha256({"phase": index, "command": command}),
        attachment_or_removal_selector=(
            "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"
            if command == "ATTACH_CONTACT_ENTITY"
            else "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT"
            if command == "REMOVE_ATTACHMENT"
            else "NONE"
        ),
    )


def _bound_resolver(tmp_path: Path, *, mutate: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    plan_sha = "c" * 64
    attach_phase = _phase(0, "ATTACH_CONTACT_ENTITY")
    motion_phase = _phase(1, "CARTESIAN_POSE")
    remove_phase = _phase(2, "REMOVE_ATTACHMENT")
    plan = SimpleNamespace(
        bound_plan_sha256=plan_sha,
        phases=(attach_phase, motion_phase, remove_phase),
    )
    attach_path = _path(plan_sha, attach_phase, ((0.0, 0.0, 0.5), (0.0, 0.0, 0.5)))
    snapshot = _snapshot(plan_sha)
    transition_provider = A3AttachmentTransitionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime_snapshot=snapshot,
        runtime_snapshot_provider_implementation_sha256="d" * 64,
        real_runtime_snapshot=False,
        monotonic_ns=iter((10, 20)).__next__,
    )
    transition = transition_provider.query_phase(
        plan,
        attach_phase,
        attach_path,
        expected_attachment_present=False,
        expected_attachment_sha256=None,
        configuration=_attachment_configuration(transition_provider),
    )
    geometry = _geometry(tmp_path)
    resolver = A3QueryOnlyAttachedObjectPhaseGeometryResolverV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        bound_plan_sha256=plan_sha,
        runtime_snapshot_checked_at_ns=snapshot.checked_at_ns,
        scene_geometry=geometry,
        scene_pose_provider=_SceneProvider(geometry, mutate=mutate),
    )
    return resolver, plan, attach_phase, motion_phase, remove_phase, attach_path, transition


def test_planned_attachment_replays_rigid_geometry_for_every_motion_sample(
    tmp_path: Path,
) -> None:
    resolver, plan, attach_phase, motion_phase, _, attach_path, transition = _bound_resolver(
        tmp_path
    )
    resolver.bind_planned_attachment(
        attachment=transition,
        plan=plan,
        phase=attach_phase,
        path=attach_path,
    )
    motion_path = _path(
        plan.bound_plan_sha256,
        motion_phase,
        ((0.0, 0.0, 0.5), (0.0, 0.0, 0.6)),
    )
    assert transition.attachment_sha256_after is not None
    geometry = resolver.geometry_for_phase(
        attachment_sha256=transition.attachment_sha256_after,
        plan=plan,
        phase=motion_phase,
        path=motion_path,
    )
    evidence = resolver.phase_evidence(
        attachment_sha256=transition.attachment_sha256_after,
        path_sha256=motion_path.path_sha256,
    )

    assert geometry.attached_object_path == "/World/M1B/cylinder_01/link"
    assert geometry.children == tuple(
        item
        for item in evidence.attachment_binding.scene_geometry.children
        if item.link_path == geometry.attached_object_path
    )
    first, second = geometry.transforms[0].transforms
    assert second.translation_world_m[2] - first.translation_world_m[2] == pytest.approx(0.1)
    assert evidence.geometry == geometry
    assert evidence.formal_query_evidence_eligible is False
    assert evidence.teacher_used is False
    assert evidence.privileged_truth_policy_input is False


def test_relative_transform_and_phase_geometry_tamper_fail_replay(tmp_path: Path) -> None:
    resolver, plan, attach_phase, motion_phase, _, attach_path, transition = _bound_resolver(
        tmp_path
    )
    resolver.bind_planned_attachment(
        attachment=transition,
        plan=plan,
        phase=attach_phase,
        path=attach_path,
    )
    assert transition.attachment_sha256_after is not None
    motion_path = _path(
        plan.bound_plan_sha256,
        motion_phase,
        ((0.0, 0.0, 0.5), (0.1, 0.0, 0.5)),
    )
    resolver.geometry_for_phase(
        attachment_sha256=transition.attachment_sha256_after,
        plan=plan,
        phase=motion_phase,
        path=motion_path,
    )
    evidence = resolver.phase_evidence(
        attachment_sha256=transition.attachment_sha256_after,
        path_sha256=motion_path.path_sha256,
    )

    binding_raw = evidence.attachment_binding.model_dump(mode="json")
    binding_raw["attachment_transition_evidence_sha256"] = "0" * 64
    binding_raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in binding_raw.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="source evidence"):
        A3PlannedAttachedObjectBindingV1.model_validate(binding_raw)

    binding_raw = evidence.attachment_binding.model_dump(mode="json")
    binding_raw["hand_to_object_transform"]["translation_world_m"][0] += 0.01
    binding_raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in binding_raw.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="relative transform"):
        A3PlannedAttachedObjectBindingV1.model_validate(binding_raw)

    phase_raw = evidence.model_dump(mode="json")
    phase_raw["geometry"]["transforms"][0]["transforms"][1]["translation_world_m"][0] += 0.01
    phase_raw["geometry"]["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in phase_raw["geometry"].items() if key != "receipt_sha256"}
    )
    phase_raw["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in phase_raw.items() if key != "evidence_sha256"}
    )
    with pytest.raises(ValueError, match="not reproducible"):
        A3AttachedObjectPhaseGeometryEvidenceV1.model_validate(phase_raw)


def test_unknown_initial_attachment_and_mutating_scene_provider_fail_closed(
    tmp_path: Path,
) -> None:
    resolver, plan, attach_phase, _, _, attach_path, transition = _bound_resolver(
        tmp_path / "clean"
    )
    with pytest.raises(A3AttachedObjectPhaseGeometryUnavailable, match="initial attachment"):
        resolver.validate_initial_attachment(attachment_sha256="e" * 64, plan=plan)

    mutating, plan, attach_phase, _, _, attach_path, transition = _bound_resolver(
        tmp_path / "mutating",
        mutate=True,
    )
    with pytest.raises(Exception, match="mutation"):
        mutating.bind_planned_attachment(
            attachment=transition,
            plan=plan,
            phase=attach_phase,
            path=attach_path,
        )


def test_release_consumes_binding_and_prevents_geometry_reuse(tmp_path: Path) -> None:
    resolver, plan, attach_phase, motion_phase, remove_phase, attach_path, transition = (
        _bound_resolver(tmp_path)
    )
    resolver.bind_planned_attachment(
        attachment=transition,
        plan=plan,
        phase=attach_phase,
        path=attach_path,
    )
    assert transition.attachment_sha256_after is not None
    remove_path = _path(
        plan.bound_plan_sha256,
        remove_phase,
        ((0.0, 0.0, 0.5), (0.0, 0.0, 0.5)),
    )
    resolver.release_planned_attachment(
        attachment_sha256=transition.attachment_sha256_after,
        plan=plan,
        phase=remove_phase,
        path=remove_path,
    )
    motion_path = _path(
        plan.bound_plan_sha256,
        motion_phase,
        ((0.0, 0.0, 0.5), (0.0, 0.0, 0.6)),
    )
    with pytest.raises(A3AttachedObjectPhaseGeometryUnavailable, match="motion phase"):
        resolver.geometry_for_phase(
            attachment_sha256=transition.attachment_sha256_after,
            plan=plan,
            phase=motion_phase,
            path=motion_path,
        )


def test_real_mode_rejects_contract_scene_provider(tmp_path: Path) -> None:
    geometry = _geometry(tmp_path)
    with pytest.raises(A3AttachedObjectPhaseGeometryUnavailable, match="mode differs"):
        A3QueryOnlyAttachedObjectPhaseGeometryResolverV1(
            project_root=ROOT,
            mode="REAL_ISAAC",
            bound_plan_sha256="c" * 64,
            runtime_snapshot_checked_at_ns=101,
            scene_geometry=geometry,
            scene_pose_provider=_SceneProvider(geometry),
        )


class _Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def append(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))


def _executed_attachment(tmp_path: Path):
    resolver, plan, attach_phase, _, _, attach_path, transition = _bound_resolver(tmp_path)
    resolver.bind_planned_attachment(
        attachment=transition,
        plan=plan,
        phase=attach_phase,
        path=attach_path,
    )
    planned = resolver.planned_attachment_bindings()[0]
    journal = _Journal()
    registry = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=journal,
        now_ns=lambda: 1_000,
    )
    executed = registry.commit_attachment(
        public_track_id="track-deadbeef",
        external_contact_path=planned.external_link_path,
        bound_plan_sha256=planned.bound_plan_sha256,
        phase_sha256=planned.attachment_transition_evidence.phase_sha256,
        planned_attachment_binding=planned,
    )
    return planned, executed, registry, journal


def test_executed_attachment_carries_query_geometry_into_the_next_plan(
    tmp_path: Path,
) -> None:
    planned, executed, _, journal = _executed_attachment(tmp_path)
    next_plan_sha256 = "e" * 64
    motion_phase = _phase(0, "CARTESIAN_POSE")
    next_plan = SimpleNamespace(
        bound_plan_sha256=next_plan_sha256,
        phases=(motion_phase,),
    )
    resolver = A3ActiveSessionAttachedObjectPhaseGeometryResolverV2(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        bound_plan_sha256=next_plan_sha256,
        runtime_snapshot_sha256="f" * 64,
        runtime_snapshot_checked_at_ns=2_000,
        current_hand_world_transform=planned.attach_hand_world_transform,
        scene_geometry=planned.scene_geometry,
        scene_pose_provider=_SceneProvider(planned.scene_geometry),
        active_attachment=executed,
    )
    resolver.validate_initial_attachment(
        attachment_sha256=executed.receipt_sha256,
        plan=next_plan,
    )
    motion_path = _path(
        next_plan_sha256,
        motion_phase,
        ((0.0, 0.0, 0.5), (0.0, 0.0, 0.6)),
    )
    geometry = resolver.geometry_for_phase(
        attachment_sha256=executed.receipt_sha256,
        plan=next_plan,
        phase=motion_phase,
        path=motion_path,
    )
    evidence = resolver.phase_evidence(
        attachment_sha256=executed.receipt_sha256,
        path_sha256=motion_path.path_sha256,
    )

    assert geometry.attachment_receipt_sha256 == executed.receipt_sha256
    assert evidence.attachment_binding.active_attachment == executed
    assert evidence.bound_plan_sha256 == next_plan_sha256
    replayed = TypeAdapter(A3AttachedObjectPhaseGeometryEvidenceAnyV2).validate_python(
        evidence.model_dump(mode="json")
    )
    assert isinstance(replayed, A3AttachedObjectPhaseGeometryEvidenceV2)
    first, second = geometry.transforms[0].transforms
    assert second.translation_world_m[2] - first.translation_world_m[2] == pytest.approx(0.1)
    assert journal.events[0][0] == "FORMAL_ACTIVE_ATTACHMENT_V2_COMMITTED"


def test_executed_attachment_rejects_crossed_plan_phase_and_mode(tmp_path: Path) -> None:
    planned, executed, registry, _ = _executed_attachment(tmp_path)
    raw = executed.model_dump(mode="json")
    raw["phase_sha256"] = "0" * 64
    raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="planned A.3 geometry"):
        A3ExecutedAttachmentBindingV2.model_validate(raw)

    with pytest.raises(FormalIsaacSceneSafetyBindingUnavailable, match="already exists"):
        registry.commit_attachment(
            public_track_id="track-deadbeef",
            external_contact_path=planned.external_link_path,
            bound_plan_sha256=planned.bound_plan_sha256,
            phase_sha256=planned.attachment_transition_evidence.phase_sha256,
            planned_attachment_binding=planned,
        )

    with pytest.raises(A3AttachedObjectPhaseGeometryUnavailable, match="mode differs"):
        A3ActiveSessionAttachedObjectPhaseGeometryResolverV2(
            project_root=ROOT,
            mode="REAL_ISAAC",
            bound_plan_sha256="e" * 64,
            runtime_snapshot_sha256="f" * 64,
            runtime_snapshot_checked_at_ns=2_000,
            current_hand_world_transform=A3RigidTransformV1(
                translation_world_m=(0.0, 0.0, 0.5),
                rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
            ),
            scene_geometry=planned.scene_geometry,
            scene_pose_provider=_SceneProvider(planned.scene_geometry),
            active_attachment=executed,
        )


class _MutationRecorder:
    def __init__(self) -> None:
        self.scene = 0
        self.attachment = 0

    def record_scene_mutations(self, count: int = 1) -> None:
        self.scene += count

    def record_attachment_mutations(self, count: int = 1) -> None:
        self.attachment += count


class _AttachProbe:
    np = np

    def __init__(self) -> None:
        self.attached: list[str] = []

    def _step_pose(self, *_args, **_kwargs):
        raise AssertionError("pose helper must not be called")

    def _step_gripper(self, *_args, **_kwargs):
        raise AssertionError("gripper helper must not be called")

    def _remove_attachment(self, *_args, **_kwargs):
        raise AssertionError("remove helper must not be called")

    def _attach_preserving_pose(self, entity, _hand, _object) -> None:
        self.attached.append(entity)

    def broker_from_window(self, *_args, **_kwargs):
        raise AssertionError("broker must not be called")

    def evaluate_robot_collision_events(self, *_args, **_kwargs):
        raise AssertionError("collision replay must not be called")

    @staticmethod
    def RigidPrim(path: str):
        return SimpleNamespace(path=path)


def _attachment_executor(
    *,
    plan,
    registry: FormalIsaacActiveAttachmentRegistryV2,
    journal: _Journal,
    probe: _AttachProbe,
) -> FrozenProbeExactPlanExecutorV1:
    return FrozenProbeExactPlanExecutorV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        probe=probe,
        robot=object(),
        hand_prim=object(),
        contact_collector=object(),
        sensors={},
        contact_views={},
        journal=journal,
        state_digest=lambda: "3" * 64,
        capture_public=lambda *_args, **_kwargs: None,
        reassociate_public=lambda *_args, **_kwargs: None,
        mutation_counter_source=_MutationRecorder(),
        attachment_state_registry=registry,
    )


def test_executor_commits_exact_preflight_attachment_binding_after_helper(
    tmp_path: Path,
) -> None:
    resolver, plan, attach_phase, _, _, attach_path, transition = _bound_resolver(tmp_path)
    resolver.bind_planned_attachment(
        attachment=transition,
        plan=plan,
        phase=attach_phase,
        path=attach_path,
    )
    planned = resolver.planned_attachment_bindings()[0]
    plan.inputs = SimpleNamespace(target_track_id="track-deadbeef")
    attach_phase.phase.contact_entity_selection = "TERMINAL_BILATERAL_CONTACT"
    attach_phase.phase.allowed_external_contact_paths = (
        "/World/M1B/cylinder_01/link",
        "/World/M1B/cylinder_02/link",
    )
    journal = _Journal()
    registry = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=journal,
        now_ns=lambda: 3_000,
    )
    probe = _AttachProbe()
    executor = _attachment_executor(
        plan=plan,
        registry=registry,
        journal=journal,
        probe=probe,
    )
    executor.bind_preflight_attachment_bindings(plan, (planned,))
    executor._attachment_candidate = "cylinder_01"
    executor._attachment_candidate_phase_index = -1

    result = executor._execute_attach(plan, attach_phase)

    active = registry.snapshot_active_attachment()
    assert active is not None
    assert active.planned_attachment_binding == planned
    assert active.helper_returned_before_registry_commit is True
    assert result["active_attachment_receipt_sha256"] == active.receipt_sha256
    assert probe.attached == ["cylinder_01"]

    second_journal = _Journal()
    second_probe = _AttachProbe()
    second_registry = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=second_journal,
        now_ns=lambda: 3_001,
    )
    crossed = _attachment_executor(
        plan=plan,
        registry=second_registry,
        journal=second_journal,
        probe=second_probe,
    )
    crossed.bind_preflight_attachment_bindings(plan, (planned,))
    crossed._attachment_candidate = "cylinder_02"
    crossed._attachment_candidate_phase_index = -1
    with pytest.raises(ExactPlanRuntimeUnavailable, match="differs from its preflight"):
        crossed._execute_attach(plan, attach_phase)
    assert second_probe.attached == []
