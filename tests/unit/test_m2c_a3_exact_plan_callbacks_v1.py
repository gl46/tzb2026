from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xh_agent.policy.qrm_lite.a3_exact_plan_callbacks_v1 import (
    IMPLEMENTATION_REPO_PATH,
    A3ExactPlanCallbacksUnavailable,
    A3ExactPlanNonActuatingCallbacksV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    ControllerCommandShapeV1,
    ControllerPreflightConfigurationV1,
    ExactPlanPreflightConfigurationV1,
    GripperLimitConfigurationV1,
    IKPreflightConfigurationV1,
    JointLimitConfigurationV1,
    PreflightRuntimeSnapshotV1,
    SafetyPreflightConfigurationV1,
    SweptCollisionConfigurationV1,
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


def _with_digest(cls: Any, **payload: Any):
    provisional = cls.model_construct(**payload, configuration_sha256="0" * 64)
    dumped = provisional.model_dump(mode="json")
    dumped["configuration_sha256"] = canonical_sha256(
        provisional.model_dump(mode="json", exclude={"configuration_sha256"})
    )
    return cls.model_validate(dumped)


def _configuration(callback_sha256: str, *, ik: str, collision: str, attachment: str):
    ik_config = _with_digest(
        IKPreflightConfigurationV1,
        algorithm_id="LULA_QUERY_ONLY_PHASE_PATH_V1",
        algorithm_sha256=ik,
        robot_description_sha256="1" * 64,
        base_frame="panda_link0",
        end_effector_frame="panda_hand",
        maximum_position_residual_m=0.002,
        maximum_orientation_residual_rad=0.01,
        maximum_iterations_per_sample=64,
        timeout_ns_per_phase=1_000_000,
    )
    limits = _with_digest(
        JointLimitConfigurationV1,
        source_sha256="2" * 64,
        joint_names=("joint_a", "joint_b"),
        lower_position=(-2.0, -2.0),
        upper_position=(2.0, 2.0),
        maximum_velocity_per_s=(2.0, 2.0),
        maximum_abs_effort=(10.0, 10.0),
        effort_estimator_sha256="3" * 64,
    )
    gripper = _with_digest(
        GripperLimitConfigurationV1,
        source_sha256="4" * 64,
        minimum_position_m=0.0,
        maximum_position_m=0.08,
        maximum_velocity_m_per_s=1.0,
        target_tolerance_m=0.001,
        timeout_ns_per_phase=1_000_000,
    )
    collision_config = _with_digest(
        SweptCollisionConfigurationV1,
        algorithm_id="A3_BULLET_CHILD_PAIR_CCD_CONTRACT_V1",
        algorithm_sha256=collision,
        collision_geometry_sha256="5" * 64,
        robot_root_path="/World/Robot",
        subsamples_per_segment=1,
        timeout_ns_per_phase=1_000_000,
    )
    controller = _with_digest(
        ControllerPreflightConfigurationV1,
        controller_id="official_franka_dls",
        controller_configuration_sha256="6" * 64,
        readiness_timeout_ns=1_000_000,
    )
    safety = _with_digest(
        SafetyPreflightConfigurationV1,
        safety_configuration_sha256="7" * 64,
        workspace_min_world_m=(-1.0, -1.0, 0.0),
        workspace_max_world_m=(1.0, 1.0, 1.0),
        maximum_state_age_ns=100,
        contact_monitor_configuration_sha256="8" * 64,
        attachment_monitor_configuration_sha256="9" * 64,
    )
    attachment_config = _with_digest(
        AttachmentPreflightConfigurationV1,
        algorithm_id="A3_PLANNED_ATTACHMENT_TRANSITION_CONTRACT_V1",
        algorithm_sha256=attachment,
        contact_monitor_configuration_sha256=(safety.contact_monitor_configuration_sha256),
        attachment_monitor_configuration_sha256=(safety.attachment_monitor_configuration_sha256),
        timeout_ns_per_phase=1_000_000,
    )
    return _with_digest(
        ExactPlanPreflightConfigurationV1,
        ik=ik_config,
        joint_limits=limits,
        gripper_limits=gripper,
        swept_collision=collision_config,
        controller=controller,
        safety=safety,
        attachment=attachment_config,
        callback_implementation_sha256=callback_sha256,
        total_timeout_ns=10_000_000,
    )


class _Counter:
    implementation_sha256 = "a" * 64
    real_active_session_source = False
    mocked_counter_source = True

    def __init__(self) -> None:
        self.writes = 0

    def snapshot_mutation_counters(self):
        return ActiveSessionMutationCountersV1(
            articulation_target_writes=self.writes,
            simulation_steps=0,
            scene_mutations=0,
            controller_commands=0,
            attachment_mutations=0,
        )


class _PathProvider:
    formal_query_evidence_eligible = False
    ik_algorithm_sha256 = "b" * 64

    def __init__(self, counter: _Counter) -> None:
        self.state_source = SimpleNamespace(mutation_counter_source=counter)
        self.calls: list[int] = []

    def solve_phase_path(self, plan, phase, *, start_state_sha256, configuration):
        del configuration
        self.calls.append(phase.phase.phase_index)
        sample_count = phase.phase.steps + 1 if phase.phase.command == "CARTESIAN_POSE" else 1
        return SimpleNamespace(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            path_sha256=canonical_sha256(
                {"phase": phase.phase.phase_index, "start": start_state_sha256}
            ),
            samples=tuple(SimpleNamespace() for _ in range(sample_count)),
        )


class _CollisionProvider:
    formal_query_evidence_eligible = False
    algorithm_sha256 = "c" * 64
    complete_continuous_self_collision_coverage = True
    complete_scene_environment_collision_coverage = True
    query_only = True

    def __init__(self) -> None:
        self.attached_counts: list[int] = []

    def query_phase(
        self,
        plan,
        phase,
        path,
        *,
        configuration,
        attached_objects=(),
        attached_object_phase_geometry_evidence=(),
    ):
        del plan, path, configuration
        assert len(attached_objects) == len(attached_object_phase_geometry_evidence)
        self.attached_counts.append(len(attached_objects))
        return SimpleNamespace(phase_index=phase.phase.phase_index)


class _IncompleteSceneCollisionProvider(_CollisionProvider):
    complete_scene_environment_collision_coverage = False


class _AttachmentProvider:
    formal_query_evidence_eligible = False
    algorithm_sha256 = "d" * 64

    def __init__(self, snapshot: PreflightRuntimeSnapshotV1) -> None:
        self.runtime_snapshot = snapshot

    def query_phase(
        self,
        plan,
        phase,
        path,
        *,
        expected_attachment_present,
        expected_attachment_sha256,
        configuration,
    ):
        del plan, path, configuration
        command = phase.phase.command
        if command == "ATTACH_CONTACT_ENTITY":
            return SimpleNamespace(
                transition="ATTACH",
                attachment_sha256_after="e" * 64,
                attachment_present_after=True,
            )
        return SimpleNamespace(
            transition="NONE",
            attachment_sha256_after=expected_attachment_sha256,
            attachment_present_after=expected_attachment_present,
        )


class _Resolver:
    implementation_sha256 = "f" * 64
    real_runtime_provider = False
    mocked_provider = True
    query_only = True

    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.geometry_calls: list[str] = []
        self.fail_geometry = False
        self.last_geometry = None
        self.last_phase = None
        self.last_path = None
        self.fail_evidence = False

    def validate_initial_attachment(self, *, attachment_sha256, plan):
        del plan
        if attachment_sha256 not in self.bound:
            raise RuntimeError("unknown initial attachment")

    def bind_planned_attachment(self, *, attachment, plan, phase, path):
        del plan, phase, path
        self.bound.add(attachment.attachment_sha256_after)

    def geometry_for_phase(self, *, attachment_sha256, plan, phase, path):
        if self.fail_geometry or attachment_sha256 not in self.bound:
            raise RuntimeError("attached geometry unavailable")
        self.geometry_calls.append(attachment_sha256)
        self.last_geometry = SimpleNamespace(
            attachment_receipt_sha256=attachment_sha256,
            executor_state_count=len(path.samples),
        )
        self.last_phase = phase
        self.last_path = path
        return self.last_geometry

    def phase_evidence(self, *, attachment_sha256, path_sha256):
        if (
            self.fail_evidence
            or self.last_geometry is None
            or self.last_phase is None
            or self.last_path is None
            or attachment_sha256 not in self.bound
            or path_sha256 != self.last_path.path_sha256
        ):
            raise RuntimeError("attached phase evidence unavailable")
        return SimpleNamespace(
            geometry=self.last_geometry,
            bound_plan_sha256=self.last_path.bound_plan_sha256,
            phase_index=self.last_phase.phase.phase_index,
            phase_sha256=self.last_phase.phase_sha256,
            path_sha256=path_sha256,
        )

    def release_planned_attachment(self, *, attachment_sha256, plan, phase, path):
        del plan, phase, path
        self.bound.remove(attachment_sha256)


def _snapshot(plan_sha256: str):
    payload = {
        "schema_version": "PreflightRuntimeSnapshotV1",
        "bound_plan_sha256": plan_sha256,
        "preplan_state_sha256": "1" * 64,
        "observed_at_ns": 100,
        "checked_at_ns": 101,
        "controller_id": "official_franka_dls",
        "controller_configuration_sha256": "6" * 64,
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


def _phase(index: int, command: str, *, steps: int = 0):
    return SimpleNamespace(
        phase=SimpleNamespace(phase_index=index, command=command, steps=steps),
        phase_sha256=canonical_sha256({"index": index, "command": command}),
    )


def _stack(*, collision: _CollisionProvider | None = None):
    plan_sha256 = "0" * 64
    snapshot = _snapshot(plan_sha256)
    counter = _Counter()
    path = _PathProvider(counter)
    collision = collision or _CollisionProvider()
    attachment = _AttachmentProvider(snapshot)
    resolver = _Resolver()
    callback_sha256 = hashlib.sha256((ROOT / IMPLEMENTATION_REPO_PATH).read_bytes()).hexdigest()
    configuration = _configuration(
        callback_sha256,
        ik=path.ik_algorithm_sha256,
        collision=collision.algorithm_sha256,
        attachment=attachment.algorithm_sha256,
    )
    callbacks = A3ExactPlanNonActuatingCallbacksV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        configuration=configuration,
        runtime_snapshot=snapshot,
        runtime_snapshot_real=False,
        mutation_counter_source=counter,
        phase_path_provider=path,
        swept_collision_provider=collision,
        attachment_transition_provider=attachment,
        attached_geometry_resolver=resolver,
    )
    phases = (_phase(0, "ATTACH_CONTACT_ENTITY"), _phase(1, "CARTESIAN_POSE", steps=2))
    plan = SimpleNamespace(
        bound_plan_sha256=plan_sha256,
        phases=phases,
        inputs=SimpleNamespace(
            preplan_state_sha256=snapshot.preplan_state_sha256,
            preplan_state_timestamp_ns=snapshot.observed_at_ns,
        ),
    )
    return callbacks, configuration, counter, collision, resolver, plan


def test_composite_rejects_self_only_collision_provider() -> None:
    with pytest.raises(
        A3ExactPlanCallbacksUnavailable,
        match="configuration/providers do not share one frozen deployment",
    ):
        _stack(collision=_IncompleteSceneCollisionProvider())


def _run_phase(callbacks, configuration, plan, phase, *, start: str):
    path = callbacks.solve_phase_path(
        plan,
        phase,
        start_state_sha256=start,
        configuration=configuration,
    )
    callbacks.check_swept_collision(plan, phase, path, configuration=configuration)
    transition = callbacks.check_attachment_transition(
        plan,
        phase,
        path,
        expected_attachment_present=callbacks._attachment_sha256 is not None,
        expected_attachment_sha256=callbacks._attachment_sha256,
        configuration=configuration,
    )
    return path, transition


def test_composite_requires_attached_payload_geometry_after_planned_attach() -> None:
    callbacks, configuration, _, collision, resolver, plan = _stack()
    assert callbacks.snapshot_runtime(plan) == callbacks.runtime_snapshot
    first_path, first_transition = _run_phase(
        callbacks,
        configuration,
        plan,
        plan.phases[0],
        start=plan.inputs.preplan_state_sha256,
    )
    assert first_transition.attachment_sha256_after in resolver.bound
    _run_phase(
        callbacks,
        configuration,
        plan,
        plan.phases[1],
        start=first_path.path_sha256,
    )
    assert collision.attached_counts == [0, 1]
    assert resolver.geometry_calls == ["e" * 64]
    assert callbacks.complete is True


def test_composite_poisoned_when_attached_payload_geometry_is_missing() -> None:
    callbacks, configuration, _, _, resolver, plan = _stack()
    callbacks.snapshot_runtime(plan)
    first_path, _ = _run_phase(
        callbacks,
        configuration,
        plan,
        plan.phases[0],
        start=plan.inputs.preplan_state_sha256,
    )
    resolver.fail_geometry = True
    path = callbacks.solve_phase_path(
        plan,
        plan.phases[1],
        start_state_sha256=first_path.path_sha256,
        configuration=configuration,
    )
    with pytest.raises(A3ExactPlanCallbacksUnavailable, match="payload phase geometry"):
        callbacks.check_swept_collision(
            plan,
            plan.phases[1],
            path,
            configuration=configuration,
        )
    assert callbacks._stage == "POISONED"


def test_composite_poisoned_when_attached_payload_derivation_evidence_is_missing() -> None:
    callbacks, configuration, _, _, resolver, plan = _stack()
    callbacks.snapshot_runtime(plan)
    first_path, _ = _run_phase(
        callbacks,
        configuration,
        plan,
        plan.phases[0],
        start=plan.inputs.preplan_state_sha256,
    )
    resolver.fail_evidence = True
    path = callbacks.solve_phase_path(
        plan,
        plan.phases[1],
        start_state_sha256=first_path.path_sha256,
        configuration=configuration,
    )
    with pytest.raises(A3ExactPlanCallbacksUnavailable, match="phase evidence is unavailable"):
        callbacks.check_swept_collision(
            plan,
            plan.phases[1],
            path,
            configuration=configuration,
        )
    assert callbacks._stage == "POISONED"


def test_composite_rejects_out_of_order_callback_and_cannot_retry() -> None:
    callbacks, configuration, _, _, _, plan = _stack()
    callbacks.snapshot_runtime(plan)
    fake_path = SimpleNamespace(path_sha256="2" * 64)
    with pytest.raises(A3ExactPlanCallbacksUnavailable, match="phase order"):
        callbacks.check_swept_collision(
            plan,
            plan.phases[0],
            fake_path,
            configuration=configuration,
        )
    with pytest.raises(A3ExactPlanCallbacksUnavailable, match="poisoned"):
        callbacks.solve_phase_path(
            plan,
            plan.phases[0],
            start_state_sha256=plan.inputs.preplan_state_sha256,
            configuration=configuration,
        )


def test_composite_rejects_any_active_session_mutation() -> None:
    callbacks, configuration, counter, _, _, plan = _stack()
    callbacks.snapshot_runtime(plan)
    counter.writes = 1
    with pytest.raises(A3ExactPlanCallbacksUnavailable, match="mutation counters changed"):
        callbacks.solve_phase_path(
            plan,
            plan.phases[0],
            start_state_sha256=plan.inputs.preplan_state_sha256,
            configuration=configuration,
        )
    assert callbacks._stage == "POISONED"
