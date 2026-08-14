from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from xh_agent.policy.qrm_lite.a3_attached_object_phase_geometry_v1 import (
    A3AttachedObjectPhaseGeometryEvidenceV1,
    A3AttachedObjectPhaseGeometryUnavailable,
    A3PlannedAttachedObjectBindingV1,
    A3QueryOnlyAttachedObjectPhaseGeometryResolverV1,
)
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
