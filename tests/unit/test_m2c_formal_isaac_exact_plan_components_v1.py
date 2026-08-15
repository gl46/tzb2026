from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from test_m2c_a3_complete_scene_collision_v2 import _scene_geometry
from test_m2c_a3_phase_swept_collision_v1 import _Backend, _FK, _geometry
from test_m2c_formal_isaac_a3_runtime_snapshot_v1 import _Journal, _ReadinessSource
from test_m2c_formal_isaac_exact_plan_bundle_factory_v1 import (
    _plan_and_query,
    _primitive_binding,
)
from test_m2c_lula_query_only_phase_path_v1 import _Kernel, _closure
from xh_agent.policy.qrm_lite.a3_attachment_transition_v1 import (
    A3AttachmentTransitionProviderV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3RigidTransformV1,
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_swept_collision_v2 import (
    CONTRACT_ALGORITHM_ID,
    A3CompleteSceneSweptCollisionProviderV2,
)
from xh_agent.policy.qrm_lite.a3_exact_plan_callbacks_v1 import (
    A3ExactPlanNonActuatingCallbacksV1,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    produce_a3_scene_state_receipt_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    ControllerPreflightConfigurationV1,
    ExactPlanPreflightConfigurationV1,
    ExactPlanPreflightV1,
    GripperLimitConfigurationV1,
    IKPreflightConfigurationV1,
    JointLimitConfigurationV1,
    PreflightRuntimeSnapshotV1,
    SafetyPreflightConfigurationV1,
    SweptCollisionConfigurationV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_exact_plan_bundle_factory_v1 import (
    FormalIsaacPerDecisionExactPlanBundleFactoryV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_exact_plan_components_v1 import (
    FormalIsaacExactPlanComponentsUnavailable,
    FormalIsaacExactPlanComponentSourceV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_scene_safety_binding_v1 import (
    FormalIsaacActiveAttachmentRegistryV2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.isaac_exact_plan_runtime_v1 import (
    FrozenProbeExactPlanExecutorV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    LULA_JOINT_NAMES,
    LulaQueryOnlyIKCoordinatorV1,
    canonical_lula_query_only_ik_configuration_v1,
)
from xh_agent.policy.qrm_lite.lula_query_only_phase_path_v1 import (
    LulaQueryOnlyPhasePathProviderV1,
)


ROOT = Path(__file__).resolve().parents[2]


def _with_digest(model: type[Any], **payload: Any) -> Any:
    provisional = model.model_construct(**payload, configuration_sha256="0" * 64)
    raw = provisional.model_dump(mode="json", exclude={"configuration_sha256"})
    return model.model_validate({**raw, "configuration_sha256": canonical_sha256(raw)})


class _ScenePoseProvider:
    configuration_sha256 = "c" * 64
    real_runtime_provider = False
    contract_test_only = True
    implementation_path = str(Path(__file__).resolve())
    implementation_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def __init__(self, *, counter: Any, geometry: Any) -> None:
        self.mutation_counter_source = counter
        self.geometry = geometry

    def query_scene_link_world_poses(
        self,
        *,
        link_paths: tuple[str, ...],
        after_ns: int,
    ) -> tuple[dict[str, A3RigidTransformV1], int]:
        expected = {item.link_path for item in self.geometry.source_links}
        assert set(link_paths) == expected
        return (
            {
                item.link_path: item.source_initial_world_transform
                for item in self.geometry.source_links
            },
            after_ns + 1,
        )


def _configuration(
    *,
    active: Any,
    phase_path: LulaQueryOnlyPhasePathProviderV1,
    attachment: A3AttachmentTransitionProviderV1,
    collision: A3CompleteSceneSweptCollisionProviderV2,
) -> ExactPlanPreflightConfigurationV1:
    lula = canonical_lula_query_only_ik_configuration_v1()
    robot_description_sha256 = next(
        item.sha256
        for item in phase_path.ik_coordinator.source_closure.files
        if item.role == "LULA_ROBOT_DESCRIPTION"
    )
    ik = _with_digest(
        IKPreflightConfigurationV1,
        algorithm_id="LULA_QUERY_ONLY_PHASE_PATH_V1",
        algorithm_sha256=phase_path.ik_algorithm_sha256,
        robot_description_sha256=robot_description_sha256,
        base_frame="panda_link0",
        end_effector_frame="panda_hand",
        maximum_position_residual_m=lula.position_tolerance_m,
        maximum_orientation_residual_rad=lula.orientation_tolerance_rad,
        maximum_iterations_per_sample=lula.certified_iteration_upper_bound,
        timeout_ns_per_phase=5_000_000_000,
    )
    limits = _with_digest(
        JointLimitConfigurationV1,
        source_sha256=active.joint_limit_source_sha256,
        joint_names=LULA_JOINT_NAMES,
        lower_position=(-3.0,) * 7,
        upper_position=(3.0,) * 7,
        maximum_velocity_per_s=(3.0,) * 7,
        maximum_abs_effort=active.maximum_abs_effort,
        effort_estimator_sha256=active.implementation_sha256,
    )
    gripper = _with_digest(
        GripperLimitConfigurationV1,
        source_sha256="d" * 64,
        minimum_position_m=0.0,
        maximum_position_m=0.08,
        maximum_velocity_m_per_s=1.0,
        target_tolerance_m=0.001,
        timeout_ns_per_phase=5_000_000_000,
    )
    swept = _with_digest(
        SweptCollisionConfigurationV1,
        algorithm_id=CONTRACT_ALGORITHM_ID,
        algorithm_sha256=collision.algorithm_sha256,
        collision_geometry_sha256=collision.collision_geometry_binding_sha256,
        robot_root_path="/World/Robot",
        subsamples_per_segment=1,
        timeout_ns_per_phase=5_000_000_000,
    )
    controller = _with_digest(
        ControllerPreflightConfigurationV1,
        controller_id="official_franka_dls",
        controller_configuration_sha256=active.controller_configuration_sha256,
        readiness_timeout_ns=1_000_000,
    )
    safety = _with_digest(
        SafetyPreflightConfigurationV1,
        safety_configuration_sha256="e" * 64,
        workspace_min_world_m=(-2.0, -2.0, 0.0),
        workspace_max_world_m=(2.0, 2.0, 2.0),
        maximum_state_age_ns=1_000_000,
        contact_monitor_configuration_sha256="f" * 64,
        attachment_monitor_configuration_sha256="1" * 64,
    )
    attachment_config = _with_digest(
        AttachmentPreflightConfigurationV1,
        algorithm_id="A3_PLANNED_ATTACHMENT_TRANSITION_CONTRACT_V1",
        algorithm_sha256=attachment.algorithm_sha256,
        contact_monitor_configuration_sha256=safety.contact_monitor_configuration_sha256,
        attachment_monitor_configuration_sha256=(safety.attachment_monitor_configuration_sha256),
        timeout_ns_per_phase=5_000_000_000,
    )
    callback_sha256 = hashlib.sha256(
        (ROOT / "src/xh_agent/policy/qrm_lite/a3_exact_plan_callbacks_v1.py").read_bytes()
    ).hexdigest()
    return _with_digest(
        ExactPlanPreflightConfigurationV1,
        ik=ik,
        joint_limits=limits,
        gripper_limits=gripper,
        swept_collision=swept,
        controller=controller,
        safety=safety,
        attachment=attachment_config,
        callback_implementation_sha256=callback_sha256,
        total_timeout_ns=60_000_000_000,
    )


def _probe() -> Any:
    noop = lambda *args, **kwargs: None  # noqa: E731
    return SimpleNamespace(
        _step_pose=noop,
        _step_gripper=noop,
        _attach_preserving_pose=noop,
        _remove_attachment=noop,
        broker_from_window=noop,
        evaluate_robot_collision_events=noop,
        RigidPrim=object,
        np=SimpleNamespace(asarray=lambda value: value),
    )


def _stack(tmp_path: Path, *, state_digest: str | None = None):  # type: ignore[no-untyped-def]
    plan, query = _plan_and_query(tmp_path)
    counter = query.active_session_factory.mutation_counter_source
    journal = _Journal()
    attachment_registry = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=journal,
    )
    readiness = _ReadinessSource(counter, attachment_registry)
    prototype_active = query.active_session_factory.create_active_session_query_provider()
    closure = _closure()
    coordinator = LulaQueryOnlyIKCoordinatorV1(
        source_closure=closure,
        kernel=_Kernel(closure),
        counter_source=counter,
        mode="CONTRACT_TEST",
        adapter_implementation_path=(
            ROOT / "src/xh_agent/policy/qrm_lite/lula_query_only_ik_v1.py"
        ),
    )
    phase_path = LulaQueryOnlyPhasePathProviderV1(
        mode="CONTRACT_TEST",
        state_source=prototype_active,
        ik_coordinator=coordinator,
        effort_provider=prototype_active,
        project_root=ROOT,
    )
    snapshot = PreflightRuntimeSnapshotV1.model_construct(
        bound_plan_sha256=plan.bound_plan_sha256,
    )
    runtime_snapshot_implementation_sha256 = hashlib.sha256(
        (ROOT / "src/xh_agent/policy/qrm_lite/formal_isaac_a3_runtime_snapshot_v1.py").read_bytes()
    ).hexdigest()
    attachment = A3AttachmentTransitionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime_snapshot=snapshot,
        runtime_snapshot_provider_implementation_sha256=(runtime_snapshot_implementation_sha256),
        real_runtime_snapshot=False,
    )
    scene_geometry = _scene_geometry(tmp_path)
    scene_pose = _ScenePoseProvider(counter=counter, geometry=scene_geometry)
    scene_state = produce_a3_scene_state_receipt_v1(
        bound_plan_sha256=plan.bound_plan_sha256,
        runtime_snapshot_sha256="2" * 64,
        geometry=scene_geometry,
        provider=scene_pose,
        after_ns=100,
        require_real_runtime_provider=False,
    )
    robot_geometry = _geometry()
    fk_provider = _FK(tmp_path / "contract-fk.py")
    native_backend = _Backend()
    numeric = canonical_a3_bullet_numeric_configuration_v1()
    collision = A3CompleteSceneSweptCollisionProviderV2(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        robot_geometry=robot_geometry,
        fk_provider=fk_provider,
        scene_geometry=scene_geometry,
        scene_state=scene_state,
        real_attached_geometry_resolver=False,
        native_backend=native_backend,
        numeric_configuration=numeric,
    )
    configuration = _configuration(
        active=prototype_active,
        phase_path=phase_path,
        attachment=attachment,
        collision=collision,
    )
    source = FormalIsaacExactPlanComponentSourceV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        mutation_counter_source=counter,
        active_attachment_source=attachment_registry,
        scene_geometry=scene_geometry,
        scene_pose_provider=scene_pose,
        robot_geometry=robot_geometry,
        fk_provider=fk_provider,
        native_backend=native_backend,
        numeric_configuration=numeric,
        ik_coordinator=coordinator,
        probe=_probe(),
        robot=object(),
        hand_prim=object(),
        contact_collector=object(),
        sensors={},
        contact_views={},
        journal=journal,
        state_digest=lambda: state_digest or plan.inputs.preplan_state_sha256,
        capture_public=lambda *_args, **_kwargs: None,
        reassociate_public=lambda *_args, **_kwargs: None,
    )
    factory = FormalIsaacPerDecisionExactPlanBundleFactoryV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        binding=None,
        primitive_binding=_primitive_binding(plan),
        a3_deployment_binding=None,
        plan_synthesis_query=query,
        readiness_source=readiness,
        component_source=source,
        configuration=configuration,
    )
    return plan, source, factory


def test_concrete_component_source_builds_the_actual_same_scene_graph(
    tmp_path: Path,
) -> None:
    plan, source, factory = _stack(tmp_path)

    bundle = factory.build_bundle(plan)

    assert isinstance(bundle.preflight_verifier, ExactPlanPreflightV1)
    assert isinstance(
        bundle.preflight_verifier.callbacks,
        A3ExactPlanNonActuatingCallbacksV1,
    )
    assert isinstance(bundle.executor, FrozenProbeExactPlanExecutorV1)
    callbacks = bundle.preflight_verifier.callbacks
    assert callbacks.phase_path_provider.state_source is (
        callbacks.phase_path_provider.effort_provider
    )
    assert callbacks.swept_collision_provider.scene_geometry == source.scene_geometry
    assert callbacks.swept_collision_provider.scene_state.bound_plan_sha256 == (
        plan.bound_plan_sha256
    )
    assert callbacks.attached_geometry_resolver.scene_pose_provider is (source.scene_pose_provider)
    assert bundle.executor.attachment_state_registry is source.active_attachment_source
    assert bundle.preflight_verifier.project_root is None
    assert bundle.preflight_verifier.deployment_binding is None
    assert bundle.executor.deployment_binding is None
    assert source.formal_execution_eligible is False


def test_component_source_rejects_crossed_active_state_and_consumes_plan(
    tmp_path: Path,
) -> None:
    plan, _, factory = _stack(tmp_path, state_digest="9" * 64)

    with pytest.raises(FormalIsaacExactPlanComponentsUnavailable, match="active state"):
        factory.build_bundle(plan)
    with pytest.raises(Exception, match="already consumed"):
        factory.build_bundle(plan)


def test_component_source_constructor_rejects_crossed_scene_counter(
    tmp_path: Path,
) -> None:
    _, source, _ = _stack(tmp_path)
    crossed_pose = SimpleNamespace(**vars(source.scene_pose_provider))
    crossed_pose.real_runtime_provider = False
    crossed_pose.contract_test_only = True
    crossed_pose.mutation_counter_source = object()

    with pytest.raises(FormalIsaacExactPlanComponentsUnavailable, match="cross scene"):
        FormalIsaacExactPlanComponentSourceV1(
            project_root=ROOT,
            mode="CONTRACT_TEST",
            mutation_counter_source=source.mutation_counter_source,
            active_attachment_source=source.active_attachment_source,
            scene_geometry=source.scene_geometry,
            scene_pose_provider=crossed_pose,
            robot_geometry=source.robot_geometry,
            fk_provider=source.fk_provider,
            native_backend=source.native_backend,
            numeric_configuration=source.numeric_configuration,
            ik_coordinator=source.ik_coordinator,
            probe=source.probe,
            robot=source.robot,
            hand_prim=source.hand_prim,
            contact_collector=source.contact_collector,
            sensors=source.sensors,
            contact_views=source.contact_views,
            journal=source.journal,
            state_digest=source.state_digest,
            capture_public=source.capture_public,
            reassociate_public=source.reassociate_public,
        )
