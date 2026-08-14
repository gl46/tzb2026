"""Query-only phase adapter from 60 Hz joint paths to ADR-0024 Bullet CCD.

The adapter is deliberately narrower than the whole exact-plan callback.  It
does one thing: turn one already frozen ``NonActuatingPhasePathV1`` into a
complete, replayable continuous self-collision receipt.  It never opens Isaac,
steps physics, writes a target, changes attachment state, or executes a phase.

Non-motion phases return an empty high-level collision result.  Motion phases
must cover the full Cartesian product of non-ACM convex children using the
pinned dynamic-subdivision algorithm.  A production result is possible only
when both the FK provider and native Bullet backend carry their real-runtime
identities; contract fixtures remain visibly non-formal.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Callable, Literal, Protocol, Sequence

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
from xh_agent.policy.qrm_lite.a3_phase_swept_collision_evidence_v1 import (
    build_a3_phase_swept_collision_evidence_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightConfigurationV1,
    MOTION_COMMANDS,
    NonActuatingPhasePathV1,
    NonActuatingSweptCollisionV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_phase_swept_collision_v1.py"


class A3PhaseSweptCollisionUnavailable(RuntimeError):
    """The phase cannot produce complete query-only CCD evidence."""


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


class A3PhaseSweptCollisionProviderV1:
    """Single-deployment, multi-phase non-actuating CCD provider."""

    non_actuating: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        geometry: A3ControlledPandaGeometryReceiptV1,
        fk_provider: A3ReadOnlyFKProviderV1,
        native_backend: _NativeBackend | A3ChildPairCCDBackendV1,
        numeric_configuration: A3BulletNumericConfigurationV1,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.mode = mode
        self.geometry = geometry
        self.fk_provider = fk_provider
        self.native_backend = native_backend
        self.numeric_configuration = numeric_configuration
        self.monotonic_ns = monotonic_ns
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.algorithm_sha256 = canonical_sha256(
            {
                "schema_version": "A3PhaseSweptCollisionAlgorithmV1",
                "implementation_sha256": self.implementation_sha256,
                "geometry_receipt_sha256": geometry.receipt_sha256,
                "fk_provider_implementation_sha256": fk_provider.implementation_sha256,
                "fk_provider_configuration_sha256": fk_provider.configuration_sha256,
                "native_backend_implementation_sha256": native_backend.implementation_sha256,
                "numeric_configuration_sha256": numeric_configuration.configuration_sha256,
                "high_level_subsample_semantics": (
                    "MINIMUM_DYNAMIC_SUBDIVISIONS_PER_NON_ACM_CHILD_PAIR_AND_EXECUTOR_SEGMENT"
                ),
                "complete_non_acm_child_pair_product": True,
            }
        )
        dependencies_are_real = bool(
            not geometry.contract_test_only
            and fk_provider.real_runtime_provider
            and native_backend.real_native_backend
        )
        if (mode == "REAL_ISAAC") != dependencies_are_real:
            raise A3PhaseSweptCollisionUnavailable(
                "A.3 phase provider mode differs from geometry/FK/native dependencies"
            )

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    def _validate_configuration(
        self,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> None:
        collision = configuration.swept_collision
        expected_id = (
            "A3_BULLET_CHILD_PAIR_CCD_V1"
            if self.mode == "REAL_ISAAC"
            else "A3_BULLET_CHILD_PAIR_CCD_CONTRACT_V1"
        )
        if (
            collision.algorithm_id != expected_id
            or collision.algorithm_sha256 != self.algorithm_sha256
            or collision.collision_geometry_sha256 != self.geometry.receipt_sha256
            or collision.robot_root_path != "/World/Robot"
            or not collision.continuous_between_samples
            or not collision.fail_on_unknown_pair
        ):
            raise A3PhaseSweptCollisionUnavailable(
                "A.3 phase collision configuration differs from bound dependencies"
            )

    def query_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
        attached_objects: tuple[A3AttachedObjectGeometryV1, ...] = (),
    ) -> NonActuatingSweptCollisionV1:
        """Return a high-level receipt carrying the complete A.3 replay envelope."""

        self._validate_configuration(configuration)
        wire = phase.phase
        if (
            wire.phase_index >= len(plan.phases)
            or plan.phases[wire.phase_index] != phase
            or path.bound_plan_sha256 != plan.bound_plan_sha256
            or path.phase_index != wire.phase_index
            or path.phase_sha256 != phase.phase_sha256
        ):
            raise A3PhaseSweptCollisionUnavailable(
                "A.3 phase collision query crossed plan/phase/path"
            )

        started = self.monotonic_ns()
        evidence = None
        expected_segments = wire.steps if wire.command in MOTION_COMMANDS else 0
        if expected_segments:
            joint_state_sequence = tuple(sample.joint_positions for sample in path.samples)
            if len(joint_state_sequence) != expected_segments + 1:
                raise A3PhaseSweptCollisionUnavailable(
                    "A.3 phase collision path state count differs"
                )
            try:
                fk_receipt = produce_read_only_fk_receipt_v1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    geometry=self.geometry,
                    joint_names=path.joint_names,
                    joint_state_sequence=joint_state_sequence,
                    provider=self.fk_provider,
                )
                world = build_self_collision_world_from_fk_v1(
                    geometry=self.geometry,
                    fk_receipt=fk_receipt,
                    require_real_runtime_provider=self.mode == "REAL_ISAAC",
                    attached_objects=attached_objects,
                )
                request = build_child_pair_ccd_request_v1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    world=world,
                    configuration=self.numeric_configuration,
                )
                raw_receipt = self.native_backend.query(
                    request,
                    children=world.children,
                    shape_payloads=(
                        *self.geometry.shape_payloads,
                        *(payload for item in attached_objects for payload in item.shape_payloads),
                    ),
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
                    raise A3PhaseSweptCollisionUnavailable(
                        "A.3 native receipt crossed the bound backend implementation"
                    )
                evidence = build_a3_phase_swept_collision_evidence_v1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    phase_index=wire.phase_index,
                    phase_sha256=phase.phase_sha256,
                    path_sha256=path.path_sha256,
                    phase_provider_implementation_sha256=self.implementation_sha256,
                    phase_algorithm_sha256=self.algorithm_sha256,
                    native_backend_implementation_sha256=(
                        self.native_backend.implementation_sha256
                    ),
                    executor_joint_names=path.joint_names,
                    executor_joint_state_sequence=joint_state_sequence,
                    geometry=self.geometry,
                    attached_objects=attached_objects,
                    fk_receipt=fk_receipt,
                    collision_world=world,
                    numeric_configuration=self.numeric_configuration,
                    child_pair_request=request,
                    native_receipt=native_receipt,
                )
            except Exception as exc:
                raise A3PhaseSweptCollisionUnavailable(
                    "A.3 complete child-pair query rejected the phase"
                ) from exc

            per_pair_subdivisions: dict[tuple[int, str, int, str, int], set[int]] = {}
            for item in evidence.child_pair_request.segments:
                key = (
                    item.executor_segment_index,
                    item.link_a,
                    item.child_a,
                    item.link_b,
                    item.child_b,
                )
                per_pair_subdivisions.setdefault(key, set()).add(item.subdivision_index)
            if any(
                len(indices) < configuration.swept_collision.subsamples_per_segment
                for indices in per_pair_subdivisions.values()
            ):
                raise A3PhaseSweptCollisionUnavailable(
                    "A.3 dynamic subdivision coverage is below the frozen minimum"
                )

        duration = self.monotonic_ns() - started
        if duration < 0:
            raise A3PhaseSweptCollisionUnavailable("A.3 monotonic query clock reversed")
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
