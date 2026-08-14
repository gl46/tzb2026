"""Production coordinator for one formal V4 Isaac episode.

This module composes three separately frozen boundaries: a real-Isaac episode
lifecycle, the replayable public-observation provider, and the exact-plan
runtime.  It contains no scene setup, detector, planner, controller, or
fallback implementation.  INVALID mappings and explicitly typed non-actuating
gate rejections are terminal ``NO_PHYSICAL_EXECUTION``.  Unknown exceptions
are never converted into experimental outcomes and are left for the endpoint
state machine to poison and audit.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    FormalExactPlanGateRejectionV1,
    FormalExactPlanRuntimeV1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    ReplayableFormalPublicObservationProviderV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacCaptureRequestV4,
    IsaacCaptureResponseV4,
    IsaacEndpointBindingV4,
    IsaacExecuteRequestV4,
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacFinalizeResponseV4,
    IsaacStartRequestV4,
    IsaacStartResponseV4,
    ModelDecisionExecutionReceiptV4,
    validate_runtime_mapping_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    MappingRejectionV2,
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacEpisodeStartReceiptV4(_FrozenModel):
    """Physical-runtime receipt for the already-established failure boundary."""

    schema_version: Literal["FormalIsaacEpisodeStartReceiptV4"] = "FormalIsaacEpisodeStartReceiptV4"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    start_request_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_backend_sha256: str = Field(pattern=SHA256_PATTERN)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_id: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    qwen_bundle_sha256: str = Field(pattern=SHA256_PATTERN)
    failure_observed_at_ns: int = Field(gt=0)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    failure_boundary_derived_from_public_observation: Literal[True] = True
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_canonical(self) -> "FormalIsaacEpisodeStartReceiptV4":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal V4 episode-start receipt digest differs")
        return self


class FormalIsaacFinalEvaluationReceiptV4(_FrozenModel):
    """Public-only terminal evaluator receipt after exactly eight operations."""

    schema_version: Literal["FormalIsaacFinalEvaluationReceiptV4"] = (
        "FormalIsaacFinalEvaluationReceiptV4"
    )
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    finalize_request_sha256: str = Field(pattern=SHA256_PATTERN)
    last_execution_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    last_bundle_execution_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    execution_response_sha256: tuple[str, ...] = Field(min_length=8, max_length=8)
    public_evaluation_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    evaluated_at_ns: int = Field(gt=0)
    final_task_success: bool
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    completed_model_decisions: Literal[8] = 8
    outcome_used_as_policy_input: Literal[False] = False
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_canonical(self) -> "FormalIsaacFinalEvaluationReceiptV4":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal V4 final-evaluation receipt digest differs")
        return self


class FormalIsaacEpisodeLifecycleV4(Protocol):
    """Deployment-bound real scene owner and public-only final evaluator."""

    implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool

    def start_episode(
        self,
        request: IsaacStartRequestV4,
    ) -> FormalIsaacEpisodeStartReceiptV4: ...

    def finalize_episode(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacFinalEvaluationReceiptV4: ...


_STALE_REJECTIONS = {
    MappingRejectionV2.INVALID_POINTER,
    MappingRejectionV2.STALE_TRACK,
}
_FRAME_UNIT_REJECTIONS = {
    MappingRejectionV2.COORDINATE_FRAME_MISMATCH,
    MappingRejectionV2.UNIT_MISMATCH,
}


def _validated_copy(model: Any, model_type: type[BaseModel]) -> BaseModel:
    raw = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return model_type.model_validate(raw)


def _ordered_clock_pair(now_ns: Callable[[], int], *, after_ns: int) -> tuple[int, int]:
    started_at_ns = int(now_ns())
    completed_at_ns = int(now_ns())
    if started_at_ns <= after_ns or completed_at_ns <= started_at_ns:
        raise RuntimeError("formal V4 no-action clock is not strictly ordered")
    return started_at_ns, completed_at_ns


def _terminal_mapping_v4(
    mapping: RuntimeSkillMappingResultV2,
    *,
    gate_rejection: FormalExactPlanGateRejectionV1 | None = None,
) -> RuntimeSkillMappingResultV2:
    if gate_rejection is None:
        if mapping.status != "INVALID" or mapping.rejection_reason is None:
            raise ValueError("formal V4 terminal mapping lacks an exact rejection")
        return mapping
    if mapping.status != "VALID":
        raise ValueError("formal V4 dynamic rejection did not start from a VALID mapping")
    trace = [dict(item) for item in mapping.gate_trace]
    trace.append(
        {
            "gate": gate_rejection.gate,
            "status": "INVALID",
            "detail": gate_rejection.detail,
        }
    )
    return mapping.model_copy(
        update={
            "status": "INVALID",
            "rejection_reason": gate_rejection.rejection_reason,
            "fallback_action": "NO_PHYSICAL_EXECUTION",
            "fallback_required": True,
            "execution_attribution": "NO_PHYSICAL_EXECUTION",
            "gate_trace": trace,
        }
    )


def _no_action_receipt_v4(
    *,
    request: IsaacExecuteRequestV4,
    mapping: RuntimeSkillMappingResultV2,
    now_ns: Callable[[], int],
) -> ModelDecisionExecutionReceiptV4:
    reason = mapping.rejection_reason
    if mapping.status != "INVALID" or reason is None:
        raise ValueError("formal V4 no-action receipt requires an INVALID mapping")
    started_at_ns, completed_at_ns = _ordered_clock_pair(
        now_ns,
        after_ns=request.observation.captured_at_ns,
    )
    payload: dict[str, Any] = {
        "schema_version": "ModelDecisionExecutionReceiptV4",
        "receipt_id": f"{request.session_id}-no-action-{request.decision_index}",
        "selected_skill": "NO_PHYSICAL_EXECUTION",
        "execution_source": "NO_PHYSICAL_EXECUTION",
        "operation_kind": "NO_PHYSICAL_EXECUTION",
        "outcome": "NOT_EXECUTED",
        "executed_in_real_isaac": False,
        "robot_actuation_executed": False,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "schema_gate": (
            "PASS"
            if reason
            in {
                *_STALE_REJECTIONS,
                *_FRAME_UNIT_REJECTIONS,
                MappingRejectionV2.IK_REJECTION,
                MappingRejectionV2.COLLISION_REJECTION,
                MappingRejectionV2.SAFETY_REJECTION,
            }
            else "REJECTED"
        ),
        "stale_track_gate": "REJECTED" if reason in _STALE_REJECTIONS else "NOT_RUN",
        "frame_unit_gate": ("REJECTED" if reason in _FRAME_UNIT_REJECTIONS else "NOT_RUN"),
        "ik_gate": "REJECTED" if reason == MappingRejectionV2.IK_REJECTION else "NOT_RUN",
        "collision_gate": (
            "REJECTED" if reason == MappingRejectionV2.COLLISION_REJECTION else "NOT_RUN"
        ),
        "controller_gate": "NOT_RUN",
        "safety_gate": ("REJECTED" if reason == MappingRejectionV2.SAFETY_REJECTION else "NOT_RUN"),
        "collision_or_safety_violation": False,
        "failure_reason": f"TERMINAL_NO_PHYSICAL_EXECUTION:{reason.value}",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return ModelDecisionExecutionReceiptV4(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


def _mapping_with_passed_exact_plan_v4(
    mapping: RuntimeSkillMappingResultV2,
    *,
    bound_plan_sha256: str,
    preflight_receipt_sha256: str,
) -> RuntimeSkillMappingResultV2:
    trace = [dict(item) for item in mapping.gate_trace]
    for gate in ("ik", "collision", "controller", "safety"):
        trace.append(
            {
                "gate": gate,
                "status": "PASS",
                "preflight_receipt_sha256": preflight_receipt_sha256,
            }
        )
    trace.append(
        {
            "gate": "exact_plan",
            "status": "PASS",
            "plan_sha256": bound_plan_sha256,
            "preflight_receipt_sha256": preflight_receipt_sha256,
        }
    )
    return mapping.model_copy(update={"gate_trace": trace})


def _execution_receipt_v4(
    *,
    request: IsaacExecuteRequestV4,
    mapping: RuntimeSkillMappingResultV2,
    bundle_receipt: ExactPlanBundleExecutionReceiptV1,
) -> ModelDecisionExecutionReceiptV4:
    phases = bundle_receipt.phase_receipts
    if not phases:
        raise ValueError("formal V4 bundle execution receipt has no phase evidence")
    started_at_ns = min(item.started_at_ns for item in phases)
    completed_at_ns = max(item.completed_at_ns for item in phases)
    if started_at_ns <= request.observation.captured_at_ns:
        raise ValueError("formal V4 bundle execution does not follow its observation")
    skill = str(mapping.canonical_skill)
    operation_kind: Literal[
        "ROBOT_ACTUATION",
        "PUBLIC_RGBD_CAPTURE",
        "PUBLIC_TRACK_ASSOCIATION",
    ] = {
        "REOBSERVE": "PUBLIC_RGBD_CAPTURE",
        "REASSOCIATE_TARGET": "PUBLIC_TRACK_ASSOCIATION",
    }.get(skill, "ROBOT_ACTUATION")  # type: ignore[assignment]
    passed = bundle_receipt.status == "PASS"
    operation_executed = any(item.operation_executed for item in phases)
    observed_collision = any(item.observed_collision for item in phases)
    observed_safety = any(item.observed_safety_violation for item in phases)
    robot_actuation = operation_kind == "ROBOT_ACTUATION" and operation_executed
    if operation_kind == "ROBOT_ACTUATION":
        ik_gate = "PASS"
        collision_gate = "REJECTED" if observed_collision else "PASS"
        safety_gate = "REJECTED" if observed_safety else "PASS"
        controller_gate = "PASS" if passed else "REJECTED" if not observed_collision else "PASS"
    else:
        ik_gate = collision_gate = controller_gate = safety_gate = "NOT_RUN"
    failure_reason = None
    if not passed:
        failure_reason = (
            f"TERMINAL_EXECUTION_FAILURE:{phases[-1].phase_index}:{phases[-1].controller_outcome}"
        )
    payload: dict[str, Any] = {
        "schema_version": "ModelDecisionExecutionReceiptV4",
        "receipt_id": f"{request.session_id}-execution-{request.decision_index}",
        "selected_skill": skill,
        "execution_source": "MODEL_SELECTED_REGISTERED_SKILL",
        "operation_kind": operation_kind,
        "outcome": "PASS" if passed else "FAILED",
        "executed_in_real_isaac": True,
        "robot_actuation_executed": robot_actuation,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "schema_gate": "PASS",
        "stale_track_gate": "PASS",
        "frame_unit_gate": "PASS",
        "ik_gate": ik_gate,
        "collision_gate": collision_gate,
        "controller_gate": controller_gate,
        "safety_gate": safety_gate,
        "collision_or_safety_violation": observed_collision or observed_safety,
        "failure_reason": failure_reason,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return ModelDecisionExecutionReceiptV4(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


class FormalIsaacBackendCoordinatorV4:
    """Defense-in-depth backend used behind ``FormalIsaacEndpointStateMachineV4``."""

    def __init__(
        self,
        *,
        endpoint_binding: IsaacEndpointBindingV4,
        lifecycle: FormalIsaacEpisodeLifecycleV4,
        observation_provider: ReplayableFormalPublicObservationProviderV4,
        observation_provider_implementation_sha256: str,
        exact_plan_runtime: FormalExactPlanRuntimeV1,
        exact_plan_runtime_implementation_sha256: str,
        runtime_registry_sha256: str,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not lifecycle.real_isaac or lifecycle.mocked_physics:
            raise ValueError("formal V4 backend lifecycle is not real Isaac")
        if lifecycle.implementation_sha256 != endpoint_binding.physical_backend_sha256:
            raise ValueError("formal V4 physical lifecycle differs from endpoint binding")
        if observation_provider.mode != "REAL_ISAAC":
            raise ValueError("formal V4 backend requires a REAL_ISAAC observation provider")
        if (
            observation_provider_implementation_sha256
            != endpoint_binding.public_observation_provider_sha256
        ):
            raise ValueError("formal V4 observation provider differs from endpoint binding")
        if (
            exact_plan_runtime_implementation_sha256
            != endpoint_binding.formal_exact_plan_runtime_sha256
        ):
            raise ValueError("formal V4 exact-plan runtime differs from endpoint binding")
        if runtime_registry_sha256 != endpoint_binding.runtime_registry_sha256:
            raise ValueError("formal V4 runtime registry differs from endpoint binding")
        if exact_plan_runtime.provider is None or exact_plan_runtime.bundle is None:
            raise ValueError("formal V4 exact-plan runtime is not production-bound")
        if (
            getattr(exact_plan_runtime.provider, "formal_execution_eligible", False) is not True
            or getattr(exact_plan_runtime.bundle, "formal_execution_eligible", False) is not True
        ):
            raise ValueError("formal V4 plan provider/bundle is not execution-eligible")
        if (
            observation_provider.deployment.deployment_binding_sha256
            != endpoint_binding.association_deployment_sha256
            or observation_provider.deployment.capture_source_implementation_sha256
            != endpoint_binding.capture_source_implementation_sha256
            or observation_provider.attribute_binding.selector_source_implementation_sha256
            != endpoint_binding.declared_attribute_selector_implementation_sha256
        ):
            raise ValueError("formal V4 public observation deployment crosses endpoint binding")
        self.binding = endpoint_binding
        self.lifecycle = lifecycle
        self.observation_provider = observation_provider
        self.exact_plan_runtime = exact_plan_runtime
        self.now_ns = now_ns
        self._run_id: str | None = None
        self._session_id: str | None = None
        self._decision_index = 0
        self._previous_completed_at_ns = 0
        self._previous_execution_receipt_sha256: str | None = None
        self._previous_bundle_execution_receipt_sha256: str | None = None
        self._active_capture: IsaacCaptureResponseV4 | None = None
        self._execution_responses: tuple[IsaacExecuteResponseV4, ...] = ()
        self._terminal = False

    def start(self, request: IsaacStartRequestV4) -> IsaacStartResponseV4:
        if self._run_id is not None or self._terminal:
            raise RuntimeError("formal V4 backend start is single-use")
        if (
            request.endpoint_binding_sha256 != canonical_sha256(self.binding)
            or request.declared_target_attribute
            != self.observation_provider.attribute_binding.declared_target_attribute
            or request.declared_attribute_binding_sha256
            != self.observation_provider.attribute_binding.binding_sha256
        ):
            raise ValueError("formal V4 backend start crosses its public deployment")
        # Establishing the failure boundary is single-use even if the receipt
        # or its enclosing audit response is subsequently lost.
        self._terminal = True
        raw_start = self.lifecycle.start_episode(request)
        start = _validated_copy(raw_start, FormalIsaacEpisodeStartReceiptV4)
        assert isinstance(start, FormalIsaacEpisodeStartReceiptV4)
        expected = {
            "run_id": request.run_id,
            "start_request_sha256": canonical_sha256(request),
            "endpoint_binding_sha256": canonical_sha256(self.binding),
            "physical_backend_sha256": self.binding.physical_backend_sha256,
            "challenge_nonce": request.challenge_nonce,
            "challenge_consumption_id": request.challenge_consumption_id,
            "challenge_consumption_receipt_sha256": (request.challenge_consumption_receipt_sha256),
            "matched_key": request.matched_key,
            "scene_seed": request.scene_seed,
            "failure_seed": request.failure_seed,
            "sdf_sha256": request.sdf_sha256,
            "supervision_sha256": request.supervision_sha256,
            "declared_attribute_binding_sha256": (request.declared_attribute_binding_sha256),
            "qwen_bundle_sha256": canonical_sha256(request.bundle),
        }
        if any(getattr(start, name) != value for name, value in expected.items()):
            raise ValueError("formal V4 lifecycle start receipt crosses its request")
        self.observation_provider.begin_session(
            run_id=request.run_id,
            session_id=start.session_id,
        )
        self._run_id = request.run_id
        self._session_id = start.session_id
        self._previous_completed_at_ns = start.failure_observed_at_ns
        self._terminal = False
        return IsaacStartResponseV4(
            run_id=request.run_id,
            session_id=start.session_id,
            start_request_sha256=start.start_request_sha256,
            failure_observed_at_ns=start.failure_observed_at_ns,
            endpoint_binding_sha256=start.endpoint_binding_sha256,
            implementation_sha256=self.binding.implementation_sha256,
            physical_backend_sha256=self.binding.physical_backend_sha256,
            public_observation_provider_sha256=(self.binding.public_observation_provider_sha256),
            formal_exact_plan_runtime_sha256=(self.binding.formal_exact_plan_runtime_sha256),
        )

    def capture(self, request: IsaacCaptureRequestV4) -> IsaacCaptureResponseV4:
        self._require_cycle(request.run_id, request.session_id, request.decision_index)
        if self._terminal or self._active_capture is not None:
            raise RuntimeError("formal V4 backend capture is not currently allowed")
        if request.previous_execution_receipt_sha256 != (self._previous_execution_receipt_sha256):
            raise ValueError("formal V4 backend capture crosses prior execution")
        # A real capture advances the public sensor timeline.  Consume the
        # attempt before calling the source so a lost packet cannot be retried.
        self._terminal = True
        raw_observation = self.observation_provider.capture(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            previous_execution_completed_at_ns=self._previous_completed_at_ns,
        )
        observation = FormalPublicObservationV4.model_validate(
            raw_observation.model_dump(mode="json")
            if isinstance(raw_observation, BaseModel)
            else raw_observation
        )
        if (
            observation.previous_physical_completed_at_ns != self._previous_completed_at_ns
            or observation.association_deployment_sha256
            != self.binding.association_deployment_sha256
            or observation.declared_attribute_binding_sha256
            != self.observation_provider.attribute_binding.binding_sha256
        ):
            raise ValueError("formal V4 backend observation crosses its session/deployment")
        response = IsaacCaptureResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation=observation,
            formal_observation_sha256=observation.wire_sha256,
        )
        self._active_capture = response
        self._terminal = False
        return response

    def execute(
        self,
        request: IsaacExecuteRequestV4,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV4:
        self._require_cycle(request.run_id, request.session_id, request.decision_index)
        capture = self._active_capture
        if self._terminal or capture is None or request.observation != capture.observation:
            raise RuntimeError("formal V4 backend execute lacks its exact active capture")
        # Consume the operation before any plan/preflight/executor callback.
        # Only a fully formed CONTINUE response reopens the next capture.
        self._terminal = True
        mapping = validate_runtime_mapping_v4(
            request.runtime_request,
            request.observation,
            registry,
        )
        if mapping.status == "INVALID":
            return self._commit_terminal_no_action(request, mapping)
        try:
            prepared = self.exact_plan_runtime.prepare(
                request=request,
                observation=request.observation,
                mapping=mapping,
            )
        except FormalExactPlanGateRejectionV1 as rejection:
            return self._commit_terminal_no_action(
                request,
                _terminal_mapping_v4(mapping, gate_rejection=rejection),
            )

        mapped = _mapping_with_passed_exact_plan_v4(
            mapping,
            bound_plan_sha256=prepared.bound_plan.bound_plan_sha256,
            preflight_receipt_sha256=prepared.preflight_receipt.receipt_sha256,
        )
        bundle_receipt = self.exact_plan_runtime.execute_once(prepared)
        receipt = _execution_receipt_v4(
            request=request,
            mapping=mapped,
            bundle_receipt=bundle_receipt,
        )
        passed = bundle_receipt.status == "PASS"
        response = IsaacExecuteResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            formal_observation_sha256=request.formal_observation_sha256,
            inference_response_sha256=request.inference_response_sha256,
            mapping=mapped,
            bound_plan=prepared.bound_plan,
            bound_plan_sha256=prepared.bound_plan.bound_plan_sha256,
            preflight_receipt=prepared.preflight_receipt,
            preflight_receipt_sha256=prepared.preflight_receipt.receipt_sha256,
            bundle_execution_receipt=bundle_receipt,
            bundle_execution_receipt_sha256=canonical_sha256(bundle_receipt),
            execution_receipts=[receipt],
            disposition="CONTINUE" if passed else "TERMINAL_EXECUTION_FAILURE",
            terminal_failure_outcome=None if passed else False,
            all_phase_preflight_before_any_command=True,
            model_operation_executed_in_real_isaac=any(
                item.operation_executed for item in bundle_receipt.phase_receipts
            ),
        )
        self._commit_execution(response)
        self._terminal = not passed
        return response

    def finalize(self, request: IsaacFinalizeRequestV4) -> IsaacFinalizeResponseV4:
        if self._terminal or self._active_capture is not None:
            raise RuntimeError("formal V4 backend cannot finalize an active/terminal cycle")
        if (
            request.run_id != self._run_id
            or request.session_id != self._session_id
            or self._decision_index != 8
            or len(self._execution_responses) != 8
            or request.last_execution_receipt_sha256 != self._previous_execution_receipt_sha256
            or request.last_bundle_execution_receipt_sha256
            != self._previous_bundle_execution_receipt_sha256
        ):
            raise ValueError("formal V4 backend finalize crosses the eight-cycle episode")
        self._terminal = True
        raw_final = self.lifecycle.finalize_episode(
            request,
            execution_responses=self._execution_responses,
        )
        final = _validated_copy(raw_final, FormalIsaacFinalEvaluationReceiptV4)
        assert isinstance(final, FormalIsaacFinalEvaluationReceiptV4)
        expected = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "finalize_request_sha256": canonical_sha256(request),
            "last_execution_receipt_sha256": (request.last_execution_receipt_sha256),
            "last_bundle_execution_receipt_sha256": (request.last_bundle_execution_receipt_sha256),
            "execution_response_sha256": tuple(
                canonical_sha256(item) for item in self._execution_responses
            ),
        }
        if any(getattr(final, name) != value for name, value in expected.items()):
            raise ValueError("formal V4 final evaluation crosses its exact execution history")
        if final.evaluated_at_ns <= self._previous_completed_at_ns:
            raise ValueError("formal V4 final evaluation predates the last execution")
        return IsaacFinalizeResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            evaluated_at_ns=final.evaluated_at_ns,
            final_task_success=final.final_task_success,
        )

    def _commit_terminal_no_action(
        self,
        request: IsaacExecuteRequestV4,
        mapping: RuntimeSkillMappingResultV2,
    ) -> IsaacExecuteResponseV4:
        terminal_mapping = _terminal_mapping_v4(mapping)
        receipt = _no_action_receipt_v4(
            request=request,
            mapping=terminal_mapping,
            now_ns=self.now_ns,
        )
        response = IsaacExecuteResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            formal_observation_sha256=request.formal_observation_sha256,
            inference_response_sha256=request.inference_response_sha256,
            mapping=terminal_mapping,
            execution_receipts=[receipt],
            disposition="TERMINAL_NO_PHYSICAL_EXECUTION",
            terminal_failure_outcome=False,
            all_phase_preflight_before_any_command=False,
            model_operation_executed_in_real_isaac=False,
        )
        self._commit_execution(response)
        self._terminal = True
        return response

    def _commit_execution(self, response: IsaacExecuteResponseV4) -> None:
        receipt = response.execution_receipts[0]
        self._previous_execution_receipt_sha256 = receipt.receipt_sha256
        self._previous_completed_at_ns = receipt.completed_at_ns
        self._previous_bundle_execution_receipt_sha256 = response.bundle_execution_receipt_sha256
        self._active_capture = None
        self._execution_responses = (*self._execution_responses, response)
        if response.disposition == "CONTINUE":
            self._decision_index += 1

    def _require_cycle(self, run_id: str, session_id: str, decision_index: int) -> None:
        if (
            not self._run_id
            or not self._session_id
            or run_id != self._run_id
            or session_id != self._session_id
            or decision_index != self._decision_index
        ):
            raise ValueError("formal V4 backend request crosses its active cycle")
