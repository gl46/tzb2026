"""Single-use composition of the complete ADR-0022 A.3 query stack.

This adapter joins the already versioned active-session snapshot, Lula phase
path, complete swept-collision and deterministic attachment-transition
providers behind ``ExactPlanNonActuatingCallbacksV1``.  A complete collision
provider must cover both the ADR-0024 continuous-self component and the
unchanged robot/environment scene gate.  The standalone self-CCD provider is
therefore not sufficient by itself.

Attached payload geometry is mandatory whenever the planned attachment state
is present during a motion phase.  Omitting it is never treated as an empty
robot-only collision world.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Protocol

from xh_agent.policy.qrm_lite.a3_attachment_transition_v1 import (
    A3AttachmentTransitionProviderV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3AttachedObjectGeometryV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    MOTION_COMMANDS,
    ExactPlanPreflightConfigurationV1,
    NonActuatingAttachmentTransitionV1,
    NonActuatingPhasePathV1,
    NonActuatingSweptCollisionV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
    ActiveSessionMutationCountersV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_phase_path_v1 import (
    LulaQueryOnlyPhasePathProviderV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_exact_plan_callbacks_v1.py"


class A3ExactPlanCallbacksUnavailable(RuntimeError):
    """The complete all-phase query stack is absent, crossed or already poisoned."""


class A3AttachedObjectPhaseGeometryResolverV1(Protocol):
    """Pure planning cache for an attached payload's per-sample geometry."""

    implementation_sha256: str
    real_runtime_provider: bool
    mocked_provider: bool
    query_only: Literal[True]

    def validate_initial_attachment(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> None: ...

    def bind_planned_attachment(
        self,
        *,
        attachment: NonActuatingAttachmentTransitionV1,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> None: ...

    def geometry_for_phase(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> A3AttachedObjectGeometryV1: ...

    def release_planned_attachment(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> None: ...


class A3CompleteSweptCollisionProviderV1(Protocol):
    """One provider that proves every self and environment swept query."""

    algorithm_sha256: str
    formal_query_evidence_eligible: bool
    complete_continuous_self_collision_coverage: Literal[True]
    complete_scene_environment_collision_coverage: Literal[True]
    query_only: Literal[True]

    def query_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
        attached_objects: tuple[A3AttachedObjectGeometryV1, ...],
    ) -> NonActuatingSweptCollisionV1: ...


class A3ExactPlanNonActuatingCallbacksV1:
    """One plan, one ordered all-phase query, zero active-session mutations."""

    non_actuating: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        configuration: ExactPlanPreflightConfigurationV1,
        runtime_snapshot: PreflightRuntimeSnapshotV1,
        runtime_snapshot_real: bool,
        mutation_counter_source: ActiveSessionMutationCounterSourceV1,
        phase_path_provider: LulaQueryOnlyPhasePathProviderV1,
        swept_collision_provider: A3CompleteSweptCollisionProviderV1,
        attachment_transition_provider: A3AttachmentTransitionProviderV1,
        attached_geometry_resolver: A3AttachedObjectPhaseGeometryResolverV1,
    ) -> None:
        self.mode = mode
        self.configuration = configuration
        self.runtime_snapshot = runtime_snapshot
        self.mutation_counter_source = mutation_counter_source
        self.phase_path_provider = phase_path_provider
        self.swept_collision_provider = swept_collision_provider
        self.attachment_transition_provider = attachment_transition_provider
        self.attached_geometry_resolver = attached_geometry_resolver
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.ik_algorithm_sha256 = phase_path_provider.ik_algorithm_sha256
        self.swept_collision_algorithm_sha256 = swept_collision_provider.algorithm_sha256
        self.attachment_algorithm_sha256 = attachment_transition_provider.algorithm_sha256
        self._baseline_counters = mutation_counter_source.snapshot_mutation_counters()
        self._active_plan_sha256: str | None = None
        self._next_phase_index = 0
        self._stage: Literal[
            "NEW",
            "SNAPSHOT",
            "PATH",
            "COLLISION",
            "PHASE_DONE",
            "COMPLETE",
            "POISONED",
        ] = "NEW"
        self._active_path: NonActuatingPhasePathV1 | None = None
        self._attachment_sha256 = runtime_snapshot.active_attachment_sha256

        dependencies_real = bool(
            runtime_snapshot_real
            and phase_path_provider.formal_query_evidence_eligible
            and swept_collision_provider.formal_query_evidence_eligible
            and attachment_transition_provider.formal_query_evidence_eligible
            and attached_geometry_resolver.real_runtime_provider
            and not attached_geometry_resolver.mocked_provider
            and mutation_counter_source.real_active_session_source
            and not mutation_counter_source.mocked_counter_source
        )
        dependencies_contract = bool(
            not runtime_snapshot_real
            and not phase_path_provider.formal_query_evidence_eligible
            and not swept_collision_provider.formal_query_evidence_eligible
            and not attachment_transition_provider.formal_query_evidence_eligible
            and not attached_geometry_resolver.real_runtime_provider
            and attached_geometry_resolver.mocked_provider
            and not mutation_counter_source.real_active_session_source
            and mutation_counter_source.mocked_counter_source
        )
        if (mode == "REAL_ISAAC" and not dependencies_real) or (
            mode == "CONTRACT_TEST" and not dependencies_contract
        ):
            raise A3ExactPlanCallbacksUnavailable(
                "A.3 callback mode differs from its complete query dependencies"
            )
        if (
            configuration.callback_implementation_sha256 != self.implementation_sha256
            or configuration.ik.algorithm_sha256 != self.ik_algorithm_sha256
            or configuration.swept_collision.algorithm_sha256
            != self.swept_collision_algorithm_sha256
            or configuration.attachment.algorithm_sha256 != self.attachment_algorithm_sha256
            or swept_collision_provider.complete_continuous_self_collision_coverage is not True
            or swept_collision_provider.complete_scene_environment_collision_coverage is not True
            or swept_collision_provider.query_only is not True
            or attachment_transition_provider.runtime_snapshot != runtime_snapshot
            or phase_path_provider.state_source.mutation_counter_source
            is not mutation_counter_source
        ):
            raise A3ExactPlanCallbacksUnavailable(
                "A.3 callback configuration/providers do not share one frozen deployment"
            )

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    @property
    def complete(self) -> bool:
        return self._stage == "COMPLETE"

    def _counter(self) -> ActiveSessionMutationCountersV1:
        current = self.mutation_counter_source.snapshot_mutation_counters()
        if current != self._baseline_counters:
            self._stage = "POISONED"
            raise A3ExactPlanCallbacksUnavailable(
                "active-session mutation counters changed during all-phase preflight"
            )
        return current

    def _require_live(self) -> None:
        if self._stage == "POISONED":
            raise A3ExactPlanCallbacksUnavailable("A.3 callback is poisoned")
        self._counter()

    def _poison(self, message: str, exc: Exception | None = None) -> None:
        self._stage = "POISONED"
        error = A3ExactPlanCallbacksUnavailable(message)
        if exc is None:
            raise error
        raise error from exc

    def snapshot_runtime(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> PreflightRuntimeSnapshotV1:
        self._require_live()
        if self._stage != "NEW" or self._active_plan_sha256 is not None:
            self._poison("A.3 runtime snapshot is single-use and must be first")
        if (
            self.runtime_snapshot.bound_plan_sha256 != plan.bound_plan_sha256
            or self.runtime_snapshot.preplan_state_sha256 != plan.inputs.preplan_state_sha256
            or self.runtime_snapshot.observed_at_ns != plan.inputs.preplan_state_timestamp_ns
        ):
            self._poison("A.3 runtime snapshot crossed the bound plan")
        try:
            if self._attachment_sha256 is not None:
                self.attached_geometry_resolver.validate_initial_attachment(
                    attachment_sha256=self._attachment_sha256,
                    plan=plan,
                )
        except Exception as exc:
            self._poison("A.3 initial attached payload geometry is unavailable", exc)
        self._counter()
        self._active_plan_sha256 = plan.bound_plan_sha256
        self._stage = "SNAPSHOT"
        return self.runtime_snapshot

    def _require_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        *,
        expected_stage: str,
    ) -> None:
        self._require_live()
        if (
            self._stage != expected_stage
            or self._active_plan_sha256 != plan.bound_plan_sha256
            or phase.phase.phase_index != self._next_phase_index
            or self._next_phase_index >= len(plan.phases)
            or plan.phases[self._next_phase_index] != phase
        ):
            self._poison("A.3 callback phase order or plan identity differs")

    def solve_phase_path(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        *,
        start_state_sha256: str,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingPhasePathV1:
        expected_stage = "SNAPSHOT" if self._next_phase_index == 0 else "PHASE_DONE"
        self._require_phase(plan, phase, expected_stage=expected_stage)
        if configuration != self.configuration:
            self._poison("A.3 phase-path configuration differs")
        try:
            path = self.phase_path_provider.solve_phase_path(
                plan,
                phase,
                start_state_sha256=start_state_sha256,
                configuration=configuration,
            )
        except Exception as exc:
            self._poison("A.3 phase-path provider rejected", exc)
        self._counter()
        self._active_path = path
        self._stage = "PATH"
        return path

    def check_swept_collision(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingSweptCollisionV1:
        self._require_phase(plan, phase, expected_stage="PATH")
        if configuration != self.configuration or path != self._active_path:
            self._poison("A.3 collision query crossed path/configuration")
        attached_objects: tuple[A3AttachedObjectGeometryV1, ...] = ()
        if self._attachment_sha256 is not None and phase.phase.command in MOTION_COMMANDS:
            try:
                geometry = self.attached_geometry_resolver.geometry_for_phase(
                    attachment_sha256=self._attachment_sha256,
                    plan=plan,
                    phase=phase,
                    path=path,
                )
            except Exception as exc:
                self._poison("A.3 attached payload phase geometry is unavailable", exc)
            if (
                geometry.attachment_receipt_sha256 != self._attachment_sha256
                or geometry.executor_state_count != len(path.samples)
            ):
                self._poison("A.3 attached payload geometry crossed phase states")
            attached_objects = (geometry,)
        try:
            collision = self.swept_collision_provider.query_phase(
                plan,
                phase,
                path,
                configuration=configuration,
                attached_objects=attached_objects,
            )
        except Exception as exc:
            self._poison("A.3 swept-collision provider rejected", exc)
        self._counter()
        self._stage = "COLLISION"
        return collision

    def check_attachment_transition(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        expected_attachment_present: bool,
        expected_attachment_sha256: str | None,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingAttachmentTransitionV1:
        self._require_phase(plan, phase, expected_stage="COLLISION")
        if (
            configuration != self.configuration
            or path != self._active_path
            or expected_attachment_sha256 != self._attachment_sha256
            or expected_attachment_present != (self._attachment_sha256 is not None)
        ):
            self._poison("A.3 attachment query crossed path/configuration/state")
        try:
            transition = self.attachment_transition_provider.query_phase(
                plan,
                phase,
                path,
                expected_attachment_present=expected_attachment_present,
                expected_attachment_sha256=expected_attachment_sha256,
                configuration=configuration,
            )
            if transition.transition == "ATTACH":
                self.attached_geometry_resolver.bind_planned_attachment(
                    attachment=transition,
                    plan=plan,
                    phase=phase,
                    path=path,
                )
            elif transition.transition == "REMOVE":
                assert expected_attachment_sha256 is not None
                self.attached_geometry_resolver.release_planned_attachment(
                    attachment_sha256=expected_attachment_sha256,
                    plan=plan,
                    phase=phase,
                    path=path,
                )
        except Exception as exc:
            self._poison("A.3 attachment transition/resolver rejected", exc)
        self._counter()
        self._attachment_sha256 = transition.attachment_sha256_after
        self._active_path = None
        self._next_phase_index += 1
        self._stage = "COMPLETE" if self._next_phase_index == len(plan.phases) else "PHASE_DONE"
        return transition
