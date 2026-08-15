"""Query-only bridge from one live Isaac session to exact-plan synthesis.

The bridge composes the already reviewed articulation/pose getter with a
separate safety-side binding for collision paths and attachment state.  It
never infers a simulator entity from a public track.  A production deployment
must provide that cross-bound receipt explicitly; missing or crossed evidence
therefore rejects before plan construction and before any command.

Simulator paths remain collision/attachment-gate inputs only.  They are not
exposed to Qwen, do not choose a skill or public pointer, and never replace the
world-model decision.  The bridge performs no target write, physics step,
controller command, attachment mutation, or scene mutation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_bound_plan_provider_v1 import (
    FormalPreplanStateReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_synthesis_v1 import (
    FormalPlanSynthesisSnapshotV1,
    FormalPlanSynthesisStateV1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacExecuteRequestV4
from xh_agent.policy.qrm_lite.isaac_active_session_query_v1 import (
    FormalIsaacActiveSessionQueryRuntimeV1,
    IsaacActiveSessionQueryConfigurationV1,
    IsaacActiveSessionQueryProviderV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
    ActiveSessionMutationCountersV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_plan_synthesis_query_v1.py"
_ATTACHING_SKILLS = frozenset({"GRASP", "REGRASP"})
_ATTACHED_SKILLS = frozenset({"LIFT", "MOVE", "PLACE", "RELEASE"})


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacPlanSynthesisQueryUnavailable(RuntimeError):
    """The live state cannot be bound without crossing a formal boundary."""


def _model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _implementation_sha256(project_root: Path) -> str:
    return hashlib.sha256(
        read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
    ).hexdigest()


class FormalPlanSynthesisSceneSafetyBindingV1(_FrozenModel):
    """One request-bound safety projection produced outside the model path.

    ``target_external_contact_path`` is not a model input.  It is consumed only
    by the A.3 contact/collision/attachment gates after the model has already
    selected ``target_public_track_id``.  This schema intentionally contains
    no algorithm for deriving the path; production must bind a reviewed source
    rather than guessing a public-track-to-prim mapping here.
    """

    schema_version: Literal["FormalPlanSynthesisSceneSafetyBindingV1"] = (
        "FormalPlanSynthesisSceneSafetyBindingV1"
    )
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    executed_intent_history_sha256: str = Field(pattern=SHA256_PATTERN)
    selected_skill: str = Field(min_length=1)
    target_public_track_id: str | None = Field(
        default=None,
        pattern=r"^track-[0-9a-f]{8}$",
    )
    target_external_contact_path: str | None = Field(
        default=None,
        pattern=r"^/World/M1B/[^\s]+$",
    )
    target_binding_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    attached_public_track_id: str | None = Field(
        default=None,
        pattern=r"^track-[0-9a-f]{8}$",
    )
    attached_external_contact_path: str | None = Field(
        default=None,
        pattern=r"^/World/M1B/[^\s]+$",
    )
    active_attachment_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    environment_collision_paths: tuple[str, ...] = Field(min_length=1)
    scene_geometry_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    observed_at_ns: int = Field(gt=0)
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    real_isaac: bool
    mocked_physics: bool
    simulator_paths_used_for_skill_or_pointer_selection: Literal[False] = False
    simulator_paths_exposed_to_model: Literal[False] = False
    simulator_paths_used_only_for_a3_gates: Literal[True] = True
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    controller_commands: Literal[0] = 0
    attachment_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    task_spec_fallback_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "FormalPlanSynthesisSceneSafetyBindingV1":
        target_fields = (
            self.target_public_track_id,
            self.target_external_contact_path,
            self.target_binding_receipt_sha256,
        )
        attachment_fields = (
            self.attached_public_track_id,
            self.attached_external_contact_path,
            self.active_attachment_receipt_sha256,
        )
        environment = self.environment_collision_paths
        if self.real_isaac == self.mocked_physics:
            raise ValueError("scene-safety binding must be exactly real or mocked")
        if any(value is None for value in target_fields) != all(
            value is None for value in target_fields
        ):
            raise ValueError("scene-safety target binding is partial")
        if any(value is None for value in attachment_fields) != all(
            value is None for value in attachment_fields
        ):
            raise ValueError("scene-safety attachment binding is partial")
        if environment != tuple(sorted(set(environment))) or any(
            not path.startswith("/World/") for path in environment
        ):
            raise ValueError("scene-safety environment inventory is not canonical")
        for path in (self.target_external_contact_path, self.attached_external_contact_path):
            if path is not None and path not in environment:
                raise ValueError("scene-safety contact path is absent from the environment")
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("scene-safety binding mutated the active session")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("scene-safety binding receipt digest differs")
        return self


class FormalPlanSynthesisSceneSafetySourceV1(Protocol):
    implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1

    def query_scene_safety_binding(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
        after_ns: int,
    ) -> FormalPlanSynthesisSceneSafetyBindingV1: ...


class FormalActiveSessionQueryProviderFactoryV1(Protocol):
    """Create one fresh single-use provider per formal decision."""

    real_isaac: bool
    mocked_physics: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1

    def create_active_session_query_provider(self) -> IsaacActiveSessionQueryProviderV1: ...


class IsaacActiveSessionQueryProviderFactoryV1:
    """Bound factory over one persistent scene owner and shared counter."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        runtime: FormalIsaacActiveSessionQueryRuntimeV1,
        configuration: IsaacActiveSessionQueryConfigurationV1,
    ) -> None:
        self.project_root = project_root.resolve()
        self.mode = mode
        self.runtime = runtime
        self.configuration = configuration
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_physics = mode == "CONTRACT_TEST"
        self.mutation_counter_source = runtime.mutation_counter_source

    def create_active_session_query_provider(self) -> IsaacActiveSessionQueryProviderV1:
        return IsaacActiveSessionQueryProviderV1(
            project_root=self.project_root,
            mode=self.mode,
            runtime=self.runtime,
            configuration=self.configuration,
        )


class FormalIsaacPlanSynthesisStateQueryV1:
    """Single-use composite query source consumed by the exact-plan backend."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        active_session_factory: FormalActiveSessionQueryProviderFactoryV1,
        scene_safety_source: FormalPlanSynthesisSceneSafetySourceV1,
        freshness_limit_ns: int,
    ) -> None:
        if freshness_limit_ns <= 0:
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "plan-synthesis query freshness limit is non-positive"
            )
        self.mode = mode
        self.active_session_factory = active_session_factory
        self.scene_safety_source = scene_safety_source
        self.freshness_limit_ns = freshness_limit_ns
        self.implementation_sha256 = _implementation_sha256(project_root)
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_physics = mode == "CONTRACT_TEST"
        self._consumed_request_sha256: set[str] = set()
        self._pending_active_session: (
            tuple[
                str,
                str,
                IsaacActiveSessionQueryProviderV1,
            ]
            | None
        ) = None

        counter = active_session_factory.mutation_counter_source
        if counter is not scene_safety_source.mutation_counter_source:
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "plan-synthesis query sources do not share one mutation counter"
            )
        if mode == "REAL_ISAAC":
            if (
                not active_session_factory.real_isaac
                or active_session_factory.mocked_physics
                or not scene_safety_source.real_isaac
                or scene_safety_source.mocked_physics
            ):
                raise FormalIsaacPlanSynthesisQueryUnavailable(
                    "REAL_ISAAC plan-synthesis query dependencies differ"
                )
        elif (
            active_session_factory.real_isaac
            or not active_session_factory.mocked_physics
            or scene_safety_source.real_isaac
            or not scene_safety_source.mocked_physics
        ):
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "contract plan-synthesis query received production claims"
            )

    @staticmethod
    def _validate_request_observation(
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
    ) -> None:
        expected = {
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "canonical_public_tracks_sha256": observation.canonical_public_tracks_sha256,
        }
        if any(getattr(request, name) != value for name, value in expected.items()):
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "plan-synthesis query crosses its public observation"
            )

    @staticmethod
    def _validate_skill_binding(
        request: IsaacExecuteRequestV4,
        binding: FormalPlanSynthesisSceneSafetyBindingV1,
    ) -> tuple[str, ...]:
        runtime = request.runtime_request
        skill = runtime.skill
        target = runtime.model_target_track_id
        expected = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": request.observation_id,
            "capture_receipt_sha256": request.capture_receipt_sha256,
            "formal_observation_sha256": request.formal_observation_sha256,
            "executed_intent_history_sha256": request.executed_intent_history_sha256,
            "selected_skill": skill,
            "target_public_track_id": target,
        }
        if any(getattr(binding, name) != value for name, value in expected.items()):
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "scene-safety binding crosses the model-selected request"
            )
        if target is not None and target not in request.observation.canonical_slots:
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "scene-safety target is absent from the public K=8 slots"
            )
        if skill in _ATTACHING_SKILLS:
            if (
                target is None
                or binding.target_external_contact_path is None
                or binding.attached_public_track_id is not None
            ):
                raise FormalIsaacPlanSynthesisQueryUnavailable(
                    "grasp scene-safety binding is absent or already attached"
                )
            return (binding.target_external_contact_path,)
        if skill in _ATTACHED_SKILLS:
            if (
                target is None
                or binding.attached_public_track_id != target
                or binding.attached_external_contact_path is None
                or binding.active_attachment_receipt_sha256 is None
            ):
                raise FormalIsaacPlanSynthesisQueryUnavailable(
                    "transport scene-safety binding lacks the selected attachment"
                )
            return (binding.attached_external_contact_path,)
        return ()

    def query_plan_synthesis_state(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
    ) -> FormalPlanSynthesisSnapshotV1:
        self._validate_request_observation(request, observation)
        request_sha256 = canonical_sha256(request)
        if request_sha256 in self._consumed_request_sha256:
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "plan-synthesis query request was already consumed"
            )
        if self._pending_active_session is not None:
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "prior plan-synthesis state was not bound to its exact plan"
            )
        self._consumed_request_sha256.add(request_sha256)

        active_session = self.active_session_factory.create_active_session_query_provider()
        counter = self.active_session_factory.mutation_counter_source
        if (
            active_session.mutation_counter_source is not counter
            or active_session.real_active_session_source != self.real_isaac
            or active_session.mocked_source != self.mocked_physics
        ):
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "active-session query factory returned crossed dependencies"
            )
        before = counter.snapshot_mutation_counters()
        context_sha256 = canonical_sha256(
            {
                "schema_version": "FormalIsaacPlanSynthesisQueryContextV1",
                "request_sha256": request_sha256,
                "formal_observation_sha256": observation.wire_sha256,
            }
        )
        runtime = active_session.capture_preplan_state(
            context_sha256=context_sha256,
            after_ns=observation.captured_at_ns,
        )
        raw_binding = self.scene_safety_source.query_scene_safety_binding(
            request=request,
            observation=observation,
            after_ns=runtime.observed_at_ns,
        )
        binding = FormalPlanSynthesisSceneSafetyBindingV1.model_validate(
            raw_binding.model_dump(mode="json")
            if isinstance(raw_binding, BaseModel)
            else raw_binding
        )
        after = counter.snapshot_mutation_counters()
        if (
            before != after
            or runtime.mutation_counters_before != before
            or runtime.mutation_counters_after != before
            or binding.mutation_counters_before != before
            or binding.mutation_counters_after != before
            or binding.source_implementation_sha256
            != self.scene_safety_source.implementation_sha256
            or binding.real_isaac != self.real_isaac
            or binding.mocked_physics != self.mocked_physics
            or binding.observed_at_ns <= runtime.observed_at_ns
        ):
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "plan-synthesis query mutated or crossed the active session"
            )
        dynamic_paths = self._validate_skill_binding(request, binding)
        state_payload: dict[str, Any] = {
            "schema_version": "FormalPlanSynthesisStateV1",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "active_session_runtime_receipt_sha256": runtime.receipt_sha256,
            "scene_safety_binding_receipt_sha256": binding.receipt_sha256,
            "scene_geometry_receipt_sha256": binding.scene_geometry_receipt_sha256,
            "active_session_state_sha256": runtime.state_sha256,
            "active_session_state_timestamp_ns": runtime.observed_at_ns,
            "active_session_state_dimensions": 8,
            "active_session_state_units": "rad_7_plus_per_finger_m",
            "active_attachment_receipt_sha256": binding.active_attachment_receipt_sha256,
            "end_effector_position_world_m": runtime.end_effector_world_m,
            "end_effector_orientation_world_wxyz": runtime.end_effector_world_wxyz,
            "gripper_position_m": runtime.gripper_position_m,
            "attached_public_track_id": binding.attached_public_track_id,
            "dynamic_contact_allowlist_paths": dynamic_paths,
            "environment_collision_paths": binding.environment_collision_paths,
            "state_timestamp_ns": binding.observed_at_ns,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "evaluator_identity_used": False,
            "task_spec_fallback_used": False,
            "privileged_identity_or_pose_used": False,
            "privileged_contact_or_success_truth_used": False,
            "privileged_truth_policy_input": False,
        }
        state = FormalPlanSynthesisStateV1(
            **state_payload,
            state_sha256=canonical_sha256(state_payload),
        )
        receipt_payload = {
            "schema_version": "FormalPreplanStateReceiptV1",
            "run_id": state.run_id,
            "session_id": state.session_id,
            "decision_index": state.decision_index,
            "observation_id": state.observation_id,
            "capture_receipt_sha256": state.capture_receipt_sha256,
            "formal_observation_sha256": state.formal_observation_sha256,
            "plan_synthesis_state_sha256": state.state_sha256,
            "state_sha256": state.active_session_state_sha256,
            "state_frame": "world",
            "state_dimensions": state.active_session_state_dimensions,
            "state_units": state.active_session_state_units,
            "state_timestamp_ns": state.active_session_state_timestamp_ns,
            "freshness_limit_ns": self.freshness_limit_ns,
            "query_source_implementation_sha256": self.implementation_sha256,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "evaluator_identity_used": False,
            "task_spec_fallback_used": False,
            "privileged_identity_or_pose_used": False,
            "privileged_contact_or_success_truth_used": False,
            "privileged_truth_policy_input": False,
        }
        receipt = FormalPreplanStateReceiptV1(
            **receipt_payload,
            receipt_sha256=canonical_sha256(receipt_payload),
        )
        self._pending_active_session = (
            state.state_sha256,
            context_sha256,
            active_session,
        )
        return FormalPlanSynthesisSnapshotV1(state=state, receipt=receipt)

    def claim_active_session_query_provider(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> IsaacActiveSessionQueryProviderV1:
        """Consume the exact provider that captured ``plan``'s physical state."""

        pending = self._pending_active_session
        if pending is None:
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "plan-synthesis active-session provider is absent or already claimed"
            )
        # Consume before validation.  A crossed plan must not make the captured
        # physical state retryable under a different immutable plan.
        self._pending_active_session = None
        synthesis_sha256, context_sha256, provider = pending
        cached = provider.cached_preplan_state(context_sha256=context_sha256)
        inputs = plan.inputs
        if (
            inputs.plan_synthesis_state_sha256 != synthesis_sha256
            or inputs.preplan_state_sha256 != cached.state_sha256
            or inputs.preplan_state_timestamp_ns != cached.observed_at_ns
            or inputs.preplan_state_dimensions != 8
            or inputs.preplan_state_units != "rad_7_plus_per_finger_m"
        ):
            raise FormalIsaacPlanSynthesisQueryUnavailable(
                "bound plan crosses its captured active-session state"
            )
        return provider
