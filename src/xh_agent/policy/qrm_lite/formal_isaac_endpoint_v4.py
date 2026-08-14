"""Persistent authenticated state machine for one formal V4 Isaac episode.

This module is transport and replay logic only.  It cannot construct a plan,
run preflight, or actuate Isaac.  A separately frozen backend must return the
typed V4 capture and exact-plan receipts; this state machine independently
checks their identity, public association history, registry mapping, ordering,
and terminal semantics before committing a signed response to the labserver
audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Mapping, Protocol

from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v2 import (
    AppendOnlyIsaacAuditLogV2,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    validate_bound_exact_plan_inputs_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_ISAAC_CAPTURE_PATH_V4,
    FORMAL_ISAAC_EXECUTE_PATH_V4,
    FORMAL_ISAAC_FINALIZE_PATH_V4,
    FORMAL_ISAAC_START_PATH_V4,
    IsaacCaptureRequestV4,
    IsaacCaptureResponseV4,
    IsaacEndpointBindingV4,
    IsaacExecuteRequestV4,
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacFinalizeResponseV4,
    IsaacStartRequestV4,
    IsaacStartResponseV4,
    QwenBundleRuntimeBindingV4,
    SignedIsaacWireMessageV4,
    sign_isaac_wire_message_v4,
    validate_runtime_mapping_v4,
    verify_isaac_wire_message_v4,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    MappingRejectionV2,
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
)


FORMAL_ISAAC_PATHS_V4 = frozenset(
    {
        FORMAL_ISAAC_START_PATH_V4,
        FORMAL_ISAAC_CAPTURE_PATH_V4,
        FORMAL_ISAAC_EXECUTE_PATH_V4,
        FORMAL_ISAAC_FINALIZE_PATH_V4,
    }
)


class RealIsaacBackendV4(Protocol):
    """The sole producer of real-Isaac V4 response payloads."""

    def start(self, request: IsaacStartRequestV4) -> IsaacStartResponseV4: ...

    def capture(self, request: IsaacCaptureRequestV4) -> IsaacCaptureResponseV4: ...

    def execute(
        self,
        request: IsaacExecuteRequestV4,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV4: ...

    def finalize(self, request: IsaacFinalizeRequestV4) -> IsaacFinalizeResponseV4: ...


@dataclass
class _SessionStateV4:
    phase: str = "NEW"
    run_id: str | None = None
    session_id: str | None = None
    bundle: QwenBundleRuntimeBindingV4 | None = None
    declared_target_attribute: str | None = None
    declared_attribute_binding_sha256: str | None = None
    decision_index: int = 0
    previous_execution_receipt_sha256: str | None = None
    previous_bundle_execution_receipt_sha256: str | None = None
    previous_completed_at_ns: int = 0
    previous_association_history: tuple[dict[str, Any], ...] = ()
    executed_intent_history: tuple[PublicExecutedIntentHistoryItemV2, ...] = ()
    active_capture: IsaacCaptureResponseV4 | None = None


_DYNAMIC_REJECTIONS = {
    MappingRejectionV2.IK_REJECTION,
    MappingRejectionV2.COLLISION_REJECTION,
    MappingRejectionV2.SAFETY_REJECTION,
}


def _mapping_semantics(mapping: RuntimeSkillMappingResultV2) -> dict[str, Any]:
    return mapping.model_dump(
        mode="json",
        exclude={
            "status",
            "rejection_reason",
            "fallback_required",
            "execution_attribution",
            "gate_trace",
        },
    )


class FormalIsaacEndpointStateMachineV4:
    """Serialize one start -> 8(capture, execute) -> finalize V4 episode."""

    def __init__(
        self,
        *,
        secret: bytes,
        endpoint_binding: IsaacEndpointBindingV4,
        registry: RuntimeSkillRegistryV2,
        backend: RealIsaacBackendV4,
        audit: AppendOnlyIsaacAuditLogV2,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("formal V4 endpoint HMAC key must contain at least 32 bytes")
        self._secret = secret
        self.binding = endpoint_binding
        self.registry = registry
        self.backend = backend
        self.audit = audit
        self.state = _SessionStateV4()
        self._lock = threading.Lock()
        self._poisoned = False
        self._uncommitted_backend_operation: str | None = None

    @property
    def session_audit_path(self) -> Path | None:
        return self.audit._session_path

    def handle(self, path: str, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Authenticate, replay, audit and return one V4 wire response."""

        with self._lock:
            if self._poisoned:
                raise RuntimeError("Isaac V4 session is poisoned after an audit/backend failure")
            try:
                require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
                self.audit.append(
                    "WIRE_REQUEST_RECEIVED",
                    {"path": path, "signed_wire": dict(raw)},
                )
                response = self._dispatch(path, raw)
                dumped = response.model_dump(mode="json")
                self.audit.append(
                    "WIRE_RESPONSE_COMMITTED",
                    {"path": path, "signed_wire": dumped},
                )
                self._uncommitted_backend_operation = None
                return dumped
            except Exception as exc:
                physical_may_have_executed = bool(self._uncommitted_backend_operation == "execute")
                try:
                    self.audit.append(
                        "WIRE_REQUEST_REJECTED",
                        {
                            "path": path,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "physical_evidence_accepted": False,
                            "physical_execution_may_have_occurred": physical_may_have_executed,
                        },
                    )
                except Exception:
                    self._poisoned = True
                if self._uncommitted_backend_operation is not None:
                    self._poisoned = True
                raise

    def _dispatch(
        self,
        path: str,
        raw: Mapping[str, Any],
    ) -> SignedIsaacWireMessageV4:
        if path == FORMAL_ISAAC_START_PATH_V4:
            return self._start(raw)
        if path == FORMAL_ISAAC_CAPTURE_PATH_V4:
            return self._capture(raw)
        if path == FORMAL_ISAAC_EXECUTE_PATH_V4:
            return self._execute(raw)
        if path == FORMAL_ISAAC_FINALIZE_PATH_V4:
            return self._finalize(raw)
        raise ValueError(f"unknown formal V4 Isaac path: {path}")

    def _start(self, raw: Mapping[str, Any]) -> SignedIsaacWireMessageV4:
        if self.state.phase != "NEW":
            raise RuntimeError("Isaac V4 start is allowed exactly once")
        _, request = verify_isaac_wire_message_v4(
            raw,
            self._secret,
            expected_type="ISAAC_START_REQUEST_V4",
            model=IsaacStartRequestV4,
        )
        endpoint_sha = canonical_sha256(self.binding)
        if request.endpoint_binding_sha256 != endpoint_sha:
            raise ValueError("V4 start request differs from endpoint deployment")
        if (
            request.bundle.association_deployment_sha256
            != self.binding.association_deployment_sha256
            or request.bundle.capture_source_implementation_sha256
            != self.binding.capture_source_implementation_sha256
            or request.bundle.declared_attribute_selector_implementation_sha256
            != self.binding.declared_attribute_selector_implementation_sha256
        ):
            raise ValueError("V4 start crosses Qwen and Isaac public-observation deployments")
        request_sha = canonical_sha256(request)
        self.audit.begin_session(run_id=request.run_id, request_sha256=request_sha)
        self.audit.append(
            "ISAAC_V4_START_ACCEPTED_FOR_BACKEND",
            {"request": request.model_dump(mode="json")},
        )
        self._uncommitted_backend_operation = "start"
        response = self.backend.start(request)
        expected_response = {
            "run_id": request.run_id,
            "start_request_sha256": request_sha,
            "endpoint_binding_sha256": endpoint_sha,
            "implementation_sha256": self.binding.implementation_sha256,
            "physical_backend_sha256": self.binding.physical_backend_sha256,
            "public_observation_provider_sha256": (self.binding.public_observation_provider_sha256),
            "formal_exact_plan_runtime_sha256": (self.binding.formal_exact_plan_runtime_sha256),
        }
        if any(
            getattr(response, field) != expected for field, expected in expected_response.items()
        ):
            raise ValueError("real V4 backend start differs from frozen endpoint binding")
        self.state = _SessionStateV4(
            phase="READY_CAPTURE",
            run_id=request.run_id,
            session_id=response.session_id,
            bundle=request.bundle,
            declared_target_attribute=request.declared_target_attribute,
            declared_attribute_binding_sha256=(request.declared_attribute_binding_sha256),
            decision_index=0,
            previous_completed_at_ns=response.failure_observed_at_ns,
        )
        return sign_isaac_wire_message_v4(
            "ISAAC_START_RESPONSE_V4",
            response,
            self._secret,
        )

    def _capture(self, raw: Mapping[str, Any]) -> SignedIsaacWireMessageV4:
        if self.state.phase != "READY_CAPTURE":
            raise RuntimeError("capture is not the next Isaac V4 operation")
        _, request = verify_isaac_wire_message_v4(
            raw,
            self._secret,
            expected_type="ISAAC_CAPTURE_REQUEST_V4",
            model=IsaacCaptureRequestV4,
        )
        self._validate_cycle_identity(request)
        if (
            request.previous_execution_receipt_sha256
            != self.state.previous_execution_receipt_sha256
        ):
            raise ValueError("V4 capture does not bind the previous execution receipt")
        self._uncommitted_backend_operation = "capture"
        response = self.backend.capture(request)
        observation = response.observation
        if (
            response.run_id != request.run_id
            or response.session_id != request.session_id
            or response.decision_index != request.decision_index
            or observation.previous_physical_completed_at_ns != self.state.previous_completed_at_ns
            or observation.association_deployment_sha256
            != self.binding.association_deployment_sha256
            or observation.association_deployment.capture_source_implementation_sha256
            != self.binding.capture_source_implementation_sha256
            or observation.declared_attribute_binding.selector_source_implementation_sha256
            != self.binding.declared_attribute_selector_implementation_sha256
            or observation.observation.declared_target_attribute
            != self.state.declared_target_attribute
            or observation.declared_attribute_binding_sha256
            != self.state.declared_attribute_binding_sha256
        ):
            raise ValueError("real V4 backend capture crosses cycle/deployment")
        current_history = tuple(
            item.model_dump(mode="json") for item in observation.observation.association_history
        )
        previous_history = self.state.previous_association_history
        if previous_history and (
            len(current_history) <= len(previous_history)
            or current_history[: len(previous_history)] != previous_history
        ):
            raise ValueError("V4 association history is not a strict exact extension")
        self.state.active_capture = response
        self.state.previous_association_history = current_history
        self.state.phase = "READY_EXECUTE"
        return sign_isaac_wire_message_v4(
            "ISAAC_CAPTURE_RESPONSE_V4",
            response,
            self._secret,
        )

    def _execute(self, raw: Mapping[str, Any]) -> SignedIsaacWireMessageV4:
        capture = self.state.active_capture
        if self.state.phase != "READY_EXECUTE" or capture is None:
            raise RuntimeError("execute requires exactly one preceding fresh V4 capture")
        _, request = verify_isaac_wire_message_v4(
            raw,
            self._secret,
            expected_type="ISAAC_EXECUTE_REQUEST_V4",
            model=IsaacExecuteRequestV4,
        )
        self._validate_cycle_identity(request)
        if (
            request.observation != capture.observation
            or request.formal_observation_sha256 != capture.formal_observation_sha256
            or tuple(request.executed_intent_history) != self.state.executed_intent_history
        ):
            raise ValueError("V4 execute request is not the active replayed capture")
        independently_mapped = validate_runtime_mapping_v4(
            request.runtime_request,
            request.observation,
            self.registry,
        )
        self.state.phase = "EXECUTING"
        self._uncommitted_backend_operation = "execute"
        response = self.backend.execute(request, self.registry)
        expected_identity = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": request.observation_id,
            "formal_observation_sha256": request.formal_observation_sha256,
            "inference_response_sha256": request.inference_response_sha256,
        }
        if any(
            getattr(response, field) != expected for field, expected in expected_identity.items()
        ):
            raise ValueError("real V4 backend execution response crossed decision cycles")
        self._validate_backend_mapping(independently_mapped, response.mapping)
        if response.bound_plan is not None:
            validate_bound_exact_plan_inputs_v1(
                request=request,
                observation=request.observation,
                mapping=response.mapping,
                plan=response.bound_plan,
            )
        receipt = response.execution_receipts[0]
        if receipt.started_at_ns <= request.observation.captured_at_ns:
            raise ValueError("V4 execution receipt does not follow its fresh observation")
        self.state.previous_execution_receipt_sha256 = receipt.receipt_sha256
        self.state.previous_completed_at_ns = receipt.completed_at_ns
        self.state.active_capture = None

        if response.disposition == "CONTINUE":
            assert response.bundle_execution_receipt_sha256 is not None
            self.state.previous_bundle_execution_receipt_sha256 = (
                response.bundle_execution_receipt_sha256
            )
            # The shared history schema is the exact prefix consumed by the
            # *next* inference request and therefore admits indices 0..6.  A
            # successful decision 7 transitions directly to finalize and has
            # no ninth model request for which it could be a prior item.
            if request.decision_index < 7:
                destination_cell = (
                    response.mapping.destination_resolution.destination_cell
                    if response.mapping.destination_resolution is not None
                    else None
                )
                history_item = PublicExecutedIntentHistoryItemV2(
                    decision_index=request.decision_index,
                    selected_skill=str(response.mapping.canonical_skill),
                    target_track_id=response.mapping.target_track_id,
                    destination_cell=destination_cell,
                    physical_receipt_sha256=receipt.receipt_sha256,
                    execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
                )
                self.state.executed_intent_history = (
                    *self.state.executed_intent_history,
                    history_item,
                )
            self.audit.append(
                "EXACT_EXECUTION_PLAN_EXECUTED_V4",
                {
                    "decision_index": request.decision_index,
                    "bound_plan_sha256": response.bound_plan_sha256,
                    "preflight_receipt_sha256": response.preflight_receipt_sha256,
                    "bundle_execution_receipt_sha256": (response.bundle_execution_receipt_sha256),
                    "operation_kind": receipt.operation_kind,
                },
            )
            self.state.decision_index += 1
            self.state.phase = (
                "READY_FINALIZE" if self.state.decision_index == 8 else "READY_CAPTURE"
            )
        else:
            self.audit.append(
                "ISAAC_V4_TERMINAL_FAILURE_COMMITTED",
                {
                    "decision_index": request.decision_index,
                    "disposition": response.disposition,
                    "execution_receipt_sha256": receipt.receipt_sha256,
                    "physical_execution_may_have_occurred": bool(receipt.robot_actuation_executed),
                },
            )
            self.state.phase = "TERMINAL_FAILURE"
        return sign_isaac_wire_message_v4(
            "ISAAC_EXECUTE_RESPONSE_V4",
            response,
            self._secret,
        )

    def _finalize(self, raw: Mapping[str, Any]) -> SignedIsaacWireMessageV4:
        if self.state.phase != "READY_FINALIZE":
            raise RuntimeError("V4 finalize requires eight successful model operations")
        _, request = verify_isaac_wire_message_v4(
            raw,
            self._secret,
            expected_type="ISAAC_FINALIZE_REQUEST_V4",
            model=IsaacFinalizeRequestV4,
        )
        if (
            request.run_id != self.state.run_id
            or request.session_id != self.state.session_id
            or request.last_execution_receipt_sha256 != self.state.previous_execution_receipt_sha256
            or request.last_bundle_execution_receipt_sha256
            != self.state.previous_bundle_execution_receipt_sha256
        ):
            raise ValueError("V4 finalize differs from its exact eight-cycle session")
        self._uncommitted_backend_operation = "finalize"
        response = self.backend.finalize(request)
        if (
            response.run_id != request.run_id
            or response.session_id != request.session_id
            or response.evaluated_at_ns <= self.state.previous_completed_at_ns
        ):
            raise ValueError("V4 final evaluator is not after the last model operation")
        self.state.phase = "FINALIZED"
        return sign_isaac_wire_message_v4(
            "ISAAC_FINALIZE_RESPONSE_V4",
            response,
            self._secret,
        )

    @staticmethod
    def _validate_backend_mapping(
        independent: RuntimeSkillMappingResultV2,
        actual: RuntimeSkillMappingResultV2,
    ) -> None:
        if _mapping_semantics(independent) != _mapping_semantics(actual):
            raise ValueError("V4 backend mapping differs from independent registry replay")
        if independent.status == "INVALID":
            if (
                actual.status != "INVALID"
                or actual.rejection_reason != independent.rejection_reason
                or not actual.fallback_required
                or actual.execution_attribution != "NO_PHYSICAL_EXECUTION"
            ):
                raise ValueError("V4 backend changed an independently invalid mapping")
            return
        if actual.status == "VALID":
            if actual.fallback_required:
                raise ValueError("V4 backend VALID mapping requests fallback")
            return
        if (
            actual.rejection_reason not in _DYNAMIC_REJECTIONS
            or not actual.fallback_required
            or actual.execution_attribution != "NO_PHYSICAL_EXECUTION"
            or not any(
                item.get("status") == "INVALID"
                and item.get("gate") in {"ik", "collision", "controller", "safety", "exact_plan"}
                for item in actual.gate_trace
            )
        ):
            raise ValueError("V4 backend dynamic rejection lacks a real pre-execution gate")

    def _validate_cycle_identity(
        self,
        request: IsaacCaptureRequestV4 | IsaacExecuteRequestV4,
    ) -> None:
        if (
            request.run_id != self.state.run_id
            or request.session_id != self.state.session_id
            or request.decision_index != self.state.decision_index
        ):
            raise ValueError("request run/session/index differs from active Isaac V4 cycle")
