"""Persistent four-API state machine for one real M2C Isaac session.

This transport layer never implements physics and never creates a physical
receipt.  It authenticates messages, enforces the exact start -> eight
capture/execute cycles -> finalize transaction, and durably records every
accepted or rejected request.  A separately frozen Isaac backend is solely
responsible for fresh RGB-D, independent runtime remapping, physical gates,
controller execution, and final evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Mapping, Protocol
import uuid

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FORMAL_ISAAC_CAPTURE_PATH,
    FORMAL_ISAAC_EXECUTE_PATH,
    FORMAL_ISAAC_FINALIZE_PATH,
    FORMAL_ISAAC_START_PATH,
    IsaacCaptureRequestV2,
    IsaacCaptureResponseV2,
    IsaacEndpointBindingV2,
    IsaacExecuteRequestV2,
    IsaacExecuteResponseV2,
    IsaacFinalizeRequestV2,
    IsaacFinalizeResponseV2,
    IsaacStartRequestV2,
    IsaacStartResponseV2,
    SignedWireMessageV2,
    canonical_json_bytes,
    canonical_sha256,
    sign_wire_message,
    verify_wire_message,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import RuntimeSkillRegistryV2


class RealIsaacBackendV2(Protocol):
    """The only object authorized to return real-Isaac typed responses."""

    def start(self, request: IsaacStartRequestV2) -> IsaacStartResponseV2: ...

    def capture(self, request: IsaacCaptureRequestV2) -> IsaacCaptureResponseV2: ...

    def execute(
        self,
        request: IsaacExecuteRequestV2,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV2: ...

    def finalize(self, request: IsaacFinalizeRequestV2) -> IsaacFinalizeResponseV2: ...


class AppendOnlyIsaacAuditLogV2:
    """Durable create-only service/session JSONL logs.

    Each append is flushed with ``fsync`` before a response is released to the
    caller.  A process crash or host disconnect therefore cannot erase an
    already performed physical action from the labserver-side journal.
    """

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise NotADirectoryError(root)
        self.root = root
        self._lock = threading.Lock()
        self._sequence = 0
        self._session_path: Path | None = None
        self.service_id = uuid.uuid4().hex
        self.service_path = root / f"service-{self.service_id}.jsonl"
        self._create_exclusive(self.service_path)
        self.append(
            "SERVICE_STARTED",
            {
                "service_id": self.service_id,
                "formal_evidence": False,
                "physical_execution_performed": False,
            },
        )

    @staticmethod
    def _create_exclusive(path: Path) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)

    def begin_session(self, *, run_id: str, request_sha256: str) -> Path:
        with self._lock:
            if self._session_path is not None:
                raise RuntimeError("audit log already owns an Isaac session")
            identity = canonical_sha256(
                {
                    "request_sha256": request_sha256,
                    "run_id": run_id,
                    "service_id": self.service_id,
                }
            )
            path = self.root / f"session-{identity}.jsonl"
            self._create_exclusive(path)
            self._session_path = path
        self.append(
            "SESSION_AUDIT_CREATED",
            {
                "request_sha256": request_sha256,
                "run_id": run_id,
                "session_audit_path": str(path),
            },
        )
        return path

    def append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            self._sequence += 1
            record = {
                "schema_version": "FormalIsaacAuditEventV2",
                "sequence": self._sequence,
                "recorded_at_ns": time.time_ns(),
                "event_type": event_type,
                "payload": dict(payload),
            }
            line = canonical_json_bytes(record) + b"\n"
            paths = [self.service_path]
            if self._session_path is not None:
                paths.append(self._session_path)
            for path in paths:
                descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
                try:
                    os.write(descriptor, line)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)


@dataclass
class _SessionStateV2:
    phase: str = "NEW"
    run_id: str | None = None
    session_id: str | None = None
    decision_index: int = 0
    previous_receipt_sha256: str | None = None
    previous_completed_at_ns: int = 0
    active_capture: IsaacCaptureResponseV2 | None = None


class FormalIsaacEndpointStateMachineV2:
    """Authenticate and serialize one persistent real-physics episode."""

    def __init__(
        self,
        *,
        secret: bytes,
        endpoint_binding: IsaacEndpointBindingV2,
        registry: RuntimeSkillRegistryV2,
        backend: RealIsaacBackendV2,
        audit: AppendOnlyIsaacAuditLogV2,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("formal endpoint HMAC key must contain at least 32 bytes")
        self._secret = secret
        self.binding = endpoint_binding
        self.registry = registry
        self.backend = backend
        self.audit = audit
        self.state = _SessionStateV2()
        self._lock = threading.Lock()
        self._poisoned = False

    @property
    def session_audit_path(self) -> Path | None:
        return self.audit._session_path

    def handle(self, path: str, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Handle one of the four signed APIs without concurrent Kit calls."""

        with self._lock:
            if self._poisoned:
                raise RuntimeError("Isaac session is poisoned after an audit/backend failure")
            try:
                # Re-check every API operation.  A service/session started
                # before midnight cannot capture or actuate after the freeze.
                require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
                self.audit.append(
                    "WIRE_REQUEST_RECEIVED",
                    {"path": path, "signed_wire": dict(raw)},
                )
                response = self._dispatch(path, raw)
                dumped = response.model_dump(mode="json")
                # Persist the complete signed response before HTTP can expose it.
                self.audit.append(
                    "WIRE_RESPONSE_COMMITTED",
                    {"path": path, "signed_wire": dumped},
                )
                return dumped
            except Exception as exc:
                physical_may_have_executed = bool(
                    path == FORMAL_ISAAC_EXECUTE_PATH and self.state.phase == "EXECUTING"
                )
                try:
                    self.audit.append(
                        "WIRE_REQUEST_REJECTED",
                        {
                            "path": path,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "physical_evidence_accepted": False,
                            "physical_execution_may_have_occurred": (physical_may_have_executed),
                        },
                    )
                except Exception:
                    self._poisoned = True
                if physical_may_have_executed:
                    # A backend exception after actuation makes retry unsafe:
                    # the same model action could otherwise execute twice.
                    self._poisoned = True
                raise

    def _dispatch(
        self,
        path: str,
        raw: Mapping[str, Any],
    ) -> SignedWireMessageV2:
        if path == FORMAL_ISAAC_START_PATH:
            return self._start(raw)
        if path == FORMAL_ISAAC_CAPTURE_PATH:
            return self._capture(raw)
        if path == FORMAL_ISAAC_EXECUTE_PATH:
            return self._execute(raw)
        if path == FORMAL_ISAAC_FINALIZE_PATH:
            return self._finalize(raw)
        raise ValueError(f"unknown formal Isaac path: {path}")

    def _start(self, raw: Mapping[str, Any]) -> SignedWireMessageV2:
        if self.state.phase != "NEW":
            raise RuntimeError("Isaac start is allowed exactly once")
        _, request = verify_wire_message(
            raw,
            expected_type="ISAAC_START_REQUEST",
            payload_model=IsaacStartRequestV2,
            secret=self._secret,
        )
        request_sha = canonical_sha256(request)
        if request.endpoint_binding_sha256 != canonical_sha256(self.binding):
            raise ValueError("start request differs from this endpoint deployment binding")
        self.audit.begin_session(run_id=request.run_id, request_sha256=request_sha)
        self.audit.append(
            "ISAAC_START_ACCEPTED_FOR_BACKEND",
            {"request": request.model_dump(mode="json")},
        )
        response = self.backend.start(request)
        if (
            response.run_id != request.run_id
            or response.start_request_sha256 != request_sha
            or response.endpoint_binding_sha256 != canonical_sha256(self.binding)
            or response.implementation_sha256 != self.binding.implementation_sha256
            or response.physical_backend_sha256 != self.binding.physical_backend_sha256
        ):
            raise ValueError("real backend start response differs from frozen binding")
        self.state = _SessionStateV2(
            phase="READY_CAPTURE",
            run_id=request.run_id,
            session_id=response.session_id,
            decision_index=0,
            previous_completed_at_ns=response.failure_observed_at_ns,
        )
        return sign_wire_message("ISAAC_START_RESPONSE", response, self._secret)

    def _capture(self, raw: Mapping[str, Any]) -> SignedWireMessageV2:
        if self.state.phase != "READY_CAPTURE":
            raise RuntimeError("capture is not the next Isaac session operation")
        _, request = verify_wire_message(
            raw,
            expected_type="ISAAC_CAPTURE_REQUEST",
            payload_model=IsaacCaptureRequestV2,
            secret=self._secret,
        )
        self._validate_cycle_identity(request)
        if request.previous_physical_receipt_sha256 != self.state.previous_receipt_sha256:
            raise ValueError("capture does not bind the previous physical receipt")
        response = self.backend.capture(request)
        if (
            response.run_id != request.run_id
            or response.session_id != request.session_id
            or response.decision_index != request.decision_index
            or response.observation.previous_physical_completed_at_ns
            != self.state.previous_completed_at_ns
            or response.public_roles.selector_contract_sha256
            != self.binding.public_role_selector_sha256
        ):
            raise ValueError("real backend capture is not the next fresh cycle")
        self.state.active_capture = response
        self.state.phase = "READY_EXECUTE"
        return sign_wire_message("ISAAC_CAPTURE_RESPONSE", response, self._secret)

    def _execute(self, raw: Mapping[str, Any]) -> SignedWireMessageV2:
        if self.state.phase != "READY_EXECUTE" or self.state.active_capture is None:
            raise RuntimeError("execute requires exactly one preceding fresh capture")
        _, request = verify_wire_message(
            raw,
            expected_type="ISAAC_EXECUTE_REQUEST",
            payload_model=IsaacExecuteRequestV2,
            secret=self._secret,
        )
        self._validate_cycle_identity(request)
        capture = self.state.active_capture
        if (
            request.observation_id != capture.observation.observation_id
            or request.capture_receipt_sha256 != capture.observation.capture_receipt_sha256
        ):
            raise ValueError("execute request is not bound to the active public capture")
        self.state.phase = "EXECUTING"
        response = self.backend.execute(request, self.registry)
        if (
            response.run_id != request.run_id
            or response.session_id != request.session_id
            or response.decision_index != request.decision_index
            or response.observation_id != request.observation_id
            or response.inference_response_sha256 != request.inference_response_sha256
        ):
            raise ValueError("real backend execution response crossed decision cycles")
        receipt = response.physical_skill_receipts[0]
        if response.mapping.status == "VALID":
            plan_sha = response.exact_execution_plan_sha256
            if plan_sha is None or response.executed_exact_execution_plan_sha256 != plan_sha:
                raise ValueError("real backend did not bind execution to its exact plan")
            self.audit.append(
                "EXACT_EXECUTION_PLAN_EXECUTED",
                {
                    "decision_index": request.decision_index,
                    "exact_execution_plan_sha256": plan_sha,
                    "phase_count": len(response.exact_execution_plan.phases),
                },
            )
        else:
            if receipt.physically_executed:
                raise ValueError(
                    "INVALID mapping physically executed without a frozen B0 fallback wrapper"
                )
            self.audit.append(
                "INVALID_MODEL_ACTION_FAILED_CLOSED_NO_PHYSICAL_FALLBACK",
                {
                    "decision_index": request.decision_index,
                    "fallback_reason": receipt.fallback_reason,
                    "physically_executed": False,
                },
            )
        self.state.previous_receipt_sha256 = receipt.receipt_sha256
        self.state.previous_completed_at_ns = receipt.completed_at_ns
        self.state.active_capture = None
        receipt_passed = bool(
            receipt.physically_executed
            and all(
                getattr(receipt, gate_name) == "PASS"
                for gate_name in (
                    "schema_gate",
                    "stale_track_gate",
                    "frame_unit_gate",
                    "ik_gate",
                    "collision_gate",
                    "controller_gate",
                    "safety_gate",
                )
            )
            and not receipt.collision_or_safety_violation
            and receipt.fallback_reason is None
            and receipt.execution_source == "MODEL_SELECTED_REGISTERED_SKILL"
            and response.mapping.status == "VALID"
            and not response.mapping.fallback_required
        )
        if receipt_passed:
            self.state.decision_index += 1
            self.state.phase = (
                "READY_FINALIZE" if self.state.decision_index == 8 else "READY_CAPTURE"
            )
        else:
            # The signed response is still returned and durably recorded so the
            # host can retain the actual failure receipt.  The persistent Isaac
            # session is terminal after that physical action: no retry, B0
            # continuation, fresh capture, or formal finalize may follow.
            self.state.phase = "ABORTED_PHYSICAL_FAILURE"
        return sign_wire_message("ISAAC_EXECUTE_RESPONSE", response, self._secret)

    def _finalize(self, raw: Mapping[str, Any]) -> SignedWireMessageV2:
        if self.state.phase != "READY_FINALIZE":
            raise RuntimeError("finalize requires eight capture/execute cycles")
        _, request = verify_wire_message(
            raw,
            expected_type="ISAAC_FINALIZE_REQUEST",
            payload_model=IsaacFinalizeRequestV2,
            secret=self._secret,
        )
        if (
            request.run_id != self.state.run_id
            or request.session_id != self.state.session_id
            or request.last_physical_receipt_sha256 != self.state.previous_receipt_sha256
        ):
            raise ValueError("finalize is not bound to this eight-cycle session")
        response = self.backend.finalize(request)
        if (
            response.run_id != request.run_id
            or response.session_id != request.session_id
            or response.evaluated_at_ns <= self.state.previous_completed_at_ns
        ):
            raise ValueError("final evaluator response is not after the last action")
        self.state.phase = "FINALIZED"
        return sign_wire_message("ISAAC_FINALIZE_RESPONSE", response, self._secret)

    def _validate_cycle_identity(
        self,
        request: IsaacCaptureRequestV2 | IsaacExecuteRequestV2,
    ) -> None:
        if (
            request.run_id != self.state.run_id
            or request.session_id != self.state.session_id
            or request.decision_index != self.state.decision_index
        ):
            raise ValueError("request run/session/index differs from active Isaac cycle")


def read_json_object(raw: bytes) -> dict[str, Any]:
    """Strict HTTP JSON helper kept independent of any web framework."""

    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("formal Isaac request must be one JSON object")
    return value
