from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    ControllerPreflightConfigurationV1,
    ExactPlanPreflightConfigurationV1,
    GripperLimitConfigurationV1,
    IKPreflightConfigurationV1,
    JointLimitConfigurationV1,
    SafetyPreflightConfigurationV1,
    SweptCollisionConfigurationV1,
    canonical_non_actuating_state_sha256,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanA1InputsV1,
    ExactPlanPhaseContractV1,
    ExactPlanSourceBindingV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    LULA_JOINT_NAMES,
    _EXPECTED_IMAGE_FILES,
    ActiveSessionMutationCountersV1,
    LulaImageFileBindingV1,
    LulaNativeIKResultV1,
    LulaQueryOnlyIKCoordinatorV1,
    LulaQueryOnlySourceClosureV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_phase_path_v1 import (
    ActiveSessionRobotStateV1,
    ConservativeEffortUpperBoundReceiptV1,
    LulaPhasePathUnavailable,
    LulaQueryOnlyPhasePathEvidenceV1,
    LulaQueryOnlyPhasePathProviderV1,
)


ROOT = Path(__file__).parents[2]
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


def _with_digest(model: type[Any], **payload: Any):
    field = "configuration_sha256"
    provisional = model.model_construct(**payload, **{field: "0" * 64})
    dumped = provisional.model_dump(mode="json", exclude={field})
    return model.model_validate({**dumped, field: canonical_sha256(dumped)})


def _closure() -> LulaQueryOnlySourceClosureV1:
    files = tuple(
        LulaImageFileBindingV1(role=role, path=path, sha256=sha, size_bytes=size)
        for role, path, sha, size in _EXPECTED_IMAGE_FILES
    )
    payload: dict[str, Any] = {
        "schema_version": "LulaQueryOnlySourceClosureV1",
        "image_digest": "sha256:"
        + "783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9",
        "files": [item.model_dump(mode="json") for item in files],
        "native_module_path": (
            "extsDeprecated/isaacsim.robot_motion.lula/pip_prebundle/"
            "lula.cpython-312-x86_64-linux-gnu.so"
        ),
        "robot_descriptor_path": (
            "extsDeprecated/isaacsim.robot_motion.motion_generation/"
            "motion_policy_configs/franka/rmpflow/robot_descriptor.yaml"
        ),
        "robot_description_path": (
            "extsDeprecated/isaacsim.robot_motion.motion_generation/"
            "motion_policy_configs/franka/lula_franka_gen.urdf"
        ),
        "joint_names": LULA_JOINT_NAMES,
        "end_effector_frame": "panda_hand",
        "scene_opened": False,
        "controller_called": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return LulaQueryOnlySourceClosureV1(
        **payload,
        source_closure_sha256=canonical_sha256(payload),
    )


class _Counters:
    implementation_sha256 = "1" * 64
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


def _rotation_matrix(quaternion: tuple[float, float, float, float]) -> tuple[float, ...]:
    w, x, y, z = quaternion
    return (
        1 - 2 * (y * y + z * z),
        2 * (x * y - z * w),
        2 * (x * z + y * w),
        2 * (x * y + z * w),
        1 - 2 * (x * x + z * z),
        2 * (y * z - x * w),
        2 * (x * z - y * w),
        2 * (y * z + x * w),
        1 - 2 * (x * x + y * y),
    )


class _Kernel:
    joint_names = LULA_JOINT_NAMES
    frame_names = ("panda_link0", "panda_hand")
    implementation_sha256 = "2" * 64
    real_runtime_provider = False
    mocked_kernel = True

    def __init__(self, closure: LulaQueryOnlySourceClosureV1) -> None:
        self.source_closure_sha256 = closure.source_closure_sha256

    def solve(self, request: Any) -> LulaNativeIKResultV1:
        solution = list(request.warm_start_joint_positions_rad)
        solution[0] += 0.0005
        return LulaNativeIKResultV1(
            native_success=True,
            solution_joint_positions_rad=tuple(solution),
            native_position_error=0.0,
            native_axis_orientation_errors=(0.0, 0.0, 0.0),
            num_descents=1,
            achieved_position_robot_base_m=request.target_position_robot_base_m,
            achieved_orientation_robot_base_matrix=_rotation_matrix(
                request.target_orientation_robot_base_wxyz
            ),
        )


class _StateSource:
    implementation_sha256 = "3" * 64
    real_active_session_source = False
    mocked_source = True

    def __init__(self, counters: _Counters, state_sha256: str) -> None:
        self.mutation_counter_source = counters
        self.state_sha256 = state_sha256

    def read_active_state(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> ActiveSessionRobotStateV1:
        counters = self.mutation_counter_source.snapshot_mutation_counters()
        payload: dict[str, Any] = {
            "schema_version": "ActiveSessionRobotStateV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "joint_names": LULA_JOINT_NAMES,
            "joint_positions_rad": (0.0,) * 7,
            "gripper_position_m": 0.04,
            "end_effector_world_m": (0.0, 0.0, 0.5),
            "end_effector_world_wxyz": (1.0, 0.0, 0.0, 0.0),
            "robot_base_world_m": (0.0, 0.0, 0.0),
            "robot_base_world_wxyz": (1.0, 0.0, 0.0, 0.0),
            "observed_at_ns": 100,
            "source_implementation_sha256": self.implementation_sha256,
            "real_active_session_source": False,
            "mocked_source": True,
            "mutation_counters_before": counters,
            "mutation_counters_after": counters,
            "query_only": True,
            "state_sha256": self.state_sha256,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return ActiveSessionRobotStateV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )


class _Effort:
    implementation_sha256 = "4" * 64
    configuration_sha256 = "5" * 64
    joint_limit_source_sha256 = "5" * 64
    controller_configuration_sha256 = "9" * 64
    maximum_abs_effort = (10.0,) * 7
    joint_names = LULA_JOINT_NAMES
    real_runtime_provider = False
    mocked_provider = True

    def __init__(self, counters: _Counters) -> None:
        self.mutation_counter_source = counters

    def estimate_abs_effort_upper_bound(
        self,
        joint_positions_rad: tuple[float, ...],
    ) -> ConservativeEffortUpperBoundReceiptV1:
        counters = self.mutation_counter_source.snapshot_mutation_counters()
        payload: dict[str, Any] = {
            "schema_version": "ConservativeEffortUpperBoundReceiptV1",
            "joint_names": LULA_JOINT_NAMES,
            "joint_positions_sha256": canonical_sha256(
                {"joint_names": LULA_JOINT_NAMES, "joint_positions": joint_positions_rad}
            ),
            "estimated_abs_efforts": (1.0,) * 7,
            "provider_implementation_sha256": self.implementation_sha256,
            "provider_configuration_sha256": self.configuration_sha256,
            "real_runtime_provider": False,
            "mocked_provider": True,
            "mutation_counters_before": counters,
            "mutation_counters_after": counters,
            "conservative_upper_bound": True,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
        }
        return ConservativeEffortUpperBoundReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )


def _gates() -> ExactExecutionPhaseGatesV2:
    return ExactExecutionPhaseGatesV2(
        ik_detail="query-only Lula",
        joint_limits_detail="60Hz path",
        swept_collision_detail="continuous CCD",
        controller_detail="ready/shape/rate",
        safety_detail="workspace/contact/state",
    )


def _contract(phase: ExactExecutionPhaseV2) -> ExactPlanPhaseContractV1:
    return ExactPlanPhaseContractV1(
        phase=phase,
        phase_sha256=canonical_sha256(phase),
        command_rate_hz=60.0,
        command_dimensions={"CARTESIAN_POSE": 7, "GRIPPER_POSITION": 1}[phase.command],
        interpolation_rule="LINEAR_FIXED_STEPS",
        convergence_tolerance_m=0.002,
        timeout_ns=5_000_000_000,
        allowed_robot_links_sha256=canonical_sha256(phase.allowed_robot_contact_paths),
        allowed_environment_paths_sha256=canonical_sha256(()),
        allowed_external_contact_paths_sha256=canonical_sha256(
            phase.allowed_external_contact_paths
        ),
    )


def _plan(phases: tuple[ExactExecutionPhaseV2, ...]) -> M2CExactPlanPrimitivePlanV1:
    preplan_state_sha256 = canonical_non_actuating_state_sha256(
        {
            "joint_positions": (0.0,) * 7,
            "end_effector_world_m": (0.0, 0.0, 0.5),
            "end_effector_world_wxyz": (1.0, 0.0, 0.0, 0.0),
            "gripper_position_m": 0.04,
        }
    )
    wire = ExactExecutionPlanV2(
        run_id="run",
        session_id="session",
        decision_index=1,
        observation_id="observation",
        capture_receipt_sha256="a" * 64,
        canonical_skill="LIFT",
        runtime_action="B0_CARTESIAN_LIFT",
        execution_parameters_sha256="b" * 64,
        target_track_id="track-1234abcd",
        phases=phases,
    )
    contracts = tuple(_contract(phase) for phase in phases)
    bindings = tuple(
        ExactPlanSourceBindingV1(
            role=role,
            path=f"source/{index}",
            sha256=hashlib.sha256(role.encode()).hexdigest(),
        )
        for index, role in enumerate(ROLES)
    )
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
    payload: dict[str, Any] = {
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
            rgb_sha256="c" * 64,
            depth_sha256="d" * 64,
            canonical_public_tracks_sha256="e" * 64,
            signed_model_inference_response_sha256="f" * 64,
            runtime_mapping_sha256="1" * 64,
            canonical_skill=wire.canonical_skill,
            runtime_action=wire.runtime_action,
            target_track_id=wire.target_track_id,
            resolved_execution_parameters_sha256=wire.execution_parameters_sha256,
            plan_synthesis_state_sha256="b" * 64,
            preplan_state_sha256=preplan_state_sha256,
            preplan_state_dimensions=8,
            preplan_state_units="rad_7_plus_per_finger_m",
            preplan_state_timestamp_ns=100,
            preplan_state_freshness_limit_ns=1_000_000,
            plan_constructed_at_ns=101,
            controller_frequency_hz=60.0,
            command_dimensions=7,
            convergence_tolerance_m=0.002,
            immutable_commit="2" * 40,
            container_image_digest="sha256:" + "3" * 64,
        ),
        "source_bindings": bindings,
        "phases": contracts,
        "phase_schema_sha256": canonical_sha256(schema_projection),
    }
    provisional = M2CExactPlanPrimitivePlanV1.model_construct(
        **payload,
        bound_plan_sha256="0" * 64,
    )
    payload["bound_plan_sha256"] = canonical_sha256(provisional.semantic_payload())
    return M2CExactPlanPrimitivePlanV1.model_validate(payload)


def _provider_and_configuration(
    plan: M2CExactPlanPrimitivePlanV1,
) -> tuple[LulaQueryOnlyPhasePathProviderV1, ExactPlanPreflightConfigurationV1]:
    closure = _closure()
    counters = _Counters()
    coordinator = LulaQueryOnlyIKCoordinatorV1(
        source_closure=closure,
        kernel=_Kernel(closure),
        counter_source=counters,
        mode="CONTRACT_TEST",
        adapter_implementation_path=ROOT / "src/xh_agent/policy/qrm_lite/lula_query_only_ik_v1.py",
    )
    effort = _Effort(counters)
    state = _StateSource(counters, plan.inputs.preplan_state_sha256)
    provider = LulaQueryOnlyPhasePathProviderV1(
        mode="CONTRACT_TEST",
        state_source=state,
        ik_coordinator=coordinator,
        effort_provider=effort,
        project_root=ROOT,
    )
    lula_config = coordinator.source_closure
    robot_sha = next(
        item.sha256 for item in lula_config.files if item.role == "LULA_ROBOT_DESCRIPTION"
    )
    ik = _with_digest(
        IKPreflightConfigurationV1,
        algorithm_id="LULA_QUERY_ONLY_PHASE_PATH_V1",
        algorithm_sha256=provider.ik_algorithm_sha256,
        robot_description_sha256=robot_sha,
        base_frame="panda_link0",
        end_effector_frame="panda_hand",
        maximum_position_residual_m=0.002,
        maximum_orientation_residual_rad=0.01,
        maximum_iterations_per_sample=64,
        timeout_ns_per_phase=5_000_000_000,
    )
    limits = _with_digest(
        JointLimitConfigurationV1,
        source_sha256="5" * 64,
        joint_names=LULA_JOINT_NAMES,
        lower_position=(-3.0,) * 7,
        upper_position=(3.0,) * 7,
        maximum_velocity_per_s=(2.0,) * 7,
        maximum_abs_effort=(10.0,) * 7,
        effort_estimator_sha256=effort.implementation_sha256,
    )
    gripper = _with_digest(
        GripperLimitConfigurationV1,
        source_sha256="6" * 64,
        minimum_position_m=0.0,
        maximum_position_m=0.04,
        maximum_velocity_m_per_s=0.3,
        target_tolerance_m=1e-9,
        timeout_ns_per_phase=5_000_000_000,
    )
    collision = _with_digest(
        SweptCollisionConfigurationV1,
        algorithm_id="A3_BULLET_CCD_V1",
        algorithm_sha256="7" * 64,
        collision_geometry_sha256="8" * 64,
        robot_root_path="/World/Robot",
        subsamples_per_segment=1,
        timeout_ns_per_phase=5_000_000_000,
    )
    controller = _with_digest(
        ControllerPreflightConfigurationV1,
        controller_id="official_franka_dls",
        controller_configuration_sha256="9" * 64,
        readiness_timeout_ns=1_000_000,
    )
    safety = _with_digest(
        SafetyPreflightConfigurationV1,
        safety_configuration_sha256="a" * 64,
        workspace_min_world_m=(-1.0, -1.0, 0.0),
        workspace_max_world_m=(1.0, 1.0, 1.5),
        maximum_state_age_ns=1_000_000,
        contact_monitor_configuration_sha256="b" * 64,
        attachment_monitor_configuration_sha256="c" * 64,
    )
    attachment = _with_digest(
        AttachmentPreflightConfigurationV1,
        algorithm_id="QUERY_ONLY_ATTACHMENT_V1",
        algorithm_sha256="d" * 64,
        contact_monitor_configuration_sha256=safety.contact_monitor_configuration_sha256,
        attachment_monitor_configuration_sha256=safety.attachment_monitor_configuration_sha256,
        timeout_ns_per_phase=5_000_000_000,
    )
    configuration = _with_digest(
        ExactPlanPreflightConfigurationV1,
        ik=ik,
        joint_limits=limits,
        gripper_limits=gripper,
        swept_collision=collision,
        controller=controller,
        safety=safety,
        attachment=attachment,
        callback_implementation_sha256=provider.implementation_sha256,
        total_timeout_ns=20_000_000_000,
    )
    return provider, configuration


def _phases() -> tuple[ExactExecutionPhaseV2, ...]:
    return (
        ExactExecutionPhaseV2(
            phase_index=0,
            phase_name="LIFT_PATH",
            command="CARTESIAN_POSE",
            goal_position_world_m=(0.002, 0.0, 0.51),
            orientation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
            steps=2,
            collision_phase="LIFT_PATH",
            allowed_robot_contact_paths=("/World/Robot/panda_hand",),
            allowed_external_contact_paths=("/World/M1B/carried",),
            gates=_gates(),
        ),
        ExactExecutionPhaseV2(
            phase_index=1,
            phase_name="OPEN_HAND",
            command="GRIPPER_POSITION",
            gripper_position_m=0.02,
            steps=2,
            collision_phase="OPEN_HAND",
            gates=_gates(),
        ),
    )


def test_cartesian_and_gripper_paths_chain_without_execution() -> None:
    plan = _plan(_phases())
    provider, configuration = _provider_and_configuration(plan)

    first = provider.solve_phase_path(
        plan,
        plan.phases[0],
        start_state_sha256=plan.inputs.preplan_state_sha256,
        configuration=configuration,
    )
    second = provider.solve_phase_path(
        plan,
        plan.phases[1],
        start_state_sha256=first.terminal_state_sha256,
        configuration=configuration,
    )

    assert len(first.samples) == 3
    assert len(provider.evidence_for_path(first.path_sha256).ik_query_receipts) == 2
    assert first.samples[-1].end_effector_world_m == pytest.approx((0.002, 0.0, 0.51))
    assert all(item.gripper_position_m == 0.04 for item in first.samples)
    assert len(second.samples) == 3
    assert second.samples[0].state_sha256 == first.terminal_state_sha256
    assert second.samples[-1].gripper_position_m == pytest.approx(0.02)
    assert all(item.joint_positions == second.samples[0].joint_positions for item in second.samples)
    assert provider.evidence_for_path(second.path_sha256).ik_query_receipts == ()
    assert provider.formal_query_evidence_eligible is False


def test_configuration_mismatch_rejects_before_ik() -> None:
    plan = _plan(_phases())
    provider, configuration = _provider_and_configuration(plan)
    raw = configuration.model_dump(mode="json")
    raw["ik"]["base_frame"] = "world"
    raw["ik"]["configuration_sha256"] = canonical_sha256(
        {key: value for key, value in raw["ik"].items() if key != "configuration_sha256"}
    )
    raw["configuration_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "configuration_sha256"}
    )
    changed = ExactPlanPreflightConfigurationV1.model_validate(raw)
    with pytest.raises(LulaPhasePathUnavailable, match="configuration"):
        provider.solve_phase_path(
            plan,
            plan.phases[0],
            start_state_sha256=plan.inputs.preplan_state_sha256,
            configuration=changed,
        )


def test_effort_deployment_mismatch_rejects_before_path() -> None:
    plan = _plan(_phases())
    provider, configuration = _provider_and_configuration(plan)
    raw = configuration.model_dump(mode="json")
    raw["joint_limits"]["maximum_abs_effort"][0] = 9.0
    raw["joint_limits"]["configuration_sha256"] = canonical_sha256(
        {key: value for key, value in raw["joint_limits"].items() if key != "configuration_sha256"}
    )
    raw["configuration_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "configuration_sha256"}
    )
    changed = ExactPlanPreflightConfigurationV1.model_validate(raw)
    with pytest.raises(LulaPhasePathUnavailable, match="configuration"):
        provider.solve_phase_path(
            plan,
            plan.phases[0],
            start_state_sha256=plan.inputs.preplan_state_sha256,
            configuration=changed,
        )


def test_real_mode_rejects_contract_dependencies() -> None:
    plan = _plan(_phases())
    provider, _ = _provider_and_configuration(plan)
    with pytest.raises(LulaPhasePathUnavailable, match="REAL_ISAAC"):
        LulaQueryOnlyPhasePathProviderV1(
            mode="REAL_ISAAC",
            state_source=provider.state_source,
            ik_coordinator=provider.ik_coordinator,
            effort_provider=provider.effort_provider,
            project_root=ROOT,
        )


def test_evidence_digest_tamper_fails_closed() -> None:
    plan = _plan(_phases())
    provider, configuration = _provider_and_configuration(plan)
    path = provider.solve_phase_path(
        plan,
        plan.phases[0],
        start_state_sha256=plan.inputs.preplan_state_sha256,
        configuration=configuration,
    )
    raw = provider.evidence_for_path(path.path_sha256).model_dump(mode="json")
    raw["path_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        LulaQueryOnlyPhasePathEvidenceV1.model_validate(raw)


def test_phase_order_and_start_state_are_exact() -> None:
    plan = _plan(_phases())
    provider, configuration = _provider_and_configuration(plan)
    with pytest.raises(LulaPhasePathUnavailable, match="phase path start"):
        provider.solve_phase_path(
            plan,
            plan.phases[1],
            start_state_sha256="f" * 64,
            configuration=configuration,
        )


def test_no_teacher_or_privileged_truth_symbols_enter_path() -> None:
    source = (ROOT / "src/xh_agent/policy/qrm_lite/lula_query_only_phase_path_v1.py").read_text()
    assert "TeacherResponse" not in source
    assert "task_target_track_id" not in source
    assert 'privileged_truth_policy_input": False' in source
    assert 'articulation_target_writes": 0' in source
    assert 'simulation_steps": 0' in source
    assert 'scene_mutations": 0' in source
