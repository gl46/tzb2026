"""Concrete per-decision A.3/exact-plan component graph for formal Isaac V4.

The enclosing bundle factory owns the one-shot plan/state claim.  This module
only assembles the already reviewed query-only and execution components over
that same persistent scene.  Construction reads current state and scene poses,
but it never writes an articulation target, steps simulation, mutates the
scene, or selects/replans an action.

``CONTRACT_TEST`` keeps production deployment bindings out of the constructed
preflight/executor.  ``REAL_ISAAC`` requires the exact deployment bindings and
real query/native dependencies; those objects remain independently replayed by
the preflight and primitive bundle before a command can start.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Literal, Mapping

from xh_agent.policy.qrm_lite.a3_active_session_attached_object_geometry_v2 import (
    A3ActiveSessionAttachedObjectPhaseGeometryResolverV2,
)
from xh_agent.policy.qrm_lite.a3_attachment_transition_v1 import (
    A3AttachmentTransitionProviderV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3ControlledPandaGeometryReceiptV1,
    A3ReadOnlyFKProviderV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3BulletNumericConfigurationV1,
    A3ChildPairCCDBackendV1,
    A3RigidTransformV1,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_swept_collision_v2 import (
    A3CompleteSceneSweptCollisionProviderV2,
)
from xh_agent.policy.qrm_lite.a3_exact_plan_callbacks_v1 import (
    A3ExactPlanNonActuatingCallbacksV1,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3ScenePoseProviderV1,
    produce_a3_scene_state_receipt_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanA3DeploymentBindingV2,
    ExactPlanPreflightConfigurationV1,
    ExactPlanPreflightV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPrimitiveDeploymentBindingV1,
    M2CExactPlanPrimitiveBundleV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_a3_runtime_snapshot_v1 import (
    FormalIsaacA3RuntimeSnapshotProviderV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_scene_safety_binding_v1 import (
    FormalIsaacActiveAttachmentRegistryV2,
)
from xh_agent.policy.qrm_lite.isaac_active_session_query_v1 import (
    IsaacActiveSessionQueryProviderV1,
)
from xh_agent.policy.qrm_lite.isaac_exact_plan_runtime_v1 import (
    FrozenProbeExactPlanExecutorV1,
    PersistentIsaacJournalV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
    LulaQueryOnlyIKCoordinatorV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_phase_path_v1 import (
    LulaQueryOnlyPhasePathProviderV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_components_v1.py"


class FormalIsaacExactPlanComponentsUnavailable(RuntimeError):
    """The concrete component graph crossed its scene, mode, or deployment."""


class FormalIsaacExactPlanComponentSourceV1:
    """Build one fresh, same-scene query/preflight/executor graph per plan."""

    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        mutation_counter_source: ActiveSessionMutationCounterSourceV1,
        active_attachment_source: FormalIsaacActiveAttachmentRegistryV2,
        scene_geometry: A3SceneCollisionGeometryReceiptV1,
        scene_pose_provider: A3ScenePoseProviderV1,
        robot_geometry: A3ControlledPandaGeometryReceiptV1,
        fk_provider: A3ReadOnlyFKProviderV1,
        native_backend: Any | A3ChildPairCCDBackendV1,
        numeric_configuration: A3BulletNumericConfigurationV1,
        ik_coordinator: LulaQueryOnlyIKCoordinatorV1,
        probe: ModuleType | Any,
        robot: Any,
        hand_prim: Any,
        contact_collector: Any,
        sensors: Mapping[str, Any],
        contact_views: Mapping[str, Any],
        journal: PersistentIsaacJournalV1,
        state_digest: Callable[[], str],
        capture_public: Callable[..., Any],
        reassociate_public: Callable[..., Any],
    ) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.mode = mode
        self.mutation_counter_source = mutation_counter_source
        self.active_attachment_source = active_attachment_source
        self.scene_geometry = scene_geometry
        self.scene_pose_provider = scene_pose_provider
        self.robot_geometry = robot_geometry
        self.fk_provider = fk_provider
        self.native_backend = native_backend
        self.numeric_configuration = numeric_configuration
        self.ik_coordinator = ik_coordinator
        self.probe = probe
        self.robot = robot
        self.hand_prim = hand_prim
        self.contact_collector = contact_collector
        self.sensors = dict(sensors)
        self.contact_views = dict(contact_views)
        self.journal = journal
        self.state_digest = state_digest
        self.capture_public = capture_public
        self.reassociate_public = reassociate_public
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(self.project_root / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_runtime = mode == "CONTRACT_TEST"
        self.formal_execution_eligible = self.real_isaac
        self._consumed_plan_sha256: set[str] = set()

        dependencies_real = bool(
            mutation_counter_source.real_active_session_source
            and not mutation_counter_source.mocked_counter_source
            and active_attachment_source.real_isaac
            and not active_attachment_source.mocked_physics
            and scene_pose_provider.real_runtime_provider
            and not scene_pose_provider.contract_test_only
            and not robot_geometry.contract_test_only
            and fk_provider.real_runtime_provider
            and native_backend.real_native_backend
            and ik_coordinator.mode == "REAL_ISAAC"
        )
        dependencies_contract = bool(
            not mutation_counter_source.real_active_session_source
            and mutation_counter_source.mocked_counter_source
            and not active_attachment_source.real_isaac
            and active_attachment_source.mocked_physics
            and not scene_pose_provider.real_runtime_provider
            and scene_pose_provider.contract_test_only
            and robot_geometry.contract_test_only
            and not fk_provider.real_runtime_provider
            and not native_backend.real_native_backend
            and ik_coordinator.mode == "CONTRACT_TEST"
        )
        if (
            ik_coordinator.counter_source is not mutation_counter_source
            or scene_pose_provider.mutation_counter_source is not mutation_counter_source
            or active_attachment_source.journal is not journal
            or (mode == "REAL_ISAAC" and not dependencies_real)
            or (mode == "CONTRACT_TEST" and not dependencies_contract)
        ):
            raise FormalIsaacExactPlanComponentsUnavailable(
                "formal exact-plan component dependencies cross scene or execution mode"
            )

    def build_bundle_components(
        self,
        *,
        plan: M2CExactPlanPrimitivePlanV1,
        active_session_provider: IsaacActiveSessionQueryProviderV1,
        runtime_snapshot_provider: FormalIsaacA3RuntimeSnapshotProviderV1,
        runtime_snapshot: PreflightRuntimeSnapshotV1,
        configuration: ExactPlanPreflightConfigurationV1,
        primitive_binding: ExactPlanPrimitiveDeploymentBindingV1,
        a3_deployment_binding: ExactPlanA3DeploymentBindingV2 | None,
    ) -> M2CExactPlanPrimitiveBundleV1:
        plan_sha256 = plan.bound_plan_sha256
        if plan_sha256 in self._consumed_plan_sha256:
            raise FormalIsaacExactPlanComponentsUnavailable(
                "formal exact-plan component plan was already consumed"
            )
        # Consume before any external getter.  A failed pose/native/config
        # query cannot be retried with a different graph for the same plan.
        self._consumed_plan_sha256.add(plan_sha256)
        expected_binding = self.mode == "REAL_ISAAC"
        if (
            active_session_provider.mutation_counter_source is not self.mutation_counter_source
            or runtime_snapshot_provider.mutation_counter_source is not self.mutation_counter_source
            or runtime_snapshot_provider.active_attachment_source
            is not self.active_attachment_source
            or runtime_snapshot.bound_plan_sha256 != plan_sha256
            or runtime_snapshot.preplan_state_sha256 != plan.inputs.preplan_state_sha256
            or (a3_deployment_binding is not None) != expected_binding
            or primitive_binding.execution_mode != self.mode
        ):
            raise FormalIsaacExactPlanComponentsUnavailable(
                "formal exact-plan component request crosses plan/scene/deployment"
            )

        before = self.mutation_counter_source.snapshot_mutation_counters()
        active_attachment_before = self.active_attachment_source.snapshot_active_attachment()
        active_state = active_session_provider.peek_bound_preplan_state(plan)
        if (
            active_state.state_sha256 != runtime_snapshot.preplan_state_sha256
            or active_state.observed_at_ns != runtime_snapshot.observed_at_ns
            or self.state_digest() != plan.inputs.preplan_state_sha256
        ):
            raise FormalIsaacExactPlanComponentsUnavailable(
                "formal exact-plan component active state differs from the bound plan"
            )
        scene_state = produce_a3_scene_state_receipt_v1(
            bound_plan_sha256=plan_sha256,
            runtime_snapshot_sha256=runtime_snapshot.snapshot_sha256,
            geometry=self.scene_geometry,
            provider=self.scene_pose_provider,
            after_ns=runtime_snapshot.checked_at_ns,
            require_real_runtime_provider=self.real_isaac,
        )
        active_attachment_after = self.active_attachment_source.snapshot_active_attachment()
        after = self.mutation_counter_source.snapshot_mutation_counters()
        if before != after or active_attachment_before != active_attachment_after:
            raise FormalIsaacExactPlanComponentsUnavailable(
                "formal exact-plan component construction observed a scene mutation"
            )

        phase_path = LulaQueryOnlyPhasePathProviderV1(
            mode=self.mode,
            state_source=active_session_provider,
            ik_coordinator=self.ik_coordinator,
            effort_provider=active_session_provider,
            project_root=self.project_root,
        )
        attachment = A3AttachmentTransitionProviderV1(
            project_root=self.project_root,
            mode=self.mode,
            runtime_snapshot=runtime_snapshot,
            runtime_snapshot_provider_implementation_sha256=(
                runtime_snapshot_provider.implementation_sha256
            ),
            real_runtime_snapshot=self.real_isaac,
        )
        resolver = A3ActiveSessionAttachedObjectPhaseGeometryResolverV2(
            project_root=self.project_root,
            mode=self.mode,
            bound_plan_sha256=plan_sha256,
            runtime_snapshot_sha256=runtime_snapshot.snapshot_sha256,
            runtime_snapshot_checked_at_ns=runtime_snapshot.checked_at_ns,
            current_hand_world_transform=A3RigidTransformV1(
                translation_world_m=active_state.end_effector_world_m,
                rotation_world_wxyz=active_state.end_effector_world_wxyz,
            ),
            scene_geometry=self.scene_geometry,
            scene_pose_provider=self.scene_pose_provider,
            active_attachment=active_attachment_before,
        )
        collision = A3CompleteSceneSweptCollisionProviderV2(
            project_root=self.project_root,
            mode=self.mode,
            robot_geometry=self.robot_geometry,
            fk_provider=self.fk_provider,
            scene_geometry=self.scene_geometry,
            scene_state=scene_state,
            real_attached_geometry_resolver=self.real_isaac,
            native_backend=self.native_backend,
            numeric_configuration=self.numeric_configuration,
        )
        callbacks = A3ExactPlanNonActuatingCallbacksV1(
            project_root=self.project_root,
            mode=self.mode,
            configuration=configuration,
            runtime_snapshot=runtime_snapshot,
            runtime_snapshot_real=self.real_isaac,
            mutation_counter_source=self.mutation_counter_source,
            phase_path_provider=phase_path,
            swept_collision_provider=collision,
            attachment_transition_provider=attachment,
            attached_geometry_resolver=resolver,
        )
        preflight = ExactPlanPreflightV1(
            configuration=configuration,
            callbacks=callbacks,
            project_root=self.project_root if self.real_isaac else None,
            deployment_binding=(a3_deployment_binding if self.real_isaac else None),
        )
        executor = FrozenProbeExactPlanExecutorV1(
            project_root=self.project_root,
            mode=self.mode,
            probe=self.probe,
            robot=self.robot,
            hand_prim=self.hand_prim,
            contact_collector=self.contact_collector,
            sensors=self.sensors,
            contact_views=self.contact_views,
            journal=self.journal,
            state_digest=self.state_digest,
            capture_public=self.capture_public,
            reassociate_public=self.reassociate_public,
            mutation_counter_source=self.mutation_counter_source,
            attachment_state_registry=self.active_attachment_source,
            deployment_binding=(primitive_binding if self.real_isaac else None),
        )
        final = self.mutation_counter_source.snapshot_mutation_counters()
        if final != before:
            raise FormalIsaacExactPlanComponentsUnavailable(
                "formal exact-plan component constructors mutated the active scene"
            )
        return M2CExactPlanPrimitiveBundleV1(
            project_root=self.project_root,
            binding=primitive_binding,
            preflight_verifier=preflight,
            executor=executor,
        )


def implementation_sha256_v1(project_root: Path) -> str:
    return hashlib.sha256(
        read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
    ).hexdigest()
