from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any, Literal

import pytest

from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    canonical_non_actuating_state_sha256,
    ControllerCommandShapeV1,
    ControllerPreflightConfigurationV1,
    ExactPlanA3DeploymentBindingV2,
    ExactPlanPreflightConfigurationV1,
    ExactPlanPreflightRejected,
    ExactPlanPreflightV1,
    GripperLimitConfigurationV1,
    HostSignedAppendOnlyA3VerifierReceiptV1,
    IKPreflightConfigurationV1,
    IsaacLulaStartupIntrospectionReceiptV1,
    JointLimitConfigurationV1,
    NonActuatingJointSampleV1,
    NonActuatingAttachmentTransitionV1,
    NonActuatingPhasePathV1,
    NonActuatingSweptCollisionV1,
    PreflightRuntimeSnapshotV1,
    PlannedBilateralContactPairV1,
    SafetyPreflightConfigurationV1,
    SweptCollisionConfigurationV1,
    SweptCollisionPairV1,
    SweptCollisionSegmentV1,
    require_formal_a3_execution_authorization,
    strict_replay_a3_audit_receipt_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactGraspGeometryV1,
    ExactPlanA1InputsV1,
    ExactPlanPhaseContractV1,
    ExactPlanSourceBindingV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    canonical_json_bytes,
    canonical_sha256,
)


DIGEST = "a" * 64
COMMANDS = {
    "CARTESIAN_POSE": 7,
    "GRIPPER_POSITION": 1,
    "ATTACH_CONTACT_ENTITY": 0,
    "REMOVE_ATTACHMENT": 0,
    "PUBLIC_RGBD_CAPTURE": 0,
    "PUBLIC_TRACK_REASSOCIATION": 0,
}
ROLES = (
    "PRIMITIVE_ENTRYPOINT",
    "PREFLIGHT_IMPLEMENTATION",
    "EXECUTOR_IMPLEMENTATION",
    "TRANSITIVE_DEPENDENCY_MANIFEST",
    "ISAAC_RUNTIME",
    "IK_ALGORITHM",
    "JOINT_LIMIT_CONFIGURATION",
    "SWEPT_COLLISION_ALGORITHM",
    "ROBOT_ASSET",
    "CONTROLLER_CONFIGURATION",
    "SAFETY_CONFIGURATION",
    "SCENE_ASSET",
)


def _with_digest(cls: Any, **payload: Any):
    provisional = cls.model_construct(**payload, configuration_sha256="0" * 64)
    dumped = provisional.model_dump(mode="json")
    dumped["configuration_sha256"] = canonical_sha256(
        provisional.model_dump(mode="json", exclude={"configuration_sha256"})
    )
    return cls.model_validate(dumped)


def _configuration() -> ExactPlanPreflightConfigurationV1:
    ik = _with_digest(
        IKPreflightConfigurationV1,
        algorithm_id="ISAAC_LULA_QUERY_IK_V1",
        algorithm_sha256="1" * 64,
        robot_description_sha256="2" * 64,
        base_frame="world",
        end_effector_frame="panda_hand",
        maximum_position_residual_m=0.002,
        maximum_orientation_residual_rad=0.01,
        maximum_iterations_per_sample=64,
        timeout_ns_per_phase=1_000_000,
    )
    limits = _with_digest(
        JointLimitConfigurationV1,
        source_sha256="3" * 64,
        joint_names=("joint_a", "joint_b"),
        lower_position=(-2.0, -2.0),
        upper_position=(2.0, 2.0),
        maximum_velocity_per_s=(2.0, 2.0),
        maximum_abs_effort=(10.0, 10.0),
        effort_estimator_sha256="4" * 64,
    )
    gripper_limits = _with_digest(
        GripperLimitConfigurationV1,
        source_sha256="c" * 64,
        minimum_position_m=0.0,
        maximum_position_m=0.08,
        maximum_velocity_m_per_s=1.0,
        target_tolerance_m=0.001,
        timeout_ns_per_phase=1_000_000,
    )
    collision = _with_digest(
        SweptCollisionConfigurationV1,
        algorithm_id="ISAAC_LULA_SWEPT_QUERY_V1",
        algorithm_sha256="5" * 64,
        collision_geometry_sha256="6" * 64,
        robot_root_path="/World/Robot",
        subsamples_per_segment=4,
        timeout_ns_per_phase=1_000_000,
    )
    controller = _with_digest(
        ControllerPreflightConfigurationV1,
        controller_id="official_franka_dls",
        controller_configuration_sha256="7" * 64,
        readiness_timeout_ns=1_000_000,
    )
    safety = _with_digest(
        SafetyPreflightConfigurationV1,
        safety_configuration_sha256="8" * 64,
        workspace_min_world_m=(-1.0, -1.0, 0.0),
        workspace_max_world_m=(1.0, 1.0, 1.0),
        maximum_state_age_ns=100,
        contact_monitor_configuration_sha256="9" * 64,
        attachment_monitor_configuration_sha256="b" * 64,
    )
    attachment = _with_digest(
        AttachmentPreflightConfigurationV1,
        algorithm_id="ISAAC_ATTACHMENT_QUERY_V1",
        algorithm_sha256="d" * 64,
        contact_monitor_configuration_sha256=(safety.contact_monitor_configuration_sha256),
        attachment_monitor_configuration_sha256=(safety.attachment_monitor_configuration_sha256),
        timeout_ns_per_phase=1_000_000,
    )
    return _with_digest(
        ExactPlanPreflightConfigurationV1,
        ik=ik,
        joint_limits=limits,
        gripper_limits=gripper_limits,
        swept_collision=collision,
        controller=controller,
        safety=safety,
        attachment=attachment,
        callback_implementation_sha256="f" * 64,
        total_timeout_ns=10_000_000,
    )


def _deployment_configuration(callback_sha256: str) -> ExactPlanPreflightConfigurationV1:
    base = _configuration()
    ik_payload = base.ik.model_dump(mode="json", exclude={"configuration_sha256"})
    ik_payload.update(
        algorithm_sha256=hashlib.sha256(b"IK_ALGORITHM").hexdigest(),
        robot_description_sha256=hashlib.sha256(b"ROBOT_ASSET").hexdigest(),
    )
    ik = _with_digest(IKPreflightConfigurationV1, **ik_payload)
    collision_payload = base.swept_collision.model_dump(
        mode="json", exclude={"configuration_sha256"}
    )
    collision_payload["algorithm_sha256"] = hashlib.sha256(b"SWEPT_COLLISION_ALGORITHM").hexdigest()
    collision = _with_digest(SweptCollisionConfigurationV1, **collision_payload)
    payload = base.model_dump(mode="json", exclude={"configuration_sha256"})
    payload.update(
        ik=ik.model_dump(mode="json"),
        swept_collision=collision.model_dump(mode="json"),
        callback_implementation_sha256=callback_sha256,
    )
    payload["configuration_sha256"] = canonical_sha256(payload)
    return ExactPlanPreflightConfigurationV1.model_validate(payload)


def _gates() -> ExactExecutionPhaseGatesV2:
    return ExactExecutionPhaseGatesV2(
        ik_detail="query-only",
        joint_limits_detail="sampled at 60Hz",
        swept_collision_detail="continuous subsamples",
        controller_detail="ready/shape/rate",
        safety_detail="workspace/contact/attachment/stale state",
    )


def _pose(index: int, x: float) -> ExactExecutionPhaseV2:
    return ExactExecutionPhaseV2(
        phase_index=index,
        phase_name=f"MOVE_{index}",
        command="CARTESIAN_POSE",
        goal_position_world_m=(x, 0.0, 0.5),
        orientation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        steps=2,
        collision_phase=f"MOVE_{index}",
        allowed_robot_contact_paths=("/World/Robot/panda_hand",),
        allowed_external_contact_paths=("/World/M1B/carried/link",),
        gates=_gates(),
    )


def _gripper(index: int, target_m: float = 0.04) -> ExactExecutionPhaseV2:
    return ExactExecutionPhaseV2(
        phase_index=index,
        phase_name=f"GRIPPER_{index}",
        command="GRIPPER_POSITION",
        gripper_position_m=target_m,
        steps=2,
        collision_phase=f"GRIPPER_{index}",
        gates=_gates(),
    )


def _attachment_phase(index: int, command: str) -> ExactExecutionPhaseV2:
    attaching = command == "ATTACH_CONTACT_ENTITY"
    return ExactExecutionPhaseV2(
        phase_index=index,
        phase_name=f"{'ATTACH' if attaching else 'REMOVE'}_{index}",
        command=command,
        steps=0,
        collision_phase=f"{'ATTACH' if attaching else 'REMOVE'}_{index}",
        allowed_robot_contact_paths=(
            "/World/Robot/left_finger",
            "/World/Robot/right_finger",
        ),
        allowed_external_contact_paths=("/World/M1B/blocker/link",),
        contact_entity_selection=(
            "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST" if attaching else "NONE"
        ),
        gates=_gates(),
    )


def _contract(phase: ExactExecutionPhaseV2) -> ExactPlanPhaseContractV1:
    selector = {
        "ATTACH_CONTACT_ENTITY": ("TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"),
        "REMOVE_ATTACHMENT": "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT",
    }.get(phase.command, "NONE")
    return ExactPlanPhaseContractV1(
        phase=phase,
        phase_sha256=canonical_sha256(phase),
        command_rate_hz=60.0,
        command_dimensions=COMMANDS[phase.command],
        interpolation_rule=(
            "LINEAR_FIXED_STEPS"
            if phase.command
            in {
                "CARTESIAN_POSE",
                "GRIPPER_POSITION",
                "ATTACH_CONTACT_ENTITY",
                "REMOVE_ATTACHMENT",
            }
            else "NONE"
        ),
        convergence_tolerance_m=0.002,
        timeout_ns=500_000,
        allowed_robot_links_sha256=canonical_sha256(phase.allowed_robot_contact_paths),
        allowed_environment_paths_sha256=canonical_sha256(()),
        allowed_external_contact_paths_sha256=canonical_sha256(
            phase.allowed_external_contact_paths
        ),
        attachment_or_removal_selector=selector,
    )


def _plan(
    tmp_path: Path,
    *,
    configuration: ExactPlanPreflightConfigurationV1,
    phases: tuple[ExactExecutionPhaseV2, ...] | None = None,
    canonical_skill: str = "MOVE",
    grasp_geometry: ExactGraspGeometryV1 | None = None,
) -> M2CExactPlanPrimitivePlanV1:
    phases = phases or (_pose(0, 0.1), _pose(1, 0.12))
    first_phase = phases[0]
    preplan_state_sha256 = canonical_non_actuating_state_sha256(
        {
            "joint_positions": (0.0, 0.0),
            "end_effector_world_m": (
                first_phase.goal_position_world_m
                if first_phase.goal_position_world_m is not None
                else (0.1, 0.0, 0.5)
            ),
            "end_effector_world_wxyz": (
                first_phase.orientation_world_wxyz
                if first_phase.orientation_world_wxyz is not None
                else (1.0, 0.0, 0.0, 0.0)
            ),
            "gripper_position_m": 0.04,
        }
    )
    wire = ExactExecutionPlanV2(
        run_id="run",
        session_id="session",
        decision_index=2,
        observation_id="obs",
        capture_receipt_sha256="c" * 64,
        canonical_skill=canonical_skill,
        runtime_action="B0_PUBLIC_GEOMETRY_MOVE",
        execution_parameters_sha256="d" * 64,
        target_track_id="track-blocker",
        phases=phases,
    )
    bindings = []
    bound_role_digests = {
        "PREFLIGHT_IMPLEMENTATION": hashlib.sha256(
            (
                Path(__file__).parents[2]
                / "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py"
            ).read_bytes()
        ).hexdigest(),
        "IK_ALGORITHM": configuration.ik.algorithm_sha256,
        "ROBOT_ASSET": configuration.ik.robot_description_sha256,
        "JOINT_LIMIT_CONFIGURATION": configuration.joint_limits.configuration_sha256,
        "SWEPT_COLLISION_ALGORITHM": configuration.swept_collision.algorithm_sha256,
        "CONTROLLER_CONFIGURATION": configuration.controller.configuration_sha256,
        "SAFETY_CONFIGURATION": configuration.safety.configuration_sha256,
    }
    for index, role in enumerate(ROLES):
        path = tmp_path / f"source-{index}"
        expected_digest = bound_role_digests.get(role)
        raw = role.encode()
        path.write_bytes(raw)
        bindings.append(
            ExactPlanSourceBindingV1(
                role=role,
                path=str(path),
                # ExactPlanSourceBinding is an audit declaration; the bundle's
                # deployment check later resolves each real source path.  This
                # focused preflight test binds only the relevant role digest.
                sha256=expected_digest or hashlib.sha256(raw).hexdigest(),
            )
        )
    contracts = tuple(_contract(item) for item in phases)
    schema_projection = tuple(
        {
            "phase_index": item.phase.phase_index,
            "phase_name": item.phase.phase_name,
            "command": item.phase.command,
            "phase_sha256": item.phase_sha256,
            "command_rate_hz": item.command_rate_hz,
            "command_dimensions": item.command_dimensions,
            "interpolation_rule": item.interpolation_rule,
            "timeout_ns": item.timeout_ns,
            "permitted_retry_count": item.permitted_retry_count,
            "attachment_or_removal_selector": item.attachment_or_removal_selector,
            "freshness_transition": item.freshness_transition,
        }
        for item in contracts
    )
    payload = {
        "schema_version": "M2CExactPlanPrimitivePlanV1",
        "bundle_name": "M2CExactPlanPrimitiveBundleV1",
        "exact_execution_plan": wire,
        "exact_execution_plan_sha256": canonical_sha256(wire),
        "inputs": ExactPlanA1InputsV1(
            run_id=wire.run_id,
            session_id=wire.session_id,
            decision_index=wire.decision_index,
            observation_id=wire.observation_id,
            capture_receipt_sha256=wire.capture_receipt_sha256,
            rgb_sha256="e" * 64,
            depth_sha256="f" * 64,
            canonical_public_tracks_sha256="1" * 64,
            signed_model_inference_response_sha256="2" * 64,
            runtime_mapping_sha256="3" * 64,
            canonical_skill=wire.canonical_skill,
            runtime_action=wire.runtime_action,
            target_track_id=wire.target_track_id,
            resolved_execution_parameters_sha256=wire.execution_parameters_sha256,
            preplan_state_sha256=preplan_state_sha256,
            preplan_state_dimensions=2,
            preplan_state_units="rad",
            preplan_state_timestamp_ns=100,
            preplan_state_freshness_limit_ns=100,
            plan_constructed_at_ns=105,
            controller_frequency_hz=60.0,
            command_dimensions=7,
            convergence_tolerance_m=0.002,
            immutable_commit="5" * 40,
            container_image_digest="sha256:" + "6" * 64,
        ),
        "source_bindings": tuple(bindings),
        "phases": contracts,
        "grasp_geometry": grasp_geometry,
        "phase_schema_sha256": canonical_sha256(schema_projection),
    }
    provisional = M2CExactPlanPrimitivePlanV1.model_construct(
        **payload,
        bound_plan_sha256="0" * 64,
    )
    dumped = provisional.model_dump(mode="json")
    dumped["bound_plan_sha256"] = canonical_sha256(provisional.semantic_payload())
    return M2CExactPlanPrimitivePlanV1.model_validate(dumped)


def _receipt(model: Any, field: str):
    dumped = model.model_dump(mode="json")
    dumped[field] = canonical_sha256(model.model_dump(mode="json", exclude={field}))
    return type(model).model_validate(dumped)


def _rehash_dict(payload: dict[str, Any], field: str) -> None:
    payload[field] = canonical_sha256(
        {key: value for key, value in payload.items() if key != field}
    )


def _rehash_a3_phase(
    receipt: Any,
    dumped: dict[str, Any],
    phase_index: int,
):
    phase = dumped["phase_audit_evidence"][phase_index]
    path = phase["path"]
    _rehash_dict(path, "path_sha256")
    phase["swept_collision"]["path_sha256"] = path["path_sha256"]
    _rehash_dict(phase["swept_collision"], "receipt_sha256")
    phase["attachment_transition"]["path_sha256"] = path["path_sha256"]
    _rehash_dict(phase["attachment_transition"], "receipt_sha256")
    _rehash_dict(phase, "evidence_sha256")
    _rehash_dict(dumped, "receipt_sha256")
    return type(receipt).model_validate(dumped)


def _grasp_plan(
    tmp_path: Path,
    *,
    configuration: ExactPlanPreflightConfigurationV1,
) -> M2CExactPlanPrimitivePlanV1:
    phases = (
        _pose(0, 0.08),
        _pose(1, 0.10),
        _gripper(2, 0.02),
        _attachment_phase(3, "ATTACH_CONTACT_ENTITY"),
        _pose(4, 0.10),
        _pose(5, 0.08),
    )
    geometry = ExactGraspGeometryV1(
        selected_yaw_rad=0.0,
        contact_centerline_m=0.01,
        finger_target_m=0.02,
        approach_phase_index=0,
        contact_phase_indices=(1,),
        close_phase_index=2,
        attach_phase_index=3,
        lift_phase_index=4,
        retreat_phase_index=5,
        contact_allowlist_sha256=canonical_sha256(phases[3].allowed_external_contact_paths),
    )
    return _plan(
        tmp_path,
        configuration=configuration,
        phases=phases,
        canonical_skill="GRASP",
        grasp_geometry=geometry,
    )


class _Callbacks:
    non_actuating: Literal[True] = True

    def __init__(self, config: ExactPlanPreflightConfigurationV1) -> None:
        self.implementation_sha256 = "f" * 64
        self.ik_algorithm_sha256 = config.ik.algorithm_sha256
        self.swept_collision_algorithm_sha256 = config.swept_collision.algorithm_sha256
        self.attachment_algorithm_sha256 = config.attachment.algorithm_sha256
        self.config = config
        self.path_calls: list[int] = []
        self.collision_calls: list[int] = []
        self.fail_phase: int | None = None
        self.position_violation = False
        self.velocity_violation = False
        self.effort_violation = False
        self.workspace_violation = False
        self.collision_violation = False
        self.missing_sample = False
        self.stale = False
        self.controller_ready = True
        self.controller_readiness_timeout = False
        self.terminal_pose_mismatch = False
        self.gripper_target_mismatch = False
        self.gripper_velocity_violation = False
        self.gripper_position_violation = False
        self.missing_bilateral_pair = False
        self.wrong_bilateral_contact = False
        self.wrong_attachment_transition = False
        self.wrong_existing_attachment = False
        self.fail_attachment_phase: int | None = None
        self.attachment_calls: list[int] = []
        self.initial_attachment_override: bool | None = None
        self.last_terminal_sample: NonActuatingJointSampleV1 | None = None
        self.path_timeout = False
        self.collision_timeout = False
        self.attachment_timeout = False

    def snapshot_runtime(self, plan: M2CExactPlanPrimitivePlanV1):
        model = PreflightRuntimeSnapshotV1.model_construct(
            bound_plan_sha256=plan.bound_plan_sha256,
            preplan_state_sha256=plan.inputs.preplan_state_sha256,
            observed_at_ns=plan.inputs.preplan_state_timestamp_ns,
            checked_at_ns=150,
            controller_id=self.config.controller.controller_id,
            controller_configuration_sha256=(
                self.config.controller.controller_configuration_sha256
            ),
            controller_ready=self.controller_ready,
            controller_readiness_query_duration_ns=(
                self.config.controller.readiness_timeout_ns + 1
                if self.controller_readiness_timeout
                else 10
            ),
            controller_rate_hz=60.0,
            command_shapes=tuple(
                ControllerCommandShapeV1(command=name, dimensions=width)
                for name, width in COMMANDS.items()
            ),
            collision_world_ready=True,
            contact_monitor_ready=True,
            attachment_monitor_ready=True,
            terminal_bilateral_contact_broker_ready=True,
            active_attachment_present=(
                True
                if self.initial_attachment_override is None
                else self.initial_attachment_override
            ),
            active_attachment_sha256=(
                "a" * 64
                if (
                    True
                    if self.initial_attachment_override is None
                    else self.initial_attachment_override
                )
                else None
            ),
            emergency_stop_active=False,
            state_stale=self.stale,
            query_only=True,
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            teacher_used=False,
            privileged_truth_policy_input=False,
            snapshot_sha256="0" * 64,
        )
        return _receipt(model, "snapshot_sha256")

    def solve_phase_path(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        *,
        start_state_sha256: str,
        configuration: ExactPlanPreflightConfigurationV1,
    ):
        index = phase.phase.phase_index
        self.path_calls.append(index)
        if self.fail_phase == index:
            raise RuntimeError("query failed")
        wire = phase.phase
        sample_count = (
            wire.steps + 1
            if wire.command
            in {
                "CARTESIAN_POSE",
                "GRIPPER_POSITION",
            }
            else 1
        )
        samples = []
        phase_start = self.last_terminal_sample
        for sample_index in range(sample_count):
            joint_a = (
                phase_start.joint_positions[0] + 0.01 * sample_index
                if phase_start is not None
                else 0.01 * sample_index
            )
            if self.velocity_violation and index == 0 and sample_index == 1:
                joint_a = 1.0
            if self.position_violation and index == 0 and sample_index == 1:
                joint_a = 3.0
            effort = 11.0 if self.effort_violation and index == 0 else 1.0
            x = (
                2.0
                if self.workspace_violation and index == 0 and sample_index == 1
                else float(wire.goal_position_world_m[0])
                if wire.goal_position_world_m is not None
                else 0.1
            )
            if self.terminal_pose_mismatch and index == 0 and sample_index == sample_count - 1:
                x += 0.1
            start_gripper_position_m = (
                phase_start.gripper_position_m if phase_start is not None else 0.04
            )
            gripper_position_m = start_gripper_position_m
            if wire.command == "GRIPPER_POSITION":
                assert wire.gripper_position_m is not None
                gripper_position_m = start_gripper_position_m + (
                    wire.gripper_position_m - start_gripper_position_m
                ) * (sample_index / (sample_count - 1))
                if self.gripper_velocity_violation and sample_index == 1:
                    gripper_position_m = 0.08
                if self.gripper_position_violation and sample_index == 1:
                    gripper_position_m = 0.09
                if self.gripper_target_mismatch and sample_index == sample_count - 1:
                    gripper_position_m += 0.005
            cartesian = wire.command == "CARTESIAN_POSE"
            sample = NonActuatingJointSampleV1.model_construct(
                sample_index=sample_index,
                joint_positions=(joint_a, 0.0),
                estimated_abs_efforts=(effort, 1.0),
                end_effector_world_m=(x, 0.0, 0.5),
                end_effector_world_wxyz=(1.0, 0.0, 0.0, 0.0),
                gripper_position_m=gripper_position_m,
                ik_applicable=cartesian,
                ik_converged=cartesian,
                ik_position_residual_m=0.001 if cartesian else 0.0,
                ik_orientation_residual_rad=0.001 if cartesian else 0.0,
                iterations=3 if cartesian else 0,
                state_sha256="0" * 64,
            )
            sample = sample.model_copy(
                update={"state_sha256": canonical_non_actuating_state_sha256(sample)}
            )
            samples.append(sample)
        if phase_start is not None:
            samples[0] = samples[0].model_copy(
                update={
                    "joint_positions": phase_start.joint_positions,
                    "end_effector_world_m": phase_start.end_effector_world_m,
                    "end_effector_world_wxyz": phase_start.end_effector_world_wxyz,
                    "gripper_position_m": phase_start.gripper_position_m,
                }
            )
            samples[0] = samples[0].model_copy(
                update={"state_sha256": canonical_non_actuating_state_sha256(samples[0])}
            )
        if self.missing_sample and index == 0:
            samples.pop()
        self.last_terminal_sample = samples[-1]
        model = NonActuatingPhasePathV1.model_construct(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=index,
            phase_sha256=phase.phase_sha256,
            start_state_sha256=start_state_sha256,
            terminal_state_sha256=samples[-1].state_sha256,
            joint_names=configuration.joint_limits.joint_names,
            sample_rate_hz=60.0,
            samples=tuple(samples),
            ik_algorithm_sha256=configuration.ik.algorithm_sha256,
            ik_configuration_sha256=configuration.ik.configuration_sha256,
            joint_limit_configuration_sha256=(configuration.joint_limits.configuration_sha256),
            gripper_limit_configuration_sha256=(configuration.gripper_limits.configuration_sha256),
            effort_estimator_sha256=configuration.joint_limits.effort_estimator_sha256,
            query_duration_ns=(phase.timeout_ns + 1 if self.path_timeout else 100),
            query_only=True,
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            teacher_used=False,
            privileged_truth_policy_input=False,
            path_sha256="0" * 64,
        )
        return _receipt(model, "path_sha256")

    def check_swept_collision(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
    ):
        index = phase.phase.phase_index
        self.collision_calls.append(index)
        pairs: tuple[SweptCollisionPairV1, ...] = ()
        if self.collision_violation and index == 0:
            pairs = (
                SweptCollisionPairV1(
                    path0="/World/Robot/panda_hand",
                    path1="/World/Unsafe/wall",
                ),
            )
        segments = tuple(
            SweptCollisionSegmentV1(
                segment_index=segment,
                subsamples_checked=configuration.swept_collision.subsamples_per_segment,
                collision_pairs=pairs if segment == 0 else (),
            )
            for segment in range(phase.phase.steps)
        )
        model = NonActuatingSweptCollisionV1.model_construct(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=index,
            phase_sha256=phase.phase_sha256,
            path_sha256=path.path_sha256,
            algorithm_sha256=configuration.swept_collision.algorithm_sha256,
            configuration_sha256=configuration.swept_collision.configuration_sha256,
            segments=segments,
            query_duration_ns=(phase.timeout_ns + 1 if self.collision_timeout else 100),
            query_only=True,
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            teacher_used=False,
            privileged_truth_policy_input=False,
            receipt_sha256="0" * 64,
        )
        return _receipt(model, "receipt_sha256")

    def check_attachment_transition(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        expected_attachment_present: bool,
        expected_attachment_sha256: str | None,
        configuration: ExactPlanPreflightConfigurationV1,
    ):
        index = phase.phase.phase_index
        self.attachment_calls.append(index)
        if self.fail_attachment_phase == index:
            raise RuntimeError("attachment query failed")
        command = phase.phase.command
        transition = {
            "ATTACH_CONTACT_ENTITY": "ATTACH",
            "REMOVE_ATTACHMENT": "REMOVE",
        }.get(command, "NONE")
        if self.wrong_attachment_transition and command == "ATTACH_CONTACT_ENTITY":
            transition = "NONE"
        pairs: tuple[PlannedBilateralContactPairV1, ...] = ()
        after_present = expected_attachment_present
        after_sha = expected_attachment_sha256
        if command == "ATTACH_CONTACT_ENTITY":
            after_present = True
            after_sha = "e" * 64
            if not self.missing_bilateral_pair:
                pairs = (
                    PlannedBilateralContactPairV1(
                        left_robot_path="/World/Robot/left_finger",
                        right_robot_path="/World/Robot/right_finger",
                        external_path=(
                            "/World/Unsafe/wall"
                            if self.wrong_bilateral_contact
                            else "/World/M1B/blocker/link"
                        ),
                    ),
                )
        elif command == "REMOVE_ATTACHMENT":
            after_present = False
            after_sha = None
        model = NonActuatingAttachmentTransitionV1.model_construct(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=index,
            phase_sha256=phase.phase_sha256,
            path_sha256=path.path_sha256,
            command=command,
            transition=transition,
            attachment_or_removal_selector=phase.attachment_or_removal_selector,
            allowed_robot_contact_paths=phase.phase.allowed_robot_contact_paths,
            allowed_external_contact_paths=phase.phase.allowed_external_contact_paths,
            bilateral_contact_pairs=pairs,
            attachment_present_before=expected_attachment_present,
            attachment_sha256_before=(
                "f" * 64
                if self.wrong_existing_attachment and command == "REMOVE_ATTACHMENT"
                else expected_attachment_sha256
            ),
            attachment_present_after=after_present,
            attachment_sha256_after=after_sha,
            complete=True,
            algorithm_sha256=configuration.attachment.algorithm_sha256,
            configuration_sha256=configuration.attachment.configuration_sha256,
            query_duration_ns=(phase.timeout_ns + 1 if self.attachment_timeout else 100),
            query_only=True,
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            teacher_used=False,
            privileged_truth_policy_input=False,
            receipt_sha256="0" * 64,
        )
        return _receipt(model, "receipt_sha256")


def test_all_phases_pass_before_receipt_and_bundle_phase_adapter_is_cached(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)

    receipt = preflight.preflight_plan(plan)

    assert len(receipt.standard_preflight_receipt.phase_results) == 2
    assert receipt.formal_execution_eligible is False
    assert receipt.configuration_receipt.binding_addendum_required is True
    assert receipt.configuration_receipt.ik_complete_configuration_sha256 == (
        config.ik.configuration_sha256
    )
    assert receipt.configuration_receipt.collision_geometry_sha256 == (
        config.swept_collision.collision_geometry_sha256
    )
    assert receipt.configuration_receipt.ik_robot_description_sha256 == (
        config.ik.robot_description_sha256
    )
    assert receipt.configuration_receipt.gripper_limit_configuration_sha256 == (
        config.gripper_limits.configuration_sha256
    )
    assert receipt.configuration_receipt.attachment_complete_configuration_sha256 == (
        config.attachment.configuration_sha256
    )
    assert receipt.configuration_receipt.complete_preflight_configuration == config
    assert receipt.runtime_snapshot.bound_plan_sha256 == plan.bound_plan_sha256
    assert len(receipt.phase_audit_evidence) == 2
    assert all(
        item.attachment_transition.query_only
        and item.attachment_transition.articulation_target_writes == 0
        and item.attachment_transition.simulation_steps == 0
        and item.attachment_transition.scene_mutations == 0
        and item.swept_collision.path_sha256 == item.path.path_sha256
        for item in receipt.phase_audit_evidence
    )
    assert callbacks.path_calls == [0, 1]
    assert callbacks.collision_calls == [0, 1]
    assert callbacks.attachment_calls == [0, 1]
    with pytest.raises(ExactPlanPreflightRejected, match="not bound"):
        preflight.verify_phase(plan, plan.phases[0])
    assert callbacks.path_calls == [0, 1]


def test_aggregate_phase_evidence_single_field_tamper_is_rejected(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    dumped = receipt.model_dump(mode="json")
    dumped["phase_audit_evidence"][0]["path"]["query_duration_ns"] += 1

    with pytest.raises(ValueError, match="path digest differs"):
        type(receipt).model_validate(dumped)


def test_aggregate_phase_evidence_schema_tamper_is_rejected(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    dumped = receipt.model_dump(mode="json")
    dumped["phase_audit_evidence"][0]["schema_version"] = "UNREVIEWED_SCHEMA"

    with pytest.raises(ValueError, match="ExactPlanA3PhaseAuditEvidenceV1"):
        type(receipt).model_validate(dumped)


def test_sample_state_digest_is_recomputed_from_physical_state() -> None:
    sample = NonActuatingJointSampleV1.model_construct(
        sample_index=0,
        joint_positions=(0.0, 0.0),
        estimated_abs_efforts=(0.0, 0.0),
        end_effector_world_m=(0.1, 0.0, 0.5),
        end_effector_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        gripper_position_m=0.04,
        ik_applicable=True,
        ik_converged=True,
        ik_position_residual_m=0.0,
        ik_orientation_residual_rad=0.0,
        iterations=1,
        state_sha256="0" * 64,
    )
    dumped = sample.model_dump(mode="json")
    dumped["state_sha256"] = canonical_non_actuating_state_sha256(dumped)
    canonical = NonActuatingJointSampleV1.model_validate(dumped)
    tampered = canonical.model_dump(mode="json")
    tampered["gripper_position_m"] = 0.03

    with pytest.raises(ValueError, match="state digest differs"):
        NonActuatingJointSampleV1.model_validate(tampered)


def test_strict_offline_replay_rejects_rehashed_joint_limit_tamper(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    assert strict_replay_a3_audit_receipt_v1(plan, receipt) == receipt
    dumped = receipt.model_dump(mode="json")
    sample = dumped["phase_audit_evidence"][0]["path"]["samples"][1]
    sample["joint_positions"][0] = 3.0
    sample["state_sha256"] = canonical_non_actuating_state_sha256(sample)
    tampered = _rehash_a3_phase(receipt, dumped, 0)

    with pytest.raises(ExactPlanPreflightRejected, match="joint position limit"):
        strict_replay_a3_audit_receipt_v1(plan, tampered)


def test_strict_offline_replay_rejects_rehashed_collision_tamper(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    dumped = receipt.model_dump(mode="json")
    dumped["phase_audit_evidence"][0]["swept_collision"]["segments"][0]["collision_pairs"] = [
        {"path0": "/World/Robot/panda_hand", "path1": "/World/Unsafe/wall"}
    ]
    tampered = _rehash_a3_phase(receipt, dumped, 0)

    with pytest.raises(ExactPlanPreflightRejected, match="outside frozen phase allowlists"):
        strict_replay_a3_audit_receipt_v1(plan, tampered)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("controller_ready", "controller readiness"),
        ("collision_world_ready", "safety/contact/attachment monitor"),
    ],
)
def test_strict_offline_replay_rejects_rehashed_runtime_gate_tamper(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    dumped = receipt.model_dump(mode="json")
    dumped["runtime_snapshot"][field] = False
    _rehash_dict(dumped["runtime_snapshot"], "snapshot_sha256")
    _rehash_dict(dumped, "receipt_sha256")
    tampered = type(receipt).model_validate(dumped)

    with pytest.raises(ExactPlanPreflightRejected, match=message):
        strict_replay_a3_audit_receipt_v1(plan, tampered)


def test_strict_offline_replay_rejects_rehashed_attachment_transition(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config, phases=(_pose(0, 0.1),))
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    dumped = receipt.model_dump(mode="json")
    transition = dumped["phase_audit_evidence"][0]["attachment_transition"]
    transition["attachment_present_after"] = False
    transition["attachment_sha256_after"] = None
    tampered = _rehash_a3_phase(receipt, dumped, 0)

    with pytest.raises(ExactPlanPreflightRejected, match="changes attachment"):
        strict_replay_a3_audit_receipt_v1(plan, tampered)


@pytest.mark.parametrize(
    "failure",
    ["path_timeout", "collision_timeout", "attachment_timeout"],
)
def test_each_query_is_bounded_by_phase_and_configuration_timeout(
    tmp_path: Path,
    failure: str,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    setattr(callbacks, failure, True)

    with pytest.raises(ExactPlanPreflightRejected):
        ExactPlanPreflightV1(configuration=config, callbacks=callbacks).preflight_plan(plan)


def test_allowlist_digests_are_recomputed_before_callbacks(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    tampered_phase = plan.phases[0].model_copy(update={"allowed_robot_links_sha256": "0" * 64})
    provisional = plan.model_copy(update={"phases": (tampered_phase, *plan.phases[1:])})
    dumped = provisional.model_dump(mode="json")
    dumped["bound_plan_sha256"] = canonical_sha256(provisional.semantic_payload())
    tampered = M2CExactPlanPrimitivePlanV1.model_validate(dumped)
    callbacks = _Callbacks(config)

    with pytest.raises(ExactPlanPreflightRejected, match="allowlist digest"):
        ExactPlanPreflightV1(configuration=config, callbacks=callbacks).preflight_plan(tampered)
    assert callbacks.path_calls == []


def test_legacy_formal_execution_authorization_is_superseded(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    receipt = ExactPlanPreflightV1(
        configuration=config,
        callbacks=_Callbacks(config),
    ).preflight_plan(plan)
    with pytest.raises(ExactPlanPreflightRejected, match="superseded by ADR-0024"):
        require_formal_a3_execution_authorization(
            receipt,
            host_verifier_receipt=None,
        )
    payload = {
        "schema_version": "HostSignedAppendOnlyA3VerifierReceiptV1",
        "bound_plan_sha256": plan.bound_plan_sha256,
        "a3_audit_receipt_sha256": receipt.receipt_sha256,
        "run_id": plan.inputs.run_id,
        "session_id": plan.inputs.session_id,
        "challenge_nonce": "n" * 32,
        "append_only_audit_sha256": "a" * 64,
        "verifier_key_id": "unbound-test-key",
        "signature_algorithm": "ED25519",
        "signature_base64": "not-a-real-signature",
        "verified_against_frozen_allowed_signer": True,
        "append_only_lifecycle_verified": True,
        "all_gate_evidence_precedes_execution_start": True,
    }
    host_receipt = HostSignedAppendOnlyA3VerifierReceiptV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )
    with pytest.raises(ExactPlanPreflightRejected, match="superseded by ADR-0024"):
        require_formal_a3_execution_authorization(
            receipt,
            host_verifier_receipt=host_receipt,
        )


def test_v2_deployment_binding_has_no_signature_or_launcher_fields() -> None:
    schema = ExactPlanA3DeploymentBindingV2.model_json_schema()

    assert "signature_armored" not in schema["properties"]
    assert "signer_principal" not in schema["properties"]
    assert "public_trust_root_sha256" not in schema["properties"]
    assert schema["properties"]["trusted_host_signature_required"]["const"] is False
    assert schema["properties"]["launcher_attestation_required"]["const"] is False
    assert schema["properties"]["session_bound_execution_receipt_required"]["const"] is True
    assert schema["properties"]["host_hmac_post_execution_replay_required"]["const"] is True


def test_v2_deployment_binding_is_checked_before_query_callbacks(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    payload = {
        "schema_version": "ExactPlanA3DeploymentBindingV2",
        "status": "ACCEPTED_PHASE2_BINDING_ADDENDUM",
        "accepted_adr_sha256": ("62c14028df1ad91e4d3c4282c4775e33149292e9bcf10add2d505be8c7424689"),
        "binding_addendum_sha256": "1" * 64,
        "unlock_config_sha256": "2" * 64,
        "immutable_commit": "3" * 40,
        "container_image_digest": "sha256:" + "4" * 64,
        "preflight_implementation_path": (
            "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py"
        ),
        "preflight_implementation_sha256": "5" * 64,
        "callback_implementation_path": "src/callback.py",
        "callback_implementation_sha256": callbacks.implementation_sha256,
        "complete_preflight_configuration_sha256": config.configuration_sha256,
        "plan_source_bindings_sha256": canonical_sha256(plan.source_bindings),
        "phase_schema_by_skill": tuple(
            (skill, plan.phase_schema_sha256)
            for skill in (
                "GRASP",
                "LIFT",
                "MOVE",
                "PLACE",
                "RELEASE",
                "REOBSERVE",
                "REASSOCIATE_TARGET",
                "REGRASP",
            )
        ),
        "session_audit_implementation_sha256": "6" * 64,
        "host_hmac_verifier_sha256": "7" * 64,
        "entry_gate_sha256": "8" * 64,
        "formal_physical_runner_binding": ("src/formal_runner.py", "9" * 64),
        "formal_deployment_closure_binding": (
            "3" * 40,
            "sha256:" + "4" * 64,
            "a" * 64,
        ),
        "frozen_b0_runtime_wrapper_binding": None,
        "offline_wire_authentication_verifier_binding": None,
        "reviewed_addendum_accepted": True,
        "immutable_git_tree_required": True,
        "session_bound_execution_receipt_required": True,
        "host_hmac_post_execution_replay_required": True,
        "trusted_host_signature_required": False,
        "launcher_attestation_required": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    binding = _receipt(
        ExactPlanA3DeploymentBindingV2.model_construct(
            **payload,
            binding_sha256="0" * 64,
        ),
        "binding_sha256",
    )
    preflight = ExactPlanPreflightV1(
        configuration=config,
        callbacks=callbacks,
        project_root=tmp_path,
        deployment_binding=binding,
    )

    with pytest.raises(ExactPlanPreflightRejected, match="Git binding is unavailable"):
        preflight.preflight_plan(plan)

    assert callbacks.path_calls == []
    assert callbacks.collision_calls == []
    assert callbacks.attachment_calls == []


def test_v2_deployment_binding_replays_all_phases_before_authorizing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "m2c-test@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "M2C Test"], cwd=root, check=True)
    callback_path = "src/callback.py"
    callback_raw = b"query-only callback\n"
    callback_sha = hashlib.sha256(callback_raw).hexdigest()
    runner_path = "src/formal_runner.py"
    runner_raw = b"formal runner\n"
    runner_sha = hashlib.sha256(runner_raw).hexdigest()
    config = _deployment_configuration(callback_sha)

    source_bindings = {
        "PRIMITIVE_ENTRYPOINT": b"PRIMITIVE_ENTRYPOINT",
        "PREFLIGHT_IMPLEMENTATION": (
            Path(__file__).parents[2] / "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py"
        ).read_bytes(),
        "EXECUTOR_IMPLEMENTATION": b"EXECUTOR_IMPLEMENTATION",
        "TRANSITIVE_DEPENDENCY_MANIFEST": b"TRANSITIVE_DEPENDENCY_MANIFEST",
        "ISAAC_RUNTIME": b"ISAAC_RUNTIME",
        "IK_ALGORITHM": b"IK_ALGORITHM",
        "JOINT_LIMIT_CONFIGURATION": canonical_json_bytes(
            config.joint_limits.model_dump(mode="json", exclude={"configuration_sha256"})
        ),
        "SWEPT_COLLISION_ALGORITHM": b"SWEPT_COLLISION_ALGORITHM",
        "ROBOT_ASSET": b"ROBOT_ASSET",
        "CONTROLLER_CONFIGURATION": canonical_json_bytes(
            config.controller.model_dump(mode="json", exclude={"configuration_sha256"})
        ),
        "SAFETY_CONFIGURATION": canonical_json_bytes(
            config.safety.model_dump(mode="json", exclude={"configuration_sha256"})
        ),
        "SCENE_ASSET": b"SCENE_ASSET",
    }
    binding_paths: list[tuple[str, str]] = []
    for index, role in enumerate(ROLES):
        relative = f"bindings/source-{index}"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source_bindings[role])
        binding_paths.append((relative, hashlib.sha256(source_bindings[role]).hexdigest()))

    plan = _plan(root, configuration=config)
    plan_raw = plan.model_dump(mode="json")
    for item, (relative, digest) in zip(plan_raw["source_bindings"], binding_paths, strict=True):
        item["path"] = relative
        item["sha256"] = digest
    plan_raw["inputs"]["immutable_commit"] = "0" * 40
    plan_raw["bound_plan_sha256"] = canonical_sha256(
        {key: value for key, value in plan_raw.items() if key != "bound_plan_sha256"}
    )
    plan = M2CExactPlanPrimitivePlanV1.model_validate(plan_raw)

    project_files = {
        "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md": (
            Path(__file__).parents[2] / "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"
        ).read_bytes(),
        "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py": source_bindings[
            "PREFLIGHT_IMPLEMENTATION"
        ],
        callback_path: callback_raw,
        "src/xh_agent/policy/qrm_lite/formal_isaac_endpoint_v2.py": b"session audit\n",
        "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py": b"hmac verifier\n",
        runner_path: runner_raw,
    }
    for relative, raw in project_files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "implementation"], cwd=root, check=True)
    implementation_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()

    plan_raw = plan.model_dump(mode="json")
    plan_raw["inputs"]["immutable_commit"] = implementation_commit
    plan_raw["bound_plan_sha256"] = canonical_sha256(
        {key: value for key, value in plan_raw.items() if key != "bound_plan_sha256"}
    )
    plan = M2CExactPlanPrimitivePlanV1.model_validate(plan_raw)
    addendum = root / "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"
    unlock = root / "configs/m2c_s4_unlock_bindings.json"
    addendum.write_bytes(b"accepted binding addendum\n")
    addendum_sha = hashlib.sha256(addendum.read_bytes()).hexdigest()
    transitive_sha = dict((source.role, source.sha256) for source in plan.source_bindings)[
        "TRANSITIVE_DEPENDENCY_MANIFEST"
    ]
    runner_binding = (runner_path, runner_sha)
    closure_binding = (
        implementation_commit,
        plan.inputs.container_image_digest,
        transitive_sha,
    )
    entry = root / "src/xh_agent/policy/qrm_lite/s4_entry_gate.py"
    entry.write_text(
        "FORMAL_PHYSICAL_RUNNER_BINDING = " + repr(runner_binding) + "\n"
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING = " + repr(closure_binding) + "\n"
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING = None\n"
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None\n"
    )
    entry_sha = hashlib.sha256(entry.read_bytes()).hexdigest()
    unlock.parent.mkdir(parents=True, exist_ok=True)
    unlock_payload = {
        "schema_version": "M2CS4UnlockBindingV2",
        "status": "APPLIED_TO_REVIEWED_SOURCE",
        "adr_path": "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md",
        "binding_addendum_path": "docs/decisions/ADR-0022-BINDING-ADDENDUM.md",
        "binding_addendum_sha256": addendum_sha,
        "FORMAL_PHYSICAL_RUNNER_BINDING": list(runner_binding),
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING": list(closure_binding),
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING": None,
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING": None,
        "applied_to_source": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    unlock.write_bytes(canonical_json_bytes(unlock_payload))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "reviewed binding"], cwd=root, check=True)

    callbacks = _Callbacks(config)
    callbacks.implementation_sha256 = callback_sha
    callbacks.implementation_path = callback_path
    binding_payload = {
        "schema_version": "ExactPlanA3DeploymentBindingV2",
        "status": "ACCEPTED_PHASE2_BINDING_ADDENDUM",
        "accepted_adr_sha256": hashlib.sha256(
            project_files["docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"]
        ).hexdigest(),
        "binding_addendum_sha256": addendum_sha,
        "unlock_config_sha256": hashlib.sha256(unlock.read_bytes()).hexdigest(),
        "immutable_commit": implementation_commit,
        "container_image_digest": plan.inputs.container_image_digest,
        "preflight_implementation_path": (
            "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py"
        ),
        "preflight_implementation_sha256": hashlib.sha256(
            source_bindings["PREFLIGHT_IMPLEMENTATION"]
        ).hexdigest(),
        "callback_implementation_path": callback_path,
        "callback_implementation_sha256": callback_sha,
        "complete_preflight_configuration_sha256": config.configuration_sha256,
        "plan_source_bindings_sha256": canonical_sha256(plan.source_bindings),
        "phase_schema_by_skill": tuple(
            (skill, plan.phase_schema_sha256)
            for skill in (
                "GRASP",
                "LIFT",
                "MOVE",
                "PLACE",
                "RELEASE",
                "REOBSERVE",
                "REASSOCIATE_TARGET",
                "REGRASP",
            )
        ),
        "session_audit_implementation_sha256": hashlib.sha256(b"session audit\n").hexdigest(),
        "host_hmac_verifier_sha256": hashlib.sha256(b"hmac verifier\n").hexdigest(),
        "entry_gate_sha256": entry_sha,
        "formal_physical_runner_binding": runner_binding,
        "formal_deployment_closure_binding": closure_binding,
        "frozen_b0_runtime_wrapper_binding": None,
        "offline_wire_authentication_verifier_binding": None,
        "reviewed_addendum_accepted": True,
        "immutable_git_tree_required": True,
        "session_bound_execution_receipt_required": True,
        "host_hmac_post_execution_replay_required": True,
        "trusted_host_signature_required": False,
        "launcher_attestation_required": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    binding = _receipt(
        ExactPlanA3DeploymentBindingV2.model_construct(
            **binding_payload,
            binding_sha256="0" * 64,
        ),
        "binding_sha256",
    )
    preflight = ExactPlanPreflightV1(
        configuration=config,
        callbacks=callbacks,
        project_root=root,
        deployment_binding=binding,
    )

    result = preflight.verify_phase(plan, plan.phases[0])

    assert result.phase_index == 0
    assert callbacks.path_calls == [0, 1]
    assert callbacks.collision_calls == [0, 1]
    assert callbacks.attachment_calls == [0, 1]
    authorization = preflight._authorizations[plan.bound_plan_sha256]
    assert authorization.formal_execution_eligible is True
    assert authorization.physical_execution_claimed is False
    assert authorization.trusted_host_signature_required is False

    callback_counts = (
        tuple(callbacks.path_calls),
        tuple(callbacks.collision_calls),
        tuple(callbacks.attachment_calls),
    )
    canonical_entry = entry.read_bytes()
    entry.write_text(
        "FORMAL_PHYSICAL_RUNNER_BINDING = None\n"
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING = " + repr(closure_binding) + "\n"
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING = None\n"
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None\n"
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "crossed entry binding"], cwd=root, check=True)
    crossed_payload = binding.model_dump(mode="json")
    crossed_payload["entry_gate_sha256"] = hashlib.sha256(entry.read_bytes()).hexdigest()
    crossed_payload["binding_sha256"] = canonical_sha256(
        {key: value for key, value in crossed_payload.items() if key != "binding_sha256"}
    )
    crossed_binding = ExactPlanA3DeploymentBindingV2.model_validate(crossed_payload)
    with pytest.raises(ExactPlanPreflightRejected, match="entry source bindings"):
        ExactPlanPreflightV1(
            configuration=config,
            callbacks=callbacks,
            project_root=root,
            deployment_binding=crossed_binding,
        ).preflight_plan(plan)
    assert callback_counts == (
        tuple(callbacks.path_calls),
        tuple(callbacks.collision_calls),
        tuple(callbacks.attachment_calls),
    )

    entry.write_bytes(canonical_entry)
    crossed_unlock = dict(unlock_payload)
    crossed_unlock["status"] = "NOT_APPLIED"
    unlock.write_bytes(canonical_json_bytes(crossed_unlock))
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "crossed unlock config"], cwd=root, check=True)
    crossed_payload = binding.model_dump(mode="json")
    crossed_payload["unlock_config_sha256"] = hashlib.sha256(unlock.read_bytes()).hexdigest()
    crossed_payload["binding_sha256"] = canonical_sha256(
        {key: value for key, value in crossed_payload.items() if key != "binding_sha256"}
    )
    crossed_binding = ExactPlanA3DeploymentBindingV2.model_validate(crossed_payload)
    with pytest.raises(ExactPlanPreflightRejected, match="unlock config differs"):
        ExactPlanPreflightV1(
            configuration=config,
            callbacks=callbacks,
            project_root=root,
            deployment_binding=crossed_binding,
        ).preflight_plan(plan)
    assert callback_counts == (
        tuple(callbacks.path_calls),
        tuple(callbacks.collision_calls),
        tuple(callbacks.attachment_calls),
    )


def test_gripper_terminal_must_equal_frozen_wire_target(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(
        tmp_path,
        configuration=config,
        phases=(_pose(0, 0.1), _gripper(1, 0.04)),
    )
    callbacks = _Callbacks(config)
    callbacks.gripper_target_mismatch = True
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)
    executor_calls: list[str] = []

    with pytest.raises(ExactPlanPreflightRejected, match="frozen target"):
        preflight.preflight_plan(plan)

    assert executor_calls == []
    assert preflight._cache == {}


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("gripper_velocity_violation", "gripper velocity"),
        ("gripper_position_violation", "gripper position"),
    ],
)
def test_gripper_range_and_velocity_come_from_canonical_configuration(
    tmp_path: Path,
    failure: str,
    message: str,
) -> None:
    config = _configuration()
    plan = _plan(
        tmp_path,
        configuration=config,
        phases=(_pose(0, 0.1), _gripper(1, 0.04)),
    )
    callbacks = _Callbacks(config)
    setattr(callbacks, failure, True)

    with pytest.raises(ExactPlanPreflightRejected, match=message):
        ExactPlanPreflightV1(configuration=config, callbacks=callbacks).preflight_plan(plan)


def test_remove_must_bind_the_existing_attachment_identity(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(
        tmp_path,
        configuration=config,
        phases=(
            _pose(0, 0.1),
            _gripper(1, 0.06),
            _attachment_phase(2, "REMOVE_ATTACHMENT"),
        ),
        canonical_skill="RELEASE",
    )
    callbacks = _Callbacks(config)
    callbacks.wrong_existing_attachment = True

    with pytest.raises(ExactPlanPreflightRejected, match="wrong transition"):
        ExactPlanPreflightV1(configuration=config, callbacks=callbacks).preflight_plan(plan)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("missing_bilateral_pair", "bilateral transition"),
        ("wrong_bilateral_contact", "outside frozen phase allowlists"),
        ("wrong_attachment_transition", "wrong transition"),
        ("fail_attachment_phase", "callback failed"),
    ],
)
def test_attachment_requires_complete_unique_query_only_bilateral_receipt(
    tmp_path: Path,
    failure: str,
    message: str,
) -> None:
    config = _configuration()
    plan = _grasp_plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    callbacks.initial_attachment_override = False
    setattr(callbacks, failure, 3 if failure == "fail_attachment_phase" else True)
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)
    executor_calls: list[str] = []

    with pytest.raises(ExactPlanPreflightRejected, match=message):
        preflight.preflight_plan(plan)

    assert executor_calls == []
    assert preflight._cache == {}


@pytest.mark.parametrize(
    "failure",
    [
        "position_violation",
        "velocity_violation",
        "effort_violation",
        "workspace_violation",
        "collision_violation",
        "missing_sample",
        "stale",
        "controller_ready",
        "controller_readiness_timeout",
        "terminal_pose_mismatch",
    ],
)
def test_any_gate_failure_rejects_whole_plan_and_executor_is_never_called(
    tmp_path: Path,
    failure: str,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    setattr(callbacks, failure, False if failure == "controller_ready" else True)
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)
    executor_calls: list[str] = []

    with pytest.raises(ExactPlanPreflightRejected):
        preflight.preflight_plan(plan)

    assert executor_calls == []
    assert plan.bound_plan_sha256 not in preflight._cache


def test_initial_attachment_state_is_bound_to_canonical_skill(tmp_path: Path) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    callbacks.initial_attachment_override = False
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)

    with pytest.raises(ExactPlanPreflightRejected, match="initial attachment"):
        preflight.preflight_plan(plan)

    assert callbacks.path_calls == []


def test_missing_second_phase_callback_yields_no_partial_receipt_or_execution(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    callbacks = _Callbacks(config)
    callbacks.fail_phase = 1
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)
    executor_calls: list[str] = []

    with pytest.raises(ExactPlanPreflightRejected, match="callback failed"):
        preflight.preflight_plan(plan)

    assert callbacks.path_calls == [0, 1]
    assert executor_calls == []
    assert preflight._cache == {}


def test_algorithm_or_configuration_role_mismatch_fails_before_any_callback(
    tmp_path: Path,
) -> None:
    config = _configuration()
    plan = _plan(tmp_path, configuration=config)
    dumped = plan.model_dump(mode="json")
    for binding in dumped["source_bindings"]:
        if binding["role"] == "IK_ALGORITHM":
            binding["sha256"] = "0" * 64
    dumped["bound_plan_sha256"] = canonical_sha256(
        {key: value for key, value in dumped.items() if key != "bound_plan_sha256"}
    )
    mismatched = M2CExactPlanPrimitivePlanV1.model_validate(dumped)
    callbacks = _Callbacks(config)
    preflight = ExactPlanPreflightV1(configuration=config, callbacks=callbacks)

    with pytest.raises(ExactPlanPreflightRejected, match="source bindings"):
        preflight.preflight_plan(mismatched)

    assert callbacks.path_calls == []
    assert callbacks.collision_calls == []


def test_startup_introspection_receipt_cannot_claim_unbound_query_callback() -> None:
    payload = {
        "schema_version": "IsaacLulaStartupIntrospectionReceiptV1",
        "container_image_digest": "sha256:" + "1" * 64,
        "isaac_runtime_version": "6.0.1",
        "franka_class_path": "isaacsim.robot.experimental.Franka",
        "set_end_effector_pose_source_sha256": (
            "83b472dd853ae9fe0cff6a560e1f315c77d65ad69f3c37e24f23c43ed0116765"
        ),
        "set_end_effector_pose_writes_dof_targets": True,
        "query_callback_path": None,
        "query_callback_sha256": None,
        "query_callback_proven_non_actuating": False,
        "scene_created": False,
        "physics_steps": 0,
        "articulation_target_writes": 0,
        "scene_mutations": 0,
        "smoke_or_evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    receipt = IsaacLulaStartupIntrospectionReceiptV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )
    assert receipt.query_callback_proven_non_actuating is False

    tampered = receipt.model_dump(mode="json")
    tampered["query_callback_proven_non_actuating"] = True
    with pytest.raises(ValueError, match="callback proof"):
        IsaacLulaStartupIntrospectionReceiptV1.model_validate(tampered)
