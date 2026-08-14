"""Complete robot/self/environment A.3 swept-collision phase provider."""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Callable, Literal, Protocol, Sequence

from xh_agent.policy.qrm_lite.a3_attached_object_phase_geometry_v1 import (
    A3AttachedObjectPhaseGeometryEvidenceV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3AttachedObjectGeometryV1,
    A3ControlledPandaGeometryReceiptV1,
    A3ReadOnlyFKProviderV1,
    A3ShapePayloadV1,
    build_self_collision_world_from_fk_v1,
    produce_read_only_fk_receipt_v1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3BulletNumericConfigurationV1,
    A3ChildPairCCDBackendV1,
    A3ChildPairCCDReceiptV1,
    A3ChildPairCCDRequestV1,
    A3ConvexChildV1,
    build_child_pair_ccd_request_v1,
    verify_child_pair_ccd_receipt_v1,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_collision_v2 import (
    build_a3_complete_scene_collision_world_v2,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_swept_collision_evidence_v2 import (
    build_a3_complete_scene_phase_evidence_v2,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3SceneStateReceiptV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    MOTION_COMMANDS,
    ExactPlanPreflightConfigurationV1,
    NonActuatingPhasePathV1,
    NonActuatingSweptCollisionV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_complete_scene_swept_collision_v2.py"
CONTRACT_ALGORITHM_ID = "A3_BULLET_COMPLETE_SCENE_CHILD_PAIR_CCD_CONTRACT_V2"
FORMAL_ALGORITHM_ID = "A3_BULLET_COMPLETE_SCENE_CHILD_PAIR_CCD_V2"


class A3CompleteSceneSweptCollisionUnavailable(RuntimeError):
    """The complete-scene phase query is absent, crossed, or rejected."""


class _NativeBackend(Protocol):
    implementation_sha256: str
    real_native_backend: bool

    def query(
        self,
        request: A3ChildPairCCDRequestV1,
        *,
        children: Sequence[A3ConvexChildV1],
        shape_payloads: Sequence[A3ShapePayloadV1],
        configuration: A3BulletNumericConfigurationV1,
    ) -> A3ChildPairCCDReceiptV1: ...


class A3CompleteSceneSweptCollisionProviderV2:
    """Single-deployment provider for complete self and environment CCD."""

    non_actuating: Literal[True] = True
    query_only: Literal[True] = True
    complete_continuous_self_collision_coverage: Literal[True] = True
    complete_scene_environment_collision_coverage: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        robot_geometry: A3ControlledPandaGeometryReceiptV1,
        fk_provider: A3ReadOnlyFKProviderV1,
        scene_geometry: A3SceneCollisionGeometryReceiptV1,
        scene_state: A3SceneStateReceiptV1,
        real_attached_geometry_resolver: bool,
        native_backend: _NativeBackend | A3ChildPairCCDBackendV1,
        numeric_configuration: A3BulletNumericConfigurationV1,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.mode = mode
        self.robot_geometry = robot_geometry
        self.fk_provider = fk_provider
        self.scene_geometry = scene_geometry
        self.scene_state = scene_state
        self.real_attached_geometry_resolver = real_attached_geometry_resolver
        self.native_backend = native_backend
        self.numeric_configuration = numeric_configuration
        self.monotonic_ns = monotonic_ns
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.collision_geometry_binding_sha256 = canonical_sha256(
            {
                "schema_version": "A3CompleteSceneCollisionGeometryBindingV2",
                "robot_geometry_receipt_sha256": robot_geometry.receipt_sha256,
                "scene_geometry_receipt_sha256": scene_geometry.receipt_sha256,
            }
        )
        self.algorithm_sha256 = canonical_sha256(
            {
                "schema_version": "A3CompleteSceneSweptCollisionAlgorithmV2",
                "implementation_sha256": self.implementation_sha256,
                "collision_geometry_binding_sha256": (self.collision_geometry_binding_sha256),
                "scene_state_provider_implementation_sha256": (
                    scene_state.provider_implementation.sha256
                ),
                "scene_state_provider_configuration_sha256": (
                    scene_state.provider_configuration_sha256
                ),
                "fk_provider_implementation_sha256": fk_provider.implementation_sha256,
                "fk_provider_configuration_sha256": fk_provider.configuration_sha256,
                "native_backend_implementation_sha256": (native_backend.implementation_sha256),
                "numeric_configuration_sha256": (numeric_configuration.configuration_sha256),
                "ordinary_environment_motion_model": "FROZEN_PREPLAN_POSE",
                "complete_robot_self_child_pair_product": True,
                "complete_robot_environment_child_pair_product": True,
                "complete_attached_environment_child_pair_product": True,
                "environment_environment_pairs_intentionally_excluded": True,
                "phase_contact_exclusions_source": "EXACT_EXECUTION_PHASE_V2_ALLOWLISTS",
            }
        )
        dependencies_real = bool(
            not robot_geometry.contract_test_only
            and fk_provider.real_runtime_provider
            and scene_state.real_runtime_provider
            and not scene_state.contract_test_only
            and real_attached_geometry_resolver
            and native_backend.real_native_backend
        )
        if (mode == "REAL_ISAAC") != dependencies_real:
            raise A3CompleteSceneSweptCollisionUnavailable(
                "A.3 complete-scene provider mode differs from dependencies"
            )
        if (
            scene_state.geometry_receipt_sha256 != scene_geometry.receipt_sha256
            or scene_state.source_sdf_sha256 != scene_geometry.source_sdf.sha256
            or scene_state.source_supervision_sha256 != scene_geometry.source_supervision.sha256
        ):
            raise A3CompleteSceneSweptCollisionUnavailable(
                "A.3 complete-scene geometry/state binding differs"
            )

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    def _validate_configuration(
        self,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> None:
        collision = configuration.swept_collision
        expected_id = FORMAL_ALGORITHM_ID if self.mode == "REAL_ISAAC" else CONTRACT_ALGORITHM_ID
        if (
            collision.algorithm_id != expected_id
            or collision.algorithm_sha256 != self.algorithm_sha256
            or collision.collision_geometry_sha256 != self.collision_geometry_binding_sha256
            or collision.robot_root_path != "/World/Robot"
            or not collision.continuous_between_samples
            or not collision.fail_on_unknown_pair
        ):
            raise A3CompleteSceneSweptCollisionUnavailable(
                "A.3 complete-scene collision configuration differs"
            )

    def query_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
        attached_objects: tuple[A3AttachedObjectGeometryV1, ...] = (),
        attached_object_phase_geometry_evidence: tuple[
            A3AttachedObjectPhaseGeometryEvidenceV1, ...
        ] = (),
    ) -> NonActuatingSweptCollisionV1:
        self._validate_configuration(configuration)
        wire = phase.phase
        if (
            wire.phase_index >= len(plan.phases)
            or plan.phases[wire.phase_index] != phase
            or path.bound_plan_sha256 != plan.bound_plan_sha256
            or path.phase_index != wire.phase_index
            or path.phase_sha256 != phase.phase_sha256
            or self.scene_state.bound_plan_sha256 != plan.bound_plan_sha256
            or tuple(item.geometry for item in attached_object_phase_geometry_evidence)
            != attached_objects
        ):
            raise A3CompleteSceneSweptCollisionUnavailable(
                "A.3 complete-scene phase query crossed plan/phase/path/state"
            )
        started = self.monotonic_ns()
        evidence = None
        expected_segments = wire.steps if wire.command in MOTION_COMMANDS else 0
        if expected_segments:
            states = tuple(sample.joint_positions for sample in path.samples)
            if len(states) != expected_segments + 1:
                raise A3CompleteSceneSweptCollisionUnavailable(
                    "A.3 complete-scene path state count differs"
                )
            try:
                fk_receipt = produce_read_only_fk_receipt_v1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    geometry=self.robot_geometry,
                    joint_names=path.joint_names,
                    joint_state_sequence=states,
                    provider=self.fk_provider,
                )
                base_world = build_self_collision_world_from_fk_v1(
                    geometry=self.robot_geometry,
                    fk_receipt=fk_receipt,
                    require_real_runtime_provider=self.mode == "REAL_ISAAC",
                    attached_objects=attached_objects,
                )
                complete_world = build_a3_complete_scene_collision_world_v2(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    phase_index=wire.phase_index,
                    phase_sha256=phase.phase_sha256,
                    path_sha256=path.path_sha256,
                    base_world=base_world,
                    base_shape_payloads=(
                        *self.robot_geometry.shape_payloads,
                        *(payload for item in attached_objects for payload in item.shape_payloads),
                    ),
                    scene_geometry=self.scene_geometry,
                    scene_state=self.scene_state,
                    allowed_robot_contact_paths=wire.allowed_robot_contact_paths,
                    allowed_external_contact_paths=wire.allowed_external_contact_paths,
                    real_attached_geometry_resolver=(self.real_attached_geometry_resolver),
                    contract_test_only=self.mode == "CONTRACT_TEST",
                )
                request = build_child_pair_ccd_request_v1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    world=complete_world.collision_world,
                    configuration=self.numeric_configuration,
                )
                raw_receipt = self.native_backend.query(
                    request,
                    children=complete_world.collision_world.children,
                    shape_payloads=complete_world.shape_payloads,
                    configuration=self.numeric_configuration,
                )
                native_receipt = A3ChildPairCCDReceiptV1.model_validate(
                    raw_receipt.model_dump(mode="json")
                    if hasattr(raw_receipt, "model_dump")
                    else raw_receipt
                )
                verify_child_pair_ccd_receipt_v1(
                    request,
                    native_receipt,
                    configuration=self.numeric_configuration,
                    require_real_native_backend=self.mode == "REAL_ISAAC",
                )
                if (
                    native_receipt.backend_implementation_sha256
                    != self.native_backend.implementation_sha256
                ):
                    raise A3CompleteSceneSweptCollisionUnavailable(
                        "A.3 complete-scene native backend identity differs"
                    )
                evidence = build_a3_complete_scene_phase_evidence_v2(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    phase_index=wire.phase_index,
                    phase_sha256=phase.phase_sha256,
                    path_sha256=path.path_sha256,
                    phase_provider_implementation_sha256=self.implementation_sha256,
                    phase_algorithm_sha256=self.algorithm_sha256,
                    collision_geometry_binding_sha256=(self.collision_geometry_binding_sha256),
                    native_backend_implementation_sha256=(
                        self.native_backend.implementation_sha256
                    ),
                    executor_joint_names=path.joint_names,
                    executor_joint_state_sequence=states,
                    robot_geometry=self.robot_geometry,
                    attached_objects=attached_objects,
                    attached_object_phase_geometry_evidence=(
                        attached_object_phase_geometry_evidence
                    ),
                    fk_receipt=fk_receipt,
                    scene_geometry=self.scene_geometry,
                    scene_state=self.scene_state,
                    complete_scene_world=complete_world,
                    numeric_configuration=self.numeric_configuration,
                    child_pair_request=request,
                    native_receipt=native_receipt,
                )
            except Exception as exc:
                raise A3CompleteSceneSweptCollisionUnavailable(
                    "A.3 complete scene child-pair query rejected the phase"
                ) from exc
            subdivision_counts: dict[tuple[int, str, int, str, int], set[int]] = {}
            for item in evidence.child_pair_request.segments:
                key = (
                    item.executor_segment_index,
                    item.link_a,
                    item.child_a,
                    item.link_b,
                    item.child_b,
                )
                subdivision_counts.setdefault(key, set()).add(item.subdivision_index)
            if any(
                len(indices) < configuration.swept_collision.subsamples_per_segment
                for indices in subdivision_counts.values()
            ):
                raise A3CompleteSceneSweptCollisionUnavailable(
                    "A.3 complete-scene subdivision coverage is below the frozen minimum"
                )
        duration = self.monotonic_ns() - started
        if duration < 0:
            raise A3CompleteSceneSweptCollisionUnavailable(
                "A.3 complete-scene monotonic query clock reversed"
            )
        payload = {
            "schema_version": "NonActuatingSweptCollisionV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_index": wire.phase_index,
            "phase_sha256": phase.phase_sha256,
            "path_sha256": path.path_sha256,
            "algorithm_sha256": self.algorithm_sha256,
            "configuration_sha256": configuration.swept_collision.configuration_sha256,
            "segments": [
                {
                    "segment_index": index,
                    "subsamples_checked": configuration.swept_collision.subsamples_per_segment,
                    "complete": True,
                    "collision_pairs": (),
                }
                for index in range(expected_segments)
            ],
            "a3_phase_evidence": (
                evidence.model_dump(mode="json") if evidence is not None else None
            ),
            "query_duration_ns": duration,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return NonActuatingSweptCollisionV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
