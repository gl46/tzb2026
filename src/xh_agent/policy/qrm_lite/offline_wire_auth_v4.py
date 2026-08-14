"""Host-local HMAC replay for terminalized formal V4 episodes.

V4 episodes may terminate after any model decision.  This verifier therefore
derives exact Qwen/Isaac envelope counts from the replayed formal evidence
instead of assuming the V2 fixed 16/36 shape.  Each host still receives only
its own symmetric key; no signature, trust root, or cross-host key export is
part of the receipt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_host_v4 import (
    CompletionKindV4,
    M2CFormalSplitRunnerEvidenceV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_json_bytes,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_ISAAC_CAPTURE_PATH_V4,
    FORMAL_ISAAC_EXECUTE_PATH_V4,
    FORMAL_ISAAC_FINALIZE_PATH_V4,
    FORMAL_ISAAC_START_PATH_V4,
    FORMAL_WIRE_PROTOCOL_V4,
    IsaacCaptureRequestV4,
    IsaacCaptureResponseV4,
    IsaacExecuteRequestV4,
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacFinalizeResponseV4,
    IsaacStartRequestV4,
    IsaacStartResponseV4,
    validate_inference_response_binding_v4,
    verify_inference_request_v4,
    verify_inference_response_v4,
    verify_isaac_wire_message_v4,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    WireChallengeConsumptionReceiptV1,
    wire_challenge_consumption_path,
)


HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH = "src/xh_agent/policy/qrm_lite/offline_wire_auth_v4.py"
HostRoleV4 = Literal["NODE2_QWEN", "LABSERVER_ISAAC"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HostWireHMACVerificationCoreV4(StrictModel):
    schema_version: Literal["M2CHostWireHMACVerificationCoreV4"] = (
        "M2CHostWireHMACVerificationCoreV4"
    )
    host_role: HostRoleV4
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_id: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_wire_transcript_sha256: str = Field(pattern=SHA256_PATTERN)
    service_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    session_audit_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    envelope_set_sha256: str = Field(pattern=SHA256_PATTERN)
    completion_kind: CompletionKindV4
    decision_count: int = Field(ge=1, le=8)
    authenticated_envelope_count: int = Field(ge=2)
    request_envelope_count: int = Field(ge=1)
    response_envelope_count: int = Field(ge=1)
    verifier_implementation_path: Literal[HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH] = (
        HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH
    )
    verifier_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    audit_cleanly_stopped: Literal[True] = True
    all_hmac_valid: Literal[True] = True
    hmac_secret_exported: Literal[False] = False
    hmac_secret_persisted_in_receipt: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def counts_are_derived_from_terminal_shape(self) -> "HostWireHMACVerificationCoreV4":
        if self.host_role == "NODE2_QWEN":
            pairs = self.decision_count
            session_expected = False
        else:
            pairs = 1 + (2 * self.decision_count) + (self.completion_kind == "FINALIZED")
            session_expected = True
        observed = (
            self.authenticated_envelope_count,
            self.request_envelope_count,
            self.response_envelope_count,
            self.session_audit_sha256 is not None,
        )
        if observed != (2 * pairs, pairs, pairs, session_expected):
            raise ValueError("formal V4 host HMAC count/session contract differs")
        if self.completion_kind == "FINALIZED" and self.decision_count != 8:
            raise ValueError("formal V4 finalized receipt does not cover eight decisions")
        return self


class HostWireHMACVerificationReceiptV4(StrictModel):
    schema_version: Literal["M2CHostWireHMACVerificationReceiptV4"] = (
        "M2CHostWireHMACVerificationReceiptV4"
    )
    core: HostWireHMACVerificationCoreV4


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_host_secret(secret: bytes) -> None:
    if len(secret) < 32:
        raise ValueError("formal V4 host-local HMAC key must contain at least 32 bytes")


def _parse_audit(
    data: bytes,
    *,
    schema: str,
    label: str,
    require_sequence_one: bool,
) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise ValueError(f"{label} is not newline-terminated canonical JSONL")
    lines = data.splitlines()
    records = [json.loads(line) for line in lines]
    if not records or any(not isinstance(item, dict) for item in records):
        raise ValueError(f"{label} is empty or contains a non-object")
    first = records[0].get("sequence")
    if not isinstance(first, int) or first <= 0 or (require_sequence_one and first != 1):
        raise ValueError(f"{label} first sequence differs")
    previous_time = 0
    for offset, (record, line) in enumerate(zip(records, lines)):
        recorded_at_ns = record.get("recorded_at_ns")
        if (
            set(record) != {"schema_version", "sequence", "recorded_at_ns", "event_type", "payload"}
            or record.get("schema_version") != schema
            or record.get("sequence") != first + offset
            or not isinstance(recorded_at_ns, int)
            or recorded_at_ns <= 0
            or recorded_at_ns < previous_time
            or not isinstance(record.get("event_type"), str)
            or not isinstance(record.get("payload"), dict)
            or canonical_json_bytes(record) != line
        ):
            raise ValueError(f"{label} is not canonical contiguous ordered JSONL")
        previous_time = recorded_at_ns
    if any(item.get("event_type") == "WIRE_REQUEST_REJECTED" for item in records):
        raise ValueError(f"{label} contains a rejected request")
    return records


def _wire_events(
    records: list[dict[str, Any]],
    *,
    expected_paths: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    wire = [
        item
        for item in records
        if item.get("event_type") in {"WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED"}
    ]
    expected_types = [
        event
        for _ in expected_paths
        for event in ("WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED")
    ]
    if [item.get("event_type") for item in wire] != expected_types:
        raise ValueError("formal V4 wire audit request/response order differs")
    expected_wire_paths = [path for path in expected_paths for _ in range(2)]
    if [item.get("payload", {}).get("path") for item in wire] != expected_wire_paths:
        raise ValueError("formal V4 wire audit path order differs")
    envelopes = [item.get("payload", {}).get("signed_wire") for item in wire]
    if any(not isinstance(item, dict) for item in envelopes):
        raise ValueError("formal V4 wire audit contains a missing envelope")
    transcript = [
        {
            "event_type": item["event_type"],
            "path": item["payload"]["path"],
            "signed_wire": item["payload"]["signed_wire"],
        }
        for item in wire
    ]
    return envelopes[0::2], envelopes[1::2], transcript


def _event_between(
    records: list[dict[str, Any]],
    *,
    event_type: str,
    after_sequence: int,
    before_sequence: int,
) -> dict[str, Any]:
    matches = [
        item
        for item in records
        if item.get("event_type") == event_type
        and after_sequence < item["sequence"] < before_sequence
    ]
    if len(matches) != 1:
        raise ValueError(f"formal V4 Isaac {event_type} lifecycle event differs")
    return matches[0]


def _formal_and_consumption(
    formal_bytes: bytes,
    consumption_bytes: bytes,
) -> tuple[M2CFormalSplitRunnerEvidenceV4, WireChallengeConsumptionReceiptV1]:
    formal = M2CFormalSplitRunnerEvidenceV4.model_validate_json(formal_bytes)
    consumption = WireChallengeConsumptionReceiptV1.model_validate_json(consumption_bytes)
    if _sha256(consumption_bytes) != formal.challenge_consumption_receipt_sha256:
        raise ValueError("formal V4 challenge consumption receipt SHA-256 differs")
    if (
        consumption.run_id != formal.run_id
        or consumption.challenge_nonce != formal.challenge_nonce
        or consumption.matched_key != formal.matched_key
        or consumption.scene_seed != formal.scene_seed
        or consumption.failure_seed != formal.failure_seed
        or consumption.consumption_id != formal.challenge_consumption_id
        or Path(formal.challenge_consumption_receipt_path)
        != wire_challenge_consumption_path(
            Path(consumption.ledger_root),
            consumption.challenge_nonce,
        )
    ):
        raise ValueError("formal V4 challenge consumption identity differs")
    return formal, consumption


def _first_wire_time(records: list[dict[str, Any]]) -> int:
    first = next(
        (item for item in records if item.get("event_type") == "WIRE_REQUEST_RECEIVED"),
        None,
    )
    if first is None:
        raise ValueError("formal V4 audit has no endpoint request")
    return int(first["recorded_at_ns"])


def verify_node2_qwen_transcript_v4(
    formal_bytes: bytes,
    consumption_bytes: bytes,
    audit_bytes: bytes,
    *,
    secret: bytes,
) -> tuple[M2CFormalSplitRunnerEvidenceV4, str]:
    _require_host_secret(secret)
    formal, consumption = _formal_and_consumption(formal_bytes, consumption_bytes)
    records = _parse_audit(
        audit_bytes,
        schema="FormalQwenAuditEventV4",
        label="formal V4 Qwen service audit",
        require_sequence_one=True,
    )
    if consumption.consumed_at_ns >= _first_wire_time(records):
        raise ValueError("formal V4 challenge was not consumed before Qwen contact")
    paths = [FORMAL_INFERENCE_PATH_V4] * len(formal.wire_cycles)
    requests, responses, transcript = _wire_events(records, expected_paths=paths)
    expected_requests = [
        item.inference_request.model_dump(mode="json") for item in formal.wire_cycles
    ]
    expected_responses = [
        item.inference_response.model_dump(mode="json") for item in formal.wire_cycles
    ]
    if requests != expected_requests or responses != expected_responses:
        raise ValueError("formal V4 Qwen audit differs from formal evidence")
    for index, (request_raw, response_raw) in enumerate(zip(requests, responses)):
        request = verify_inference_request_v4(request_raw, secret)
        response = verify_inference_response_v4(response_raw, secret)
        validate_inference_response_binding_v4(request.payload, response.payload)
        if (
            request.payload.run_id != formal.run_id
            or request.payload.challenge_nonce != formal.challenge_nonce
            or request.payload.decision_index != index
        ):
            raise ValueError("formal V4 Qwen envelope identity differs")
    expected_event_types = [
        "SERVICE_STARTED",
        *[
            event
            for _ in formal.wire_cycles
            for event in ("WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED")
        ],
        *(["SERVICE_COMPLETED"] if len(formal.wire_cycles) == 8 else []),
        "SERVICE_STOPPED",
    ]
    if [item.get("event_type") for item in records] != expected_event_types:
        raise ValueError("formal V4 Qwen service lifecycle differs")
    start = records[0].get("payload", {})
    service_id = start.get("service_id")
    if (
        start
        != {
            "service_id": service_id,
            "path": FORMAL_INFERENCE_PATH_V4,
            "protocol": FORMAL_WIRE_PROTOCOL_V4,
            "architecture_revision": "M2C_Q012_V4",
            "expected_decisions": 8,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        or not isinstance(service_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", service_id) is None
    ):
        raise ValueError("formal V4 Qwen service start differs")
    if len(formal.wire_cycles) == 8:
        completed = records[-2].get("payload", {})
        if completed != {
            "service_id": service_id,
            "run_id": formal.run_id,
            "protocol": FORMAL_WIRE_PROTOCOL_V4,
            "responses_committed": 8,
            "formal_evidence_complete": True,
        }:
            raise ValueError("formal V4 Qwen completion event differs")
    stopped = records[-1].get("payload", {})
    if stopped != {
        "service_id": service_id,
        "run_id": formal.run_id,
        "protocol": FORMAL_WIRE_PROTOCOL_V4,
        "responses_committed": len(formal.wire_cycles),
        "completed": len(formal.wire_cycles) == 8,
        "poisoned": False,
        "rejections_recorded": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }:
        raise ValueError("formal V4 Qwen service stop is not clean")
    return formal, canonical_sha256(transcript)


def _isaac_paths(formal: M2CFormalSplitRunnerEvidenceV4) -> list[str]:
    paths = [FORMAL_ISAAC_START_PATH_V4]
    for _ in formal.wire_cycles:
        paths.extend((FORMAL_ISAAC_CAPTURE_PATH_V4, FORMAL_ISAAC_EXECUTE_PATH_V4))
    if formal.completion_kind == "FINALIZED":
        paths.append(FORMAL_ISAAC_FINALIZE_PATH_V4)
    return paths


def _verify_isaac_hmac_envelopes(
    requests: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    *,
    decision_count: int,
    finalized: bool,
    secret: bytes,
) -> tuple[list[BaseModel], list[BaseModel]]:
    request_specs: list[tuple[str, type[BaseModel]]] = [
        ("ISAAC_START_REQUEST_V4", IsaacStartRequestV4)
    ]
    response_specs: list[tuple[str, type[BaseModel]]] = [
        ("ISAAC_START_RESPONSE_V4", IsaacStartResponseV4)
    ]
    for _ in range(decision_count):
        request_specs.extend(
            [
                ("ISAAC_CAPTURE_REQUEST_V4", IsaacCaptureRequestV4),
                ("ISAAC_EXECUTE_REQUEST_V4", IsaacExecuteRequestV4),
            ]
        )
        response_specs.extend(
            [
                ("ISAAC_CAPTURE_RESPONSE_V4", IsaacCaptureResponseV4),
                ("ISAAC_EXECUTE_RESPONSE_V4", IsaacExecuteResponseV4),
            ]
        )
    if finalized:
        request_specs.append(("ISAAC_FINALIZE_REQUEST_V4", IsaacFinalizeRequestV4))
        response_specs.append(("ISAAC_FINALIZE_RESPONSE_V4", IsaacFinalizeResponseV4))
    typed_requests = [
        verify_isaac_wire_message_v4(
            raw,
            secret,
            expected_type=message_type,
            model=model,
        )[1]
        for raw, (message_type, model) in zip(requests, request_specs)
    ]
    typed_responses = [
        verify_isaac_wire_message_v4(
            raw,
            secret,
            expected_type=message_type,
            model=model,
        )[1]
        for raw, (message_type, model) in zip(responses, response_specs)
    ]
    return typed_requests, typed_responses


def verify_labserver_isaac_transcript_v4(
    formal_bytes: bytes,
    consumption_bytes: bytes,
    service_bytes: bytes,
    session_bytes: bytes,
    *,
    secret: bytes,
) -> tuple[M2CFormalSplitRunnerEvidenceV4, str]:
    _require_host_secret(secret)
    formal, consumption = _formal_and_consumption(formal_bytes, consumption_bytes)
    service = _parse_audit(
        service_bytes,
        schema="FormalIsaacAuditEventV2",
        label="formal V4 Isaac service audit",
        require_sequence_one=True,
    )
    session = _parse_audit(
        session_bytes,
        schema="FormalIsaacAuditEventV2",
        label="formal V4 Isaac session audit",
        require_sequence_one=False,
    )
    if consumption.consumed_at_ns >= _first_wire_time(service):
        raise ValueError("formal V4 challenge was not consumed before Isaac contact")
    offset = next((index for index, item in enumerate(service) if item == session[0]), None)
    if offset is None or service[offset:] != session:
        raise ValueError("formal V4 Isaac session audit is not the exact service suffix")
    if session[0].get("event_type") != "SESSION_AUDIT_CREATED":
        raise ValueError("formal V4 Isaac session audit does not begin at creation")
    paths = _isaac_paths(formal)
    requests, responses, transcript = _wire_events(service, expected_paths=paths)
    expected_requests = [formal.start_request.model_dump(mode="json")]
    expected_responses = [formal.start_response.model_dump(mode="json")]
    for cycle in formal.wire_cycles:
        expected_requests.extend(
            [
                cycle.capture_request.model_dump(mode="json"),
                cycle.execute_request.model_dump(mode="json"),
            ]
        )
        expected_responses.extend(
            [
                cycle.capture_response.model_dump(mode="json"),
                cycle.execute_response.model_dump(mode="json"),
            ]
        )
    if formal.finalize_request is not None and formal.finalize_response is not None:
        expected_requests.append(formal.finalize_request.model_dump(mode="json"))
        expected_responses.append(formal.finalize_response.model_dump(mode="json"))
    if requests != expected_requests or responses != expected_responses:
        raise ValueError("formal V4 Isaac audit differs from formal evidence")
    typed_requests, typed_responses = _verify_isaac_hmac_envelopes(
        requests,
        responses,
        decision_count=len(formal.wire_cycles),
        finalized=formal.completion_kind == "FINALIZED",
        secret=secret,
    )
    start_request = typed_requests[0]
    if not isinstance(start_request, IsaacStartRequestV4):
        raise TypeError("formal V4 Isaac start request was not typed")
    started = service[0].get("payload", {})
    service_id = started.get("service_id")
    if (
        service[0].get("event_type") != "SERVICE_STARTED"
        or not isinstance(service_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", service_id) is None
        or started
        != {
            "service_id": service_id,
            "formal_evidence": False,
            "physical_execution_performed": False,
        }
        or service[-1].get("event_type") != "SERVICE_STOPPED"
        or service[-1].get("payload") != {"clean_shutdown": True}
        or sum(item.get("event_type") == "SERVICE_STARTED" for item in service) != 1
        or sum(item.get("event_type") == "SERVICE_STOPPED" for item in service) != 1
    ):
        raise ValueError("formal V4 Isaac service is not cleanly stopped")
    ready = [item for item in service if item.get("event_type") == "HTTP_SERVER_READY_V4"]
    if (
        len(ready) != 1
        or ready[0]["sequence"]
        >= next(
            item["sequence"]
            for item in service
            if item.get("event_type") == "WIRE_REQUEST_RECEIVED"
        )
        or set(ready[0].get("payload", {}))
        != {"listen_host", "listen_port", "formal_execution_started"}
        or not isinstance(ready[0]["payload"]["listen_host"], str)
        or not isinstance(ready[0]["payload"]["listen_port"], int)
        or ready[0]["payload"]["formal_execution_started"] is not False
    ):
        raise ValueError("formal V4 Isaac HTTP service was not ready before contact")
    allowed_event_types = {
        "SERVICE_STARTED",
        "HTTP_SERVER_READY_V4",
        "WIRE_REQUEST_RECEIVED",
        "SESSION_AUDIT_CREATED",
        "ISAAC_V4_START_ACCEPTED_FOR_BACKEND",
        "WIRE_RESPONSE_COMMITTED",
        "EXACT_EXECUTION_PLAN_EXECUTED_V4",
        "ISAAC_V4_TERMINAL_FAILURE_COMMITTED",
        "HTTP_ACCESS",
        "SERVICE_STOPPED",
    }
    if any(item.get("event_type") not in allowed_event_types for item in service):
        raise ValueError("formal V4 Isaac audit contains an unknown lifecycle event")
    wire_records = [
        item
        for item in service
        if item.get("event_type") in {"WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED"}
    ]
    start_received, start_committed = wire_records[:2]
    session_created = _event_between(
        service,
        event_type="SESSION_AUDIT_CREATED",
        after_sequence=start_received["sequence"],
        before_sequence=start_committed["sequence"],
    )
    session_identity = canonical_sha256(
        {
            "request_sha256": canonical_sha256(start_request),
            "run_id": formal.run_id,
            "service_id": service_id,
        }
    )
    session_path = session_created.get("payload", {}).get("session_audit_path")
    if (
        session_created.get("payload")
        != {
            "request_sha256": canonical_sha256(start_request),
            "run_id": formal.run_id,
            "session_audit_path": session_path,
        }
        or not isinstance(session_path, str)
        or Path(session_path).name != (f"session-{session_identity}.jsonl")
    ):
        raise ValueError("formal V4 Isaac session creation identity differs")
    accepted = _event_between(
        service,
        event_type="ISAAC_V4_START_ACCEPTED_FOR_BACKEND",
        after_sequence=start_received["sequence"],
        before_sequence=start_committed["sequence"],
    )
    if accepted.get("payload") != {"request": start_request.model_dump(mode="json")}:
        raise ValueError("formal V4 Isaac backend start acceptance differs")

    execute_responses = [
        item for item in typed_responses if isinstance(item, IsaacExecuteResponseV4)
    ]
    execute_wire_indices = [
        index
        for index, item in enumerate(wire_records)
        if item.get("payload", {}).get("path") == FORMAL_ISAAC_EXECUTE_PATH_V4
        and item.get("event_type") == "WIRE_REQUEST_RECEIVED"
    ]
    for response, wire_index in zip(execute_responses, execute_wire_indices):
        request_event = wire_records[wire_index]
        response_event = wire_records[wire_index + 1]
        receipt = response.execution_receipts[0]
        if response.disposition == "CONTINUE":
            event_type = "EXACT_EXECUTION_PLAN_EXECUTED_V4"
            expected_payload = {
                "decision_index": response.decision_index,
                "bound_plan_sha256": response.bound_plan_sha256,
                "preflight_receipt_sha256": response.preflight_receipt_sha256,
                "bundle_execution_receipt_sha256": response.bundle_execution_receipt_sha256,
                "operation_kind": receipt.operation_kind,
            }
        else:
            event_type = "ISAAC_V4_TERMINAL_FAILURE_COMMITTED"
            expected_payload = {
                "decision_index": response.decision_index,
                "disposition": response.disposition,
                "execution_receipt_sha256": receipt.receipt_sha256,
                "physical_execution_may_have_occurred": bool(receipt.robot_actuation_executed),
            }
        lifecycle = _event_between(
            service,
            event_type=event_type,
            after_sequence=request_event["sequence"],
            before_sequence=response_event["sequence"],
        )
        if lifecycle.get("payload") != expected_payload:
            raise ValueError("formal V4 Isaac execution lifecycle payload differs")
    expected_exact = sum(item.disposition == "CONTINUE" for item in execute_responses)
    expected_terminal = len(execute_responses) - expected_exact
    if (
        sum(item.get("event_type") == "EXACT_EXECUTION_PLAN_EXECUTED_V4" for item in service)
        != expected_exact
        or sum(item.get("event_type") == "ISAAC_V4_TERMINAL_FAILURE_COMMITTED" for item in service)
        != expected_terminal
    ):
        raise ValueError("formal V4 Isaac execution lifecycle count differs")
    return formal, canonical_sha256(transcript)


def build_hmac_verification_receipt_v4(
    *,
    host_role: HostRoleV4,
    formal_evidence_bytes: bytes,
    challenge_consumption_bytes: bytes,
    service_audit_bytes: bytes,
    session_audit_bytes: bytes | None,
    secret: bytes,
    verifier_implementation_bytes: bytes,
) -> HostWireHMACVerificationReceiptV4:
    if host_role == "NODE2_QWEN":
        if session_audit_bytes is not None:
            raise ValueError("formal V4 node2 verifier may not accept an Isaac session audit")
        formal, envelope_set_sha256 = verify_node2_qwen_transcript_v4(
            formal_evidence_bytes,
            challenge_consumption_bytes,
            service_audit_bytes,
            secret=secret,
        )
    else:
        if session_audit_bytes is None:
            raise ValueError("formal V4 labserver verifier requires a session audit")
        formal, envelope_set_sha256 = verify_labserver_isaac_transcript_v4(
            formal_evidence_bytes,
            challenge_consumption_bytes,
            service_audit_bytes,
            session_audit_bytes,
            secret=secret,
        )
    pairs = len(formal.wire_cycles) if host_role == "NODE2_QWEN" else len(_isaac_paths(formal))
    core = HostWireHMACVerificationCoreV4(
        host_role=host_role,
        run_id=formal.run_id,
        challenge_nonce=formal.challenge_nonce,
        challenge_consumption_id=formal.challenge_consumption_id,
        challenge_consumption_receipt_sha256=formal.challenge_consumption_receipt_sha256,
        formal_evidence_sha256=_sha256(formal_evidence_bytes),
        formal_wire_transcript_sha256=formal.wire_transcript_sha256,
        service_audit_sha256=_sha256(service_audit_bytes),
        session_audit_sha256=(
            _sha256(session_audit_bytes) if session_audit_bytes is not None else None
        ),
        envelope_set_sha256=envelope_set_sha256,
        completion_kind=formal.completion_kind,
        decision_count=len(formal.wire_cycles),
        authenticated_envelope_count=2 * pairs,
        request_envelope_count=pairs,
        response_envelope_count=pairs,
        verifier_implementation_sha256=_sha256(verifier_implementation_bytes),
    )
    return HostWireHMACVerificationReceiptV4(core=core)
