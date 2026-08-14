"""Formal host orchestration for one ADR-0024 V4 Q-B episode.

The host owns transport ordering and evidence construction only.  It never
selects a skill, synthesizes an exact plan, executes physics, or substitutes a
fixed continuation.  Every decision is produced by the separately HMAC-bound
Qwen service and independently remapped by the real-Isaac endpoint.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import time
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
    validate_executed_intent_history_v2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_ISAAC_CAPTURE_PATH_V4,
    FORMAL_ISAAC_EXECUTE_PATH_V4,
    FORMAL_ISAAC_FINALIZE_PATH_V4,
    FORMAL_ISAAC_START_PATH_V4,
    FormalInferenceRequestV4,
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
    SignedInferenceRequestV4,
    SignedInferenceResponseV4,
    SignedIsaacWireMessageV4,
    canonical_runtime_mapping_sha256_v4,
    runtime_request_from_inference_v4,
    sign_inference_request_v4,
    sign_isaac_wire_message_v4,
    validate_inference_response_binding_v4,
    validate_runtime_mapping_v4,
    verify_inference_response_v4,
    verify_isaac_wire_message_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    MappingRejectionV2,
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalV4Transport(Protocol):
    """Transport implemented by HTTP in production and in-memory in tests."""

    def post_qwen(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def post_isaac(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


FormalV4EventSink = Callable[[str, Mapping[str, Any]], None]


class FormalV4RunInputs(StrictModel):
    """Immutable inputs resolved before either endpoint is contacted."""

    schema_version: Literal["FormalV4RunInputs"] = "FormalV4RunInputs"
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_receipt_path: str = Field(min_length=1)
    challenge_consumption_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_id: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_target_attribute: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    bundle: QwenBundleRuntimeBindingV4
    isaac_endpoint_binding: IsaacEndpointBindingV4
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def public_deployments_are_shared(self) -> "FormalV4RunInputs":
        endpoint = self.isaac_endpoint_binding
        bundle = self.bundle
        if (
            bundle.association_deployment_sha256 != endpoint.association_deployment_sha256
            or bundle.capture_source_implementation_sha256
            != endpoint.capture_source_implementation_sha256
            or bundle.declared_attribute_selector_implementation_sha256
            != endpoint.declared_attribute_selector_implementation_sha256
        ):
            raise ValueError("formal V4 Qwen and Isaac public deployments differ")
        return self


_PayloadT = TypeVar("_PayloadT", bound=BaseModel)


def _isaac_payload_without_hmac(
    message: SignedIsaacWireMessageV4,
    *,
    expected_type: str,
    model: type[_PayloadT],
) -> _PayloadT:
    if message.message_type != expected_type:
        raise ValueError("formal V4 evidence contains the wrong Isaac message type")
    if message.payload_sha256 != canonical_sha256(message.payload):
        raise ValueError("formal V4 evidence contains a mismatched Isaac payload digest")
    return model.model_validate(message.payload)


def _inference_digests_are_exact(
    request: SignedInferenceRequestV4,
    response: SignedInferenceResponseV4,
) -> None:
    if request.payload_sha256 != canonical_sha256(request.payload):
        raise ValueError("formal V4 evidence contains a mismatched inference request digest")
    if response.payload_sha256 != canonical_sha256(response.payload):
        raise ValueError("formal V4 evidence contains a mismatched inference response digest")
    validate_inference_response_binding_v4(request.payload, response.payload)


class FormalV4WireCycleEvidence(StrictModel):
    """One complete capture -> inference -> execute wire cycle."""

    schema_version: Literal["FormalV4WireCycleEvidence"] = "FormalV4WireCycleEvidence"
    decision_index: int = Field(ge=0, le=7)
    capture_request: SignedIsaacWireMessageV4
    capture_response: SignedIsaacWireMessageV4
    inference_request: SignedInferenceRequestV4
    inference_response: SignedInferenceResponseV4
    execute_request: SignedIsaacWireMessageV4
    execute_response: SignedIsaacWireMessageV4

    @model_validator(mode="after")
    def exact_cycle_is_cross_bound(self) -> "FormalV4WireCycleEvidence":
        capture_request = _isaac_payload_without_hmac(
            self.capture_request,
            expected_type="ISAAC_CAPTURE_REQUEST_V4",
            model=IsaacCaptureRequestV4,
        )
        capture_response = _isaac_payload_without_hmac(
            self.capture_response,
            expected_type="ISAAC_CAPTURE_RESPONSE_V4",
            model=IsaacCaptureResponseV4,
        )
        execute_request = _isaac_payload_without_hmac(
            self.execute_request,
            expected_type="ISAAC_EXECUTE_REQUEST_V4",
            model=IsaacExecuteRequestV4,
        )
        execute_response = _isaac_payload_without_hmac(
            self.execute_response,
            expected_type="ISAAC_EXECUTE_RESPONSE_V4",
            model=IsaacExecuteResponseV4,
        )
        _inference_digests_are_exact(self.inference_request, self.inference_response)
        inference_request = self.inference_request.payload
        inference_response = self.inference_response.payload
        identities = {
            (capture_request.run_id, capture_request.session_id, capture_request.decision_index),
            (capture_response.run_id, capture_response.session_id, capture_response.decision_index),
            (execute_request.run_id, execute_request.session_id, execute_request.decision_index),
            (execute_response.run_id, execute_response.session_id, execute_response.decision_index),
        }
        if len(identities) != 1 or next(iter(identities))[2] != self.decision_index:
            raise ValueError("formal V4 wire cycle crosses run/session/decision identity")
        observation = capture_response.observation
        if (
            inference_request.run_id != capture_request.run_id
            or inference_request.decision_index != self.decision_index
            or inference_request.observation != observation
            or execute_request.observation != observation
            or execute_request.inference_response_sha256 != self.inference_response.payload_sha256
            or execute_response.inference_response_sha256 != self.inference_response.payload_sha256
            or execute_response.formal_observation_sha256 != observation.wire_sha256
            or inference_response.formal_observation_sha256 != observation.wire_sha256
        ):
            raise ValueError("formal V4 wire cycle crosses capture/inference/execution evidence")
        return self


CompletionKindV4 = Literal[
    "FINALIZED",
    "TERMINAL_NO_PHYSICAL_EXECUTION",
    "TERMINAL_EXECUTION_FAILURE",
]


def _history_item(
    response: IsaacExecuteResponseV4,
) -> PublicExecutedIntentHistoryItemV2:
    receipt = response.execution_receipts[0]
    destination = (
        response.mapping.destination_resolution.destination_cell
        if response.mapping.destination_resolution is not None
        else None
    )
    return PublicExecutedIntentHistoryItemV2(
        decision_index=response.decision_index,
        selected_skill=str(response.mapping.canonical_skill),
        target_track_id=response.mapping.target_track_id,
        destination_cell=destination,
        physical_receipt_sha256=receipt.receipt_sha256,
        execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
    )


def _transcript_payload(
    *,
    start_request: SignedIsaacWireMessageV4,
    start_response: SignedIsaacWireMessageV4,
    cycles: list[FormalV4WireCycleEvidence],
    finalize_request: SignedIsaacWireMessageV4 | None,
    finalize_response: SignedIsaacWireMessageV4 | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [
        {
            "path": FORMAL_ISAAC_START_PATH_V4,
            "direction": "REQUEST",
            "signed_wire": start_request.model_dump(mode="json"),
        },
        {
            "path": FORMAL_ISAAC_START_PATH_V4,
            "direction": "RESPONSE",
            "signed_wire": start_response.model_dump(mode="json"),
        },
    ]
    for cycle in cycles:
        records.extend(
            [
                {
                    "path": FORMAL_ISAAC_CAPTURE_PATH_V4,
                    "direction": "REQUEST",
                    "signed_wire": cycle.capture_request.model_dump(mode="json"),
                },
                {
                    "path": FORMAL_ISAAC_CAPTURE_PATH_V4,
                    "direction": "RESPONSE",
                    "signed_wire": cycle.capture_response.model_dump(mode="json"),
                },
                {
                    "path": FORMAL_INFERENCE_PATH_V4,
                    "direction": "REQUEST",
                    "signed_wire": cycle.inference_request.model_dump(mode="json"),
                },
                {
                    "path": FORMAL_INFERENCE_PATH_V4,
                    "direction": "RESPONSE",
                    "signed_wire": cycle.inference_response.model_dump(mode="json"),
                },
                {
                    "path": FORMAL_ISAAC_EXECUTE_PATH_V4,
                    "direction": "REQUEST",
                    "signed_wire": cycle.execute_request.model_dump(mode="json"),
                },
                {
                    "path": FORMAL_ISAAC_EXECUTE_PATH_V4,
                    "direction": "RESPONSE",
                    "signed_wire": cycle.execute_response.model_dump(mode="json"),
                },
            ]
        )
    if finalize_request is not None and finalize_response is not None:
        records.extend(
            [
                {
                    "path": FORMAL_ISAAC_FINALIZE_PATH_V4,
                    "direction": "REQUEST",
                    "signed_wire": finalize_request.model_dump(mode="json"),
                },
                {
                    "path": FORMAL_ISAAC_FINALIZE_PATH_V4,
                    "direction": "RESPONSE",
                    "signed_wire": finalize_response.model_dump(mode="json"),
                },
            ]
        )
    return records


class M2CFormalSplitRunnerEvidenceV4(StrictModel):
    """Self-hashed formal evidence for a finalized or terminalized V4 run."""

    schema_version: Literal["M2CFormalSplitRunnerEvidenceV4"] = "M2CFormalSplitRunnerEvidenceV4"
    status: Literal["COMPLETE_TERMINALIZED_FORMAL_V4_EPISODE"] = (
        "COMPLETE_TERMINALIZED_FORMAL_V4_EPISODE"
    )
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_receipt_path: str = Field(min_length=1)
    challenge_consumption_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_id: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_target_attribute: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    bundle: QwenBundleRuntimeBindingV4
    isaac_endpoint_binding: IsaacEndpointBindingV4
    start_request: SignedIsaacWireMessageV4
    start_response: SignedIsaacWireMessageV4
    wire_cycles: list[FormalV4WireCycleEvidence] = Field(min_length=1, max_length=8)
    finalize_request: SignedIsaacWireMessageV4 | None = None
    finalize_response: SignedIsaacWireMessageV4 | None = None
    completion_kind: CompletionKindV4
    final_task_success: bool
    model_decision_count: int = Field(ge=1, le=8)
    real_model_operation_count: int = Field(ge=0, le=8)
    robot_actuation_operation_count: int = Field(ge=0, le=8)
    collision_or_safety_violation: bool
    strict_pure_model_success: bool
    wire_transcript_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    scripted_decision_source: Literal[False] = False
    b0_runtime_fallback_present: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def full_episode_replays_exactly(self) -> "M2CFormalSplitRunnerEvidenceV4":
        start_request = _isaac_payload_without_hmac(
            self.start_request,
            expected_type="ISAAC_START_REQUEST_V4",
            model=IsaacStartRequestV4,
        )
        start_response = _isaac_payload_without_hmac(
            self.start_response,
            expected_type="ISAAC_START_RESPONSE_V4",
            model=IsaacStartResponseV4,
        )
        endpoint_sha256 = canonical_sha256(self.isaac_endpoint_binding)
        if (
            start_request.run_id != self.run_id
            or start_request.challenge_nonce != self.challenge_nonce
            or start_request.challenge_consumption_id != self.challenge_consumption_id
            or start_request.challenge_consumption_receipt_sha256
            != self.challenge_consumption_receipt_sha256
            or start_request.matched_key != self.matched_key
            or start_request.scene_seed != self.scene_seed
            or start_request.failure_seed != self.failure_seed
            or start_request.sdf_sha256 != self.sdf_sha256
            or start_request.supervision_sha256 != self.supervision_sha256
            or start_request.declared_target_attribute != self.declared_target_attribute
            or start_request.declared_attribute_binding_sha256
            != self.declared_attribute_binding_sha256
            or start_request.bundle != self.bundle
            or start_request.endpoint_binding_sha256 != endpoint_sha256
            or start_response.run_id != self.run_id
            or start_response.start_request_sha256 != canonical_sha256(start_request)
            or start_response.endpoint_binding_sha256 != endpoint_sha256
            or start_response.implementation_sha256
            != self.isaac_endpoint_binding.implementation_sha256
            or start_response.physical_backend_sha256
            != self.isaac_endpoint_binding.physical_backend_sha256
            or start_response.public_observation_provider_sha256
            != self.isaac_endpoint_binding.public_observation_provider_sha256
            or start_response.formal_exact_plan_runtime_sha256
            != self.isaac_endpoint_binding.formal_exact_plan_runtime_sha256
        ):
            raise ValueError("formal V4 start evidence crosses frozen run/deployment inputs")

        if [cycle.decision_index for cycle in self.wire_cycles] != list(
            range(len(self.wire_cycles))
        ):
            raise ValueError("formal V4 evidence decisions are not one contiguous prefix")
        history: list[PublicExecutedIntentHistoryItemV2] = []
        previous_receipt_sha256: str | None = None
        previous_completed_at_ns = start_response.failure_observed_at_ns
        terminal_response: IsaacExecuteResponseV4 | None = None
        execute_responses: list[IsaacExecuteResponseV4] = []
        for cycle_offset, cycle in enumerate(self.wire_cycles):
            capture_request = _isaac_payload_without_hmac(
                cycle.capture_request,
                expected_type="ISAAC_CAPTURE_REQUEST_V4",
                model=IsaacCaptureRequestV4,
            )
            capture_response = _isaac_payload_without_hmac(
                cycle.capture_response,
                expected_type="ISAAC_CAPTURE_RESPONSE_V4",
                model=IsaacCaptureResponseV4,
            )
            execute_request = _isaac_payload_without_hmac(
                cycle.execute_request,
                expected_type="ISAAC_EXECUTE_REQUEST_V4",
                model=IsaacExecuteRequestV4,
            )
            execute_response = _isaac_payload_without_hmac(
                cycle.execute_response,
                expected_type="ISAAC_EXECUTE_RESPONSE_V4",
                model=IsaacExecuteResponseV4,
            )
            execute_responses.append(execute_response)
            inference_request = cycle.inference_request.payload
            if (
                capture_request.run_id != self.run_id
                or capture_request.session_id != start_response.session_id
                or capture_request.previous_execution_receipt_sha256 != previous_receipt_sha256
                or inference_request.challenge_nonce != self.challenge_nonce
                or inference_request.bundle != self.bundle
                or inference_request.executed_intent_history != history
                or execute_request.executed_intent_history != history
                or execute_request.executed_intent_history_sha256 != canonical_sha256(history)
                or capture_response.observation.declared_attribute_binding_sha256
                != self.declared_attribute_binding_sha256
                or capture_response.observation.previous_physical_completed_at_ns
                != previous_completed_at_ns
            ):
                raise ValueError("formal V4 cycle differs from its exact run/history prefix")
            receipt = execute_response.execution_receipts[0]
            previous_receipt_sha256 = receipt.receipt_sha256
            previous_completed_at_ns = receipt.completed_at_ns
            if execute_response.disposition == "CONTINUE":
                if terminal_response is not None:
                    raise ValueError("formal V4 evidence continues after a terminal response")
                if cycle.decision_index < 7:
                    history.append(_history_item(execute_response))
                    validate_executed_intent_history_v2(
                        history,
                        expected_length=cycle.decision_index + 1,
                    )
            else:
                if cycle_offset != len(self.wire_cycles) - 1:
                    raise ValueError("formal V4 terminal response is not the final wire cycle")
                terminal_response = execute_response

        if terminal_response is None:
            if len(self.wire_cycles) != 8 or self.completion_kind != "FINALIZED":
                raise ValueError("formal V4 nonterminal evidence lacks eight decisions/finalize")
            if self.finalize_request is None or self.finalize_response is None:
                raise ValueError("formal V4 eight-cycle evidence lacks signed finalization")
            finalize_request = _isaac_payload_without_hmac(
                self.finalize_request,
                expected_type="ISAAC_FINALIZE_REQUEST_V4",
                model=IsaacFinalizeRequestV4,
            )
            finalize_response = _isaac_payload_without_hmac(
                self.finalize_response,
                expected_type="ISAAC_FINALIZE_RESPONSE_V4",
                model=IsaacFinalizeResponseV4,
            )
            last = execute_responses[-1]
            if (
                finalize_request.run_id != self.run_id
                or finalize_request.session_id != start_response.session_id
                or finalize_request.last_execution_receipt_sha256
                != last.execution_receipts[0].receipt_sha256
                or finalize_request.last_bundle_execution_receipt_sha256
                != last.bundle_execution_receipt_sha256
                or finalize_response.run_id != self.run_id
                or finalize_response.session_id != start_response.session_id
                or self.final_task_success != finalize_response.final_task_success
                or finalize_response.evaluated_at_ns <= previous_completed_at_ns
            ):
                raise ValueError("formal V4 finalization crosses the eight-cycle episode")
        else:
            if self.finalize_request is not None or self.finalize_response is not None:
                raise ValueError("formal V4 terminal failure evidence contains finalization")
            if (
                self.completion_kind != terminal_response.disposition
                or self.final_task_success
                or terminal_response.terminal_failure_outcome is not False
            ):
                raise ValueError("formal V4 terminal response is not a fixed false outcome")

        receipts = [response.execution_receipts[0] for response in execute_responses]
        receipt_hashes = [receipt.receipt_sha256 for receipt in receipts]
        receipt_ids = [receipt.receipt_id for receipt in receipts]
        if len(receipt_hashes) != len(set(receipt_hashes)) or len(receipt_ids) != len(
            set(receipt_ids)
        ):
            raise ValueError("formal V4 episode reuses an execution receipt")
        real_model_operations = sum(
            receipt.execution_source == "MODEL_SELECTED_REGISTERED_SKILL"
            and receipt.executed_in_real_isaac
            for receipt in receipts
        )
        robot_operations = sum(receipt.robot_actuation_executed for receipt in receipts)
        safety_violation = any(receipt.collision_or_safety_violation for receipt in receipts)
        pure = bool(
            self.final_task_success
            and self.completion_kind == "FINALIZED"
            and len(execute_responses) == 8
            and all(
                response.disposition == "CONTINUE"
                and response.mapping.status == "VALID"
                and response.mapping.execution_attribution == "MODEL_SELECTED_REGISTERED_SKILL"
                and not response.mapping.fallback_required
                and response.model_operation_executed_in_real_isaac
                and response.execution_receipts[0].execution_source
                == "MODEL_SELECTED_REGISTERED_SKILL"
                and response.execution_receipts[0].executed_in_real_isaac
                and response.execution_receipts[0].outcome == "PASS"
                and not response.execution_receipts[0].collision_or_safety_violation
                for response in execute_responses
            )
        )
        if (
            self.model_decision_count != len(self.wire_cycles)
            or self.real_model_operation_count != real_model_operations
            or self.robot_actuation_operation_count != robot_operations
            or self.collision_or_safety_violation != safety_violation
            or self.strict_pure_model_success != pure
        ):
            raise ValueError("formal V4 episode summary differs from signed execution evidence")
        transcript = _transcript_payload(
            start_request=self.start_request,
            start_response=self.start_response,
            cycles=self.wire_cycles,
            finalize_request=self.finalize_request,
            finalize_response=self.finalize_response,
        )
        if self.wire_transcript_sha256 != canonical_sha256(transcript):
            raise ValueError("formal V4 ordered wire transcript digest differs")
        expected_evidence = canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        )
        if self.evidence_sha256 != expected_evidence:
            raise ValueError("formal V4 evidence self-digest differs")
        return self


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


def _validate_endpoint_mapping(
    independent: RuntimeSkillMappingResultV2,
    actual: RuntimeSkillMappingResultV2,
) -> None:
    if _mapping_semantics(independent) != _mapping_semantics(actual):
        raise ValueError("formal V4 endpoint changed independently mapped semantics")
    if independent.status == "INVALID":
        if canonical_runtime_mapping_sha256_v4(independent) != canonical_runtime_mapping_sha256_v4(
            actual
        ):
            raise ValueError("formal V4 endpoint changed an independently invalid mapping")
        return
    if actual.status == "VALID":
        if canonical_runtime_mapping_sha256_v4(independent) != canonical_runtime_mapping_sha256_v4(
            actual
        ):
            raise ValueError("formal V4 endpoint changed a valid independent mapping")
        return
    dynamic_rejections = {
        MappingRejectionV2.IK_REJECTION,
        MappingRejectionV2.COLLISION_REJECTION,
        MappingRejectionV2.SAFETY_REJECTION,
    }
    if (
        actual.rejection_reason not in dynamic_rejections
        or not actual.fallback_required
        or actual.execution_attribution != "NO_PHYSICAL_EXECUTION"
    ):
        raise ValueError("formal V4 endpoint returned an unrecognized dynamic rejection")


def _emit(
    sink: FormalV4EventSink | None,
    stage: str,
    payload: BaseModel,
) -> None:
    if sink is not None:
        sink(stage, payload.model_dump(mode="json"))


def _build_evidence(
    *,
    inputs: FormalV4RunInputs,
    start_request: SignedIsaacWireMessageV4,
    start_response: SignedIsaacWireMessageV4,
    cycles: list[FormalV4WireCycleEvidence],
    completion_kind: CompletionKindV4,
    final_task_success: bool,
    finalize_request: SignedIsaacWireMessageV4 | None = None,
    finalize_response: SignedIsaacWireMessageV4 | None = None,
) -> M2CFormalSplitRunnerEvidenceV4:
    execute_responses = [
        _isaac_payload_without_hmac(
            cycle.execute_response,
            expected_type="ISAAC_EXECUTE_RESPONSE_V4",
            model=IsaacExecuteResponseV4,
        )
        for cycle in cycles
    ]
    receipts = [response.execution_receipts[0] for response in execute_responses]
    pure = bool(
        final_task_success
        and completion_kind == "FINALIZED"
        and len(execute_responses) == 8
        and all(
            response.disposition == "CONTINUE"
            and response.mapping.status == "VALID"
            and response.mapping.execution_attribution == "MODEL_SELECTED_REGISTERED_SKILL"
            and not response.mapping.fallback_required
            and response.model_operation_executed_in_real_isaac
            and response.execution_receipts[0].execution_source == "MODEL_SELECTED_REGISTERED_SKILL"
            and response.execution_receipts[0].executed_in_real_isaac
            and response.execution_receipts[0].outcome == "PASS"
            and not response.execution_receipts[0].collision_or_safety_violation
            for response in execute_responses
        )
    )
    transcript = _transcript_payload(
        start_request=start_request,
        start_response=start_response,
        cycles=cycles,
        finalize_request=finalize_request,
        finalize_response=finalize_response,
    )
    payload: dict[str, Any] = {
        "schema_version": "M2CFormalSplitRunnerEvidenceV4",
        "status": "COMPLETE_TERMINALIZED_FORMAL_V4_EPISODE",
        **inputs.model_dump(
            mode="json",
            exclude={"schema_version", "teacher_used", "privileged_truth_policy_input"},
        ),
        "start_request": start_request.model_dump(mode="json"),
        "start_response": start_response.model_dump(mode="json"),
        "wire_cycles": [cycle.model_dump(mode="json") for cycle in cycles],
        "finalize_request": (
            None if finalize_request is None else finalize_request.model_dump(mode="json")
        ),
        "finalize_response": (
            None if finalize_response is None else finalize_response.model_dump(mode="json")
        ),
        "completion_kind": completion_kind,
        "final_task_success": final_task_success,
        "model_decision_count": len(cycles),
        "real_model_operation_count": sum(
            receipt.execution_source == "MODEL_SELECTED_REGISTERED_SKILL"
            and receipt.executed_in_real_isaac
            for receipt in receipts
        ),
        "robot_actuation_operation_count": sum(
            receipt.robot_actuation_executed for receipt in receipts
        ),
        "collision_or_safety_violation": any(
            receipt.collision_or_safety_violation for receipt in receipts
        ),
        "strict_pure_model_success": pure,
        "wire_transcript_sha256": canonical_sha256(transcript),
        "synthetic": False,
        "mocked_physics": False,
        "scripted_decision_source": False,
        "b0_runtime_fallback_present": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["evidence_sha256"] = canonical_sha256(payload)
    return M2CFormalSplitRunnerEvidenceV4.model_validate(payload)


def run_formal_v4_episode(
    *,
    inputs: FormalV4RunInputs,
    registry: RuntimeSkillRegistryV2,
    qwen_secret: bytes,
    isaac_secret: bytes,
    transport: FormalV4Transport,
    clock_ns: Callable[[], int] = time.time_ns,
    event_sink: FormalV4EventSink | None = None,
) -> M2CFormalSplitRunnerEvidenceV4:
    """Run exactly one preregistered V4 episode through external services."""

    if len(qwen_secret) < 32 or len(isaac_secret) < 32:
        raise ValueError("formal V4 endpoint HMAC keys must each contain at least 32 bytes")
    endpoint_sha256 = canonical_sha256(inputs.isaac_endpoint_binding)
    start_payload = IsaacStartRequestV4(
        run_id=inputs.run_id,
        challenge_nonce=inputs.challenge_nonce,
        challenge_consumption_id=inputs.challenge_consumption_id,
        challenge_consumption_receipt_sha256=(inputs.challenge_consumption_receipt_sha256),
        matched_key=inputs.matched_key,
        scene_seed=inputs.scene_seed,
        failure_seed=inputs.failure_seed,
        sdf_sha256=inputs.sdf_sha256,
        supervision_sha256=inputs.supervision_sha256,
        endpoint_binding_sha256=endpoint_sha256,
        declared_target_attribute=inputs.declared_target_attribute,
        declared_attribute_binding_sha256=(inputs.declared_attribute_binding_sha256),
        bundle=inputs.bundle,
    )
    start_request = sign_isaac_wire_message_v4(
        "ISAAC_START_REQUEST_V4",
        start_payload,
        isaac_secret,
    )
    _emit(event_sink, "START_REQUEST", start_request)
    raw_start_response = transport.post_isaac(
        FORMAL_ISAAC_START_PATH_V4,
        start_request.model_dump(mode="json"),
    )
    start_response, start = verify_isaac_wire_message_v4(
        raw_start_response,
        isaac_secret,
        expected_type="ISAAC_START_RESPONSE_V4",
        model=IsaacStartResponseV4,
    )
    _emit(event_sink, "START_RESPONSE", start_response)
    if (
        start.run_id != inputs.run_id
        or start.start_request_sha256 != canonical_sha256(start_payload)
        or start.endpoint_binding_sha256 != endpoint_sha256
        or start.implementation_sha256 != inputs.isaac_endpoint_binding.implementation_sha256
        or start.physical_backend_sha256 != inputs.isaac_endpoint_binding.physical_backend_sha256
        or start.public_observation_provider_sha256
        != inputs.isaac_endpoint_binding.public_observation_provider_sha256
        or start.formal_exact_plan_runtime_sha256
        != inputs.isaac_endpoint_binding.formal_exact_plan_runtime_sha256
    ):
        raise ValueError("formal V4 start response differs from the frozen endpoint")

    history: list[PublicExecutedIntentHistoryItemV2] = []
    previous_receipt_sha256: str | None = None
    cycles: list[FormalV4WireCycleEvidence] = []
    last_execute: IsaacExecuteResponseV4 | None = None
    for decision_index in range(8):
        capture_payload = IsaacCaptureRequestV4(
            run_id=inputs.run_id,
            session_id=start.session_id,
            decision_index=decision_index,
            previous_execution_receipt_sha256=previous_receipt_sha256,
        )
        capture_request = sign_isaac_wire_message_v4(
            "ISAAC_CAPTURE_REQUEST_V4",
            capture_payload,
            isaac_secret,
        )
        _emit(event_sink, f"DECISION_{decision_index}_CAPTURE_REQUEST", capture_request)
        raw_capture_response = transport.post_isaac(
            FORMAL_ISAAC_CAPTURE_PATH_V4,
            capture_request.model_dump(mode="json"),
        )
        capture_response, capture = verify_isaac_wire_message_v4(
            raw_capture_response,
            isaac_secret,
            expected_type="ISAAC_CAPTURE_RESPONSE_V4",
            model=IsaacCaptureResponseV4,
        )
        _emit(event_sink, f"DECISION_{decision_index}_CAPTURE_RESPONSE", capture_response)
        if (
            capture.run_id != inputs.run_id
            or capture.session_id != start.session_id
            or capture.decision_index != decision_index
            or capture.observation.declared_attribute_binding_sha256
            != inputs.declared_attribute_binding_sha256
        ):
            raise ValueError("formal V4 capture response crosses run/session/declaration")

        sent_at_ns = max(clock_ns(), capture.observation.captured_at_ns + 1)
        inference_payload = FormalInferenceRequestV4(
            run_id=inputs.run_id,
            challenge_nonce=inputs.challenge_nonce,
            request_id=f"{inputs.run_id}-decision-{decision_index}",
            decision_index=decision_index,
            sent_at_ns=sent_at_ns,
            executed_intent_history=history,
            prior_decisions_sha256=canonical_sha256(history),
            bundle=inputs.bundle,
            observation=capture.observation,
        )
        inference_request = sign_inference_request_v4(inference_payload, qwen_secret)
        _emit(event_sink, f"DECISION_{decision_index}_INFERENCE_REQUEST", inference_request)
        raw_inference_response = transport.post_qwen(
            FORMAL_INFERENCE_PATH_V4,
            inference_request.model_dump(mode="json"),
        )
        inference_response = verify_inference_response_v4(
            raw_inference_response,
            qwen_secret,
        )
        _emit(event_sink, f"DECISION_{decision_index}_INFERENCE_RESPONSE", inference_response)
        validate_inference_response_binding_v4(
            inference_payload,
            inference_response.payload,
        )
        runtime_request = runtime_request_from_inference_v4(
            inference_payload,
            inference_response.payload,
            registry,
        )
        independent_mapping = validate_runtime_mapping_v4(
            runtime_request,
            capture.observation,
            registry,
        )
        execute_payload = IsaacExecuteRequestV4(
            run_id=inputs.run_id,
            session_id=start.session_id,
            decision_index=decision_index,
            observation_id=capture.observation.observation_id,
            capture_receipt_sha256=capture.observation.capture_receipt_sha256,
            formal_observation_sha256=capture.observation.wire_sha256,
            canonical_public_tracks_sha256=(capture.observation.canonical_public_tracks_sha256),
            inference_response_sha256=inference_response.payload_sha256,
            executed_intent_history=history,
            executed_intent_history_sha256=canonical_sha256(history),
            observation=capture.observation,
            runtime_request=runtime_request,
        )
        execute_request = sign_isaac_wire_message_v4(
            "ISAAC_EXECUTE_REQUEST_V4",
            execute_payload,
            isaac_secret,
        )
        _emit(event_sink, f"DECISION_{decision_index}_EXECUTE_REQUEST", execute_request)
        raw_execute_response = transport.post_isaac(
            FORMAL_ISAAC_EXECUTE_PATH_V4,
            execute_request.model_dump(mode="json"),
        )
        execute_response, execute = verify_isaac_wire_message_v4(
            raw_execute_response,
            isaac_secret,
            expected_type="ISAAC_EXECUTE_RESPONSE_V4",
            model=IsaacExecuteResponseV4,
        )
        _emit(event_sink, f"DECISION_{decision_index}_EXECUTE_RESPONSE", execute_response)
        if (
            execute.run_id != inputs.run_id
            or execute.session_id != start.session_id
            or execute.decision_index != decision_index
            or execute.observation_id != capture.observation.observation_id
            or execute.formal_observation_sha256 != capture.observation.wire_sha256
            or execute.inference_response_sha256 != inference_response.payload_sha256
        ):
            raise ValueError("formal V4 execute response crosses its active decision")
        _validate_endpoint_mapping(independent_mapping, execute.mapping)
        cycle = FormalV4WireCycleEvidence(
            decision_index=decision_index,
            capture_request=capture_request,
            capture_response=capture_response,
            inference_request=inference_request,
            inference_response=inference_response,
            execute_request=execute_request,
            execute_response=execute_response,
        )
        cycles.append(cycle)
        last_execute = execute
        previous_receipt_sha256 = execute.execution_receipts[0].receipt_sha256
        if execute.disposition != "CONTINUE":
            return _build_evidence(
                inputs=inputs,
                start_request=start_request,
                start_response=start_response,
                cycles=cycles,
                completion_kind=execute.disposition,
                final_task_success=False,
            )
        if decision_index < 7:
            history.append(_history_item(execute))
            validate_executed_intent_history_v2(
                history,
                expected_length=decision_index + 1,
            )

    if last_execute is None or last_execute.bundle_execution_receipt_sha256 is None:
        raise RuntimeError("formal V4 eight-cycle episode lacks final execution evidence")
    finalize_payload = IsaacFinalizeRequestV4(
        run_id=inputs.run_id,
        session_id=start.session_id,
        last_execution_receipt_sha256=last_execute.execution_receipts[0].receipt_sha256,
        last_bundle_execution_receipt_sha256=(last_execute.bundle_execution_receipt_sha256),
    )
    finalize_request = sign_isaac_wire_message_v4(
        "ISAAC_FINALIZE_REQUEST_V4",
        finalize_payload,
        isaac_secret,
    )
    _emit(event_sink, "FINALIZE_REQUEST", finalize_request)
    raw_finalize_response = transport.post_isaac(
        FORMAL_ISAAC_FINALIZE_PATH_V4,
        finalize_request.model_dump(mode="json"),
    )
    finalize_response, final = verify_isaac_wire_message_v4(
        raw_finalize_response,
        isaac_secret,
        expected_type="ISAAC_FINALIZE_RESPONSE_V4",
        model=IsaacFinalizeResponseV4,
    )
    _emit(event_sink, "FINALIZE_RESPONSE", finalize_response)
    if final.run_id != inputs.run_id or final.session_id != start.session_id:
        raise ValueError("formal V4 final outcome crosses its physical session")
    return _build_evidence(
        inputs=inputs,
        start_request=start_request,
        start_response=start_response,
        cycles=cycles,
        finalize_request=finalize_request,
        finalize_response=finalize_response,
        completion_kind="FINALIZED",
        final_task_success=final.final_task_success,
    )
