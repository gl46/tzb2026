from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import pytest

from xh_agent.data_engine.isaac.public_failure_predicates import PublicTrackSnapshotV2
from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v2 import (
    AppendOnlyIsaacAuditLogV2,
    FormalIsaacEndpointStateMachineV2,
)
from xh_agent.policy.qrm_lite.formal_public_role_selector_v2 import (
    select_public_journal_roles_v2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    FORMAL_ISAAC_CAPTURE_PATH,
    FORMAL_ISAAC_EXECUTE_PATH,
    FORMAL_ISAAC_FINALIZE_PATH,
    FORMAL_ISAAC_START_PATH,
    FormalPublicObservationV2,
    IsaacCaptureRequestV2,
    IsaacCaptureResponseV2,
    IsaacEndpointBindingV2,
    IsaacExecuteRequestV2,
    IsaacExecuteResponseV2,
    IsaacFinalizeRequestV2,
    IsaacFinalizeResponseV2,
    IsaacStartRequestV2,
    IsaacStartResponseV2,
    PublicAssetInlineV2,
    PublicRoleBindingV2,
    QwenBundleRuntimeBindingV2,
    canonical_sha256,
    physical_receipt_sha256,
    sign_wire_message,
    verify_wire_message,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
    RuntimeSkillRequestV2,
    load_registry_v2,
)


ROOT = Path(__file__).resolve().parents[2]
SECRET = b"formal-isaac-state-machine-test-key!!"
DIGEST = "a" * 64


def _bundle() -> QwenBundleRuntimeBindingV2:
    return QwenBundleRuntimeBindingV2(
        bundle_manifest_sha256="1" * 64,
        head_checkpoint_sha256="2" * 64,
        adapter_tree_sha256="3" * 64,
        model_cache_dir=(
            "/verified/cache/models--Qwen--Qwen3.5-4B/snapshots/"
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
        ),
        model_cache_tree_sha256="4" * 64,
        failure_context="on",
    )


def _binding() -> IsaacEndpointBindingV2:
    return IsaacEndpointBindingV2(
        endpoint_base_url="http://labserver:48132",
        host="labserver",
        implementation_path="/frozen/serve.py",
        implementation_sha256="5" * 64,
        physical_backend_path="/frozen/backend.py",
        physical_backend_sha256="6" * 64,
        public_role_selector_path="/frozen/public_selector.py",
        public_role_selector_sha256="7" * 64,
        frozen_v4_probe_sha256=("6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"),
    )


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(stream, "PNG")
    return stream.getvalue()


def _depth() -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.ones((2, 2), dtype=np.float32), allow_pickle=False)
    return stream.getvalue()


def _asset(raw: bytes, *, uri: str, media_type: str) -> PublicAssetInlineV2:
    return PublicAssetInlineV2(
        uri=uri,
        sha256=hashlib.sha256(raw).hexdigest(),
        media_type=media_type,
        data_base64=base64.b64encode(raw).decode("ascii"),
    )


class _ContractBackend:
    """State-machine test double; never formal or physical evidence."""

    formal_evidence = False
    real_physics = False

    def __init__(self, binding: IsaacEndpointBindingV2) -> None:
        self.binding = binding
        self.failure_ns = 100
        self.previous_ns = 100
        self.execute_calls = 0

    def start(self, request: IsaacStartRequestV2) -> IsaacStartResponseV2:
        return IsaacStartResponseV2(
            run_id=request.run_id,
            session_id="contract-session-not-physics",
            start_request_sha256=canonical_sha256(request),
            failure_observed_at_ns=self.failure_ns,
            endpoint_binding_sha256=canonical_sha256(self.binding),
            implementation_sha256=self.binding.implementation_sha256,
            physical_backend_sha256=self.binding.physical_backend_sha256,
        )

    def capture(self, request: IsaacCaptureRequestV2) -> IsaacCaptureResponseV2:
        captured = self.previous_ns + 10
        observation = FormalPublicObservationV2(
            observation_id=f"observation-{request.decision_index}",
            captured_at_ns=captured,
            previous_physical_completed_at_ns=self.previous_ns,
            rgb=_asset(_png(), uri=f"dataset://rgb/{captured}.png", media_type="image/png"),
            depth=_asset(
                _depth(),
                uri=f"dataset://depth/{captured}.npy",
                media_type="application/x-npy",
            ),
            capture_receipt_sha256=hashlib.sha256(str(captured).encode()).hexdigest(),
            perception_tracks=[
                {
                    "track_id": "track-blocker",
                    "category": "industrial_cylinder:red",
                    "confidence": 0.99,
                    "pose_xyzquat": [0.1, 0.2, 0.5, 1, 0, 0, 0],
                },
                {
                    "track_id": "track-task",
                    "category": "industrial_cylinder:yellow",
                    "confidence": 0.98,
                    "pose_xyzquat": [0.2, 0.2, 0.5, 1, 0, 0, 0],
                },
            ],
            canonical_slots=[
                "track-blocker",
                "track-task",
                None,
                None,
                None,
                None,
                None,
                None,
            ],
        )
        return IsaacCaptureResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation=observation,
            public_roles=PublicRoleBindingV2(
                blocker_track_id="track-blocker",
                task_target_track_id="track-task",
                selector_contract_sha256=self.binding.public_role_selector_sha256,
            ),
        )

    def execute(
        self,
        request: IsaacExecuteRequestV2,
        _registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV2:
        self.execute_calls += 1
        started = self.previous_ns + 20
        completed = started + 10
        self.previous_ns = completed
        skill = request.runtime_request.skill
        target = request.runtime_request.model_target_track_id
        slot = request.runtime_request.model_target_slot
        plan = ExactExecutionPlanV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            capture_receipt_sha256=request.capture_receipt_sha256,
            canonical_skill=skill,
            runtime_action=f"CONTRACT_ONLY_{skill}",
            execution_parameters_sha256=canonical_sha256({}),
            target_track_id=target,
            phases=(
                ExactExecutionPhaseV2(
                    phase_index=0,
                    phase_name="CONTRACT_ONLY_CARTESIAN",
                    command="CARTESIAN_POSE",
                    goal_position_world_m=(0.1, 0.2, 0.57),
                    orientation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
                    steps=1,
                    collision_phase="CONTRACT_ONLY_NO_PHYSICS",
                    gates=ExactExecutionPhaseGatesV2(
                        ik_detail="contract-only IK",
                        joint_limits_detail="contract-only limits",
                        swept_collision_detail="contract-only sweep",
                        controller_detail="contract-only controller",
                        safety_detail="contract-only safety",
                    ),
                ),
            ),
        )
        plan_sha256 = canonical_sha256(plan)
        mapping = RuntimeSkillMappingResultV2(
            status="VALID",
            canonical_skill=skill,
            runtime_action=f"CONTRACT_ONLY_{skill}",
            target_track_id=target,
            target_track_slot=slot,
            parameters={},
            execution_parameters={},
            parameter_provenance={},
            fallback_action="B0_SAFE_HOLD",
            fallback_required=False,
            execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
            gate_trace=[
                {"gate": name, "status": "PASS"}
                for name in (
                    "schema",
                    "track",
                    "protocol",
                    "ik",
                    "collision",
                    "controller",
                    "safety",
                    "exact_plan",
                )
            ],
        )
        mapping.gate_trace[-1]["plan_sha256"] = plan_sha256
        provisional = PhysicalSkillReceiptV2(
            receipt_id=f"contract-not-physical-{self.execute_calls}",
            receipt_sha256="0" * 64,
            executed_skill=skill,
            execution_source="MODEL_SELECTED_REGISTERED_SKILL",
            physically_executed=True,
            started_at_ns=started,
            completed_at_ns=completed,
            schema_gate="PASS",
            stale_track_gate="PASS",
            frame_unit_gate="PASS",
            ik_gate="PASS",
            collision_gate="PASS",
            controller_gate="PASS",
            safety_gate="PASS",
        )
        receipt = provisional.model_copy(
            update={"receipt_sha256": physical_receipt_sha256(provisional)}
        )
        return IsaacExecuteResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            inference_response_sha256=request.inference_response_sha256,
            mapping=mapping,
            exact_execution_plan=plan,
            exact_execution_plan_sha256=plan_sha256,
            executed_exact_execution_plan_sha256=plan_sha256,
            requested_skill_was_physically_executed=True,
            physical_skill_receipts=[receipt],
        )

    def finalize(self, request: IsaacFinalizeRequestV2) -> IsaacFinalizeResponseV2:
        return IsaacFinalizeResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            evaluated_at_ns=self.previous_ns + 10,
            final_task_success=False,
        )


def _start_request(binding: IsaacEndpointBindingV2) -> IsaacStartRequestV2:
    return IsaacStartRequestV2(
        run_id="run-contract-only",
        matched_key="key-contract-only",
        scene_seed=1,
        failure_seed=2,
        sdf_sha256="8" * 64,
        supervision_sha256="9" * 64,
        runtime_registry_sha256="a" * 64,
        endpoint_binding_sha256=canonical_sha256(binding),
        bundle=_bundle(),
    )


def _runtime(index: int) -> RuntimeSkillRequestV2:
    return RuntimeSkillRequestV2(
        model_class_id="coarse.skill.GRASP",
        skill="GRASP",
        model_target_track_id="track-blocker",
        model_target_slot=0,
        target_track_provenance="MODEL",
        canonical_track_ids=[
            "track-blocker",
            "track-task",
            None,
            None,
            None,
            None,
            None,
            None,
        ],
        parameters={"grasp_family": "top_down"},
        parameter_provenance={"grasp_family": "MODEL"},
        coordinate_frame="world",
        units="m_rad",
        current_phase="RECOVERY",
        confidence=1.0,
    )


def _endpoint(tmp_path: Path) -> tuple[FormalIsaacEndpointStateMachineV2, _ContractBackend]:
    binding = _binding()
    backend = _ContractBackend(binding)
    endpoint = FormalIsaacEndpointStateMachineV2(
        secret=SECRET,
        endpoint_binding=binding,
        registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        backend=backend,
        audit=AppendOnlyIsaacAuditLogV2(tmp_path / "audit"),
    )
    return endpoint, backend


def _call(
    endpoint: FormalIsaacEndpointStateMachineV2,
    *,
    path: str,
    message_type: Any,
    payload: Any,
    response_type: str,
    response_model: Any,
) -> Any:
    raw = sign_wire_message(message_type, payload, SECRET).model_dump(mode="json")
    response = endpoint.handle(path, raw)
    return verify_wire_message(
        response,
        expected_type=response_type,
        payload_model=response_model,
        secret=SECRET,
    )[1]


def test_public_role_selector_is_public_only_and_missing_role_stays_none() -> None:
    roles = select_public_journal_roles_v2(
        [
            PublicTrackSnapshotV2(
                track_id="track-red",
                category="cylinder",
                visual_color="red",
                position_world_m=[0.1, 0.0, 0.5],
                confidence=0.9,
            )
        ]
    )
    assert roles.blocker_track_id == "track-red"
    assert roles.task_target_track_id is None


def test_state_machine_requires_start_capture_execute_order_and_binds_capture(
    tmp_path: Path,
) -> None:
    endpoint, backend = _endpoint(tmp_path)
    with pytest.raises(RuntimeError, match="capture is not the next"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH,
            sign_wire_message(
                "ISAAC_CAPTURE_REQUEST",
                IsaacCaptureRequestV2(
                    run_id="run-contract-only",
                    session_id="contract-session-not-physics",
                    decision_index=0,
                ),
                SECRET,
            ).model_dump(mode="json"),
        )
    start = _call(
        endpoint,
        path=FORMAL_ISAAC_START_PATH,
        message_type="ISAAC_START_REQUEST",
        payload=_start_request(endpoint.binding),
        response_type="ISAAC_START_RESPONSE",
        response_model=IsaacStartResponseV2,
    )
    capture_request = IsaacCaptureRequestV2(
        run_id=start.run_id,
        session_id=start.session_id,
        decision_index=0,
    )
    capture = _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH,
        message_type="ISAAC_CAPTURE_REQUEST",
        payload=capture_request,
        response_type="ISAAC_CAPTURE_RESPONSE",
        response_model=IsaacCaptureResponseV2,
    )
    wrong = IsaacExecuteRequestV2(
        run_id=start.run_id,
        session_id=start.session_id,
        decision_index=0,
        observation_id="wrong-observation",
        capture_receipt_sha256=capture.observation.capture_receipt_sha256,
        inference_response_sha256=DIGEST,
        executed_intent_history_sha256=DIGEST,
        runtime_request=_runtime(0),
    )
    with pytest.raises(ValueError, match="active public capture"):
        endpoint.handle(
            FORMAL_ISAAC_EXECUTE_PATH,
            sign_wire_message("ISAAC_EXECUTE_REQUEST", wrong, SECRET).model_dump(mode="json"),
        )
    assert backend.execute_calls == 0


def test_exactly_eight_cycles_share_one_session_and_finalize_once(tmp_path: Path) -> None:
    endpoint, backend = _endpoint(tmp_path)
    start = _call(
        endpoint,
        path=FORMAL_ISAAC_START_PATH,
        message_type="ISAAC_START_REQUEST",
        payload=_start_request(endpoint.binding),
        response_type="ISAAC_START_RESPONSE",
        response_model=IsaacStartResponseV2,
    )
    previous_sha: str | None = None
    for index in range(8):
        capture = _call(
            endpoint,
            path=FORMAL_ISAAC_CAPTURE_PATH,
            message_type="ISAAC_CAPTURE_REQUEST",
            payload=IsaacCaptureRequestV2(
                run_id=start.run_id,
                session_id=start.session_id,
                decision_index=index,
                previous_physical_receipt_sha256=previous_sha,
            ),
            response_type="ISAAC_CAPTURE_RESPONSE",
            response_model=IsaacCaptureResponseV2,
        )
        execute = _call(
            endpoint,
            path=FORMAL_ISAAC_EXECUTE_PATH,
            message_type="ISAAC_EXECUTE_REQUEST",
            payload=IsaacExecuteRequestV2(
                run_id=start.run_id,
                session_id=start.session_id,
                decision_index=index,
                observation_id=capture.observation.observation_id,
                capture_receipt_sha256=capture.observation.capture_receipt_sha256,
                inference_response_sha256=hashlib.sha256(str(index).encode()).hexdigest(),
                executed_intent_history_sha256=DIGEST,
                runtime_request=_runtime(index),
            ),
            response_type="ISAAC_EXECUTE_RESPONSE",
            response_model=IsaacExecuteResponseV2,
        )
        previous_sha = execute.physical_skill_receipts[0].receipt_sha256
    assert backend.execute_calls == 8
    finalize = _call(
        endpoint,
        path=FORMAL_ISAAC_FINALIZE_PATH,
        message_type="ISAAC_FINALIZE_REQUEST",
        payload=IsaacFinalizeRequestV2(
            run_id=start.run_id,
            session_id=start.session_id,
            last_physical_receipt_sha256=str(previous_sha),
        ),
        response_type="ISAAC_FINALIZE_RESPONSE",
        response_model=IsaacFinalizeResponseV2,
    )
    assert finalize.final_task_success is False
    with pytest.raises(RuntimeError, match="exactly once"):
        endpoint.handle(
            FORMAL_ISAAC_START_PATH,
            sign_wire_message(
                "ISAAC_START_REQUEST",
                _start_request(endpoint.binding),
                SECRET,
            ).model_dump(mode="json"),
        )

    session_path = endpoint.session_audit_path
    assert session_path is not None
    events = [json.loads(line) for line in session_path.read_text().splitlines()]
    committed = [event for event in events if event["event_type"] == "WIRE_RESPONSE_COMMITTED"]
    assert len(committed) == 18  # start + eight capture/execute pairs + finalize
    assert all(event["schema_version"] == "FormalIsaacAuditEventV2" for event in events)


def test_bad_hmac_is_rejected_and_persisted_without_backend_execution(tmp_path: Path) -> None:
    endpoint, backend = _endpoint(tmp_path)
    signed = sign_wire_message(
        "ISAAC_START_REQUEST",
        _start_request(endpoint.binding),
        SECRET,
    ).model_dump(mode="json")
    signed["hmac_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="HMAC"):
        endpoint.handle(FORMAL_ISAAC_START_PATH, signed)
    assert backend.execute_calls == 0
    records = [json.loads(line) for line in endpoint.audit.service_path.read_text().splitlines()]
    assert records[-1]["event_type"] == "WIRE_REQUEST_REJECTED"
    assert records[-1]["payload"]["physical_evidence_accepted"] is False


def test_invalid_mapping_is_terminal_and_never_executes_unfrozen_b0_fallback(
    tmp_path: Path,
) -> None:
    endpoint, backend = _endpoint(tmp_path)
    start = _call(
        endpoint,
        path=FORMAL_ISAAC_START_PATH,
        message_type="ISAAC_START_REQUEST",
        payload=_start_request(endpoint.binding),
        response_type="ISAAC_START_RESPONSE",
        response_model=IsaacStartResponseV2,
    )
    capture = _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH,
        message_type="ISAAC_CAPTURE_REQUEST",
        payload=IsaacCaptureRequestV2(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE",
        response_model=IsaacCaptureResponseV2,
    )

    def fail_closed(
        request: IsaacExecuteRequestV2,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV2:
        backend.execute_calls += 1
        mapping = RuntimeSkillMappingResultV2(
            status="INVALID",
            rejection_reason="SAFETY_REJECTION",
            fallback_action=registry.fallback_action,
            fallback_required=True,
            gate_trace=[{"gate": "exact_plan", "status": "INVALID"}],
        )
        provisional = PhysicalSkillReceiptV2(
            receipt_id="contract-invalid-not-executed",
            receipt_sha256="0" * 64,
            executed_skill="NO_PHYSICAL_EXECUTION",
            execution_source="NO_PHYSICAL_EXECUTION",
            physically_executed=False,
            started_at_ns=120,
            completed_at_ns=121,
            schema_gate="PASS",
            stale_track_gate="PASS",
            frame_unit_gate="PASS",
            ik_gate="NOT_RUN",
            collision_gate="NOT_RUN",
            controller_gate="NOT_RUN",
            safety_gate="NOT_RUN",
            fallback_reason=(
                "PHYSICAL_FALLBACK_NOT_EXECUTED:"
                "NO_HASH_FROZEN_UNCHANGED_B0_ACTION_WRAPPER; SAFETY_REJECTION"
            ),
        )
        receipt = provisional.model_copy(
            update={"receipt_sha256": physical_receipt_sha256(provisional)}
        )
        return IsaacExecuteResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            inference_response_sha256=request.inference_response_sha256,
            mapping=mapping,
            requested_skill_was_physically_executed=False,
            physical_skill_receipts=[receipt],
        )

    backend.execute = fail_closed  # type: ignore[method-assign]
    execute = _call(
        endpoint,
        path=FORMAL_ISAAC_EXECUTE_PATH,
        message_type="ISAAC_EXECUTE_REQUEST",
        payload=IsaacExecuteRequestV2(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
            observation_id=capture.observation.observation_id,
            capture_receipt_sha256=capture.observation.capture_receipt_sha256,
            inference_response_sha256=DIGEST,
            executed_intent_history_sha256=DIGEST,
            runtime_request=_runtime(0),
        ),
        response_type="ISAAC_EXECUTE_RESPONSE",
        response_model=IsaacExecuteResponseV2,
    )
    receipt = execute.physical_skill_receipts[0]
    assert receipt.physically_executed is False
    assert endpoint.state.phase == "ABORTED_PHYSICAL_FAILURE"
    records = [json.loads(line) for line in endpoint.audit.service_path.read_text().splitlines()]
    event = next(
        record
        for record in records
        if record["event_type"] == "INVALID_MODEL_ACTION_FAILED_CLOSED_NO_PHYSICAL_FALLBACK"
    )
    assert event["payload"]["physically_executed"] is False


def test_backend_execute_exception_poisons_session_and_prevents_retry(
    tmp_path: Path,
) -> None:
    endpoint, backend = _endpoint(tmp_path)
    start = _call(
        endpoint,
        path=FORMAL_ISAAC_START_PATH,
        message_type="ISAAC_START_REQUEST",
        payload=_start_request(endpoint.binding),
        response_type="ISAAC_START_RESPONSE",
        response_model=IsaacStartResponseV2,
    )
    capture = _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH,
        message_type="ISAAC_CAPTURE_REQUEST",
        payload=IsaacCaptureRequestV2(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE",
        response_model=IsaacCaptureResponseV2,
    )
    request = IsaacExecuteRequestV2(
        run_id=start.run_id,
        session_id=start.session_id,
        decision_index=0,
        observation_id=capture.observation.observation_id,
        capture_receipt_sha256=capture.observation.capture_receipt_sha256,
        inference_response_sha256=DIGEST,
        executed_intent_history_sha256=DIGEST,
        runtime_request=_runtime(0),
    )

    def fail_after_possible_actuation(
        _request: IsaacExecuteRequestV2,
        _registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV2:
        backend.execute_calls += 1
        raise RuntimeError("backend response lost after possible actuation")

    backend.execute = fail_after_possible_actuation  # type: ignore[method-assign]
    signed = sign_wire_message("ISAAC_EXECUTE_REQUEST", request, SECRET).model_dump(mode="json")
    with pytest.raises(RuntimeError, match="response lost"):
        endpoint.handle(FORMAL_ISAAC_EXECUTE_PATH, signed)
    with pytest.raises(RuntimeError, match="poisoned"):
        endpoint.handle(FORMAL_ISAAC_EXECUTE_PATH, signed)
    assert backend.execute_calls == 1
    records = [json.loads(line) for line in endpoint.audit.service_path.read_text().splitlines()]
    rejection = next(
        record for record in reversed(records) if record["event_type"] == "WIRE_REQUEST_REJECTED"
    )
    assert rejection["payload"]["physical_execution_may_have_occurred"] is True


def test_signed_failed_execution_receipt_aborts_persistent_session(
    tmp_path: Path,
) -> None:
    endpoint, backend = _endpoint(tmp_path)
    start = _call(
        endpoint,
        path=FORMAL_ISAAC_START_PATH,
        message_type="ISAAC_START_REQUEST",
        payload=_start_request(endpoint.binding),
        response_type="ISAAC_START_RESPONSE",
        response_model=IsaacStartResponseV2,
    )
    capture = _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH,
        message_type="ISAAC_CAPTURE_REQUEST",
        payload=IsaacCaptureRequestV2(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE",
        response_model=IsaacCaptureResponseV2,
    )
    original_execute = backend.execute

    def failed_controller_receipt(
        request: IsaacExecuteRequestV2,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV2:
        response = original_execute(request, registry)
        receipt = response.physical_skill_receipts[0].model_copy(
            update={"controller_gate": "REJECTED", "receipt_sha256": "0" * 64}
        )
        receipt.receipt_sha256 = physical_receipt_sha256(receipt)
        return response.model_copy(update={"physical_skill_receipts": [receipt]})

    backend.execute = failed_controller_receipt  # type: ignore[method-assign]
    execute = _call(
        endpoint,
        path=FORMAL_ISAAC_EXECUTE_PATH,
        message_type="ISAAC_EXECUTE_REQUEST",
        payload=IsaacExecuteRequestV2(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
            observation_id=capture.observation.observation_id,
            capture_receipt_sha256=capture.observation.capture_receipt_sha256,
            inference_response_sha256=DIGEST,
            executed_intent_history_sha256=DIGEST,
            runtime_request=_runtime(0),
        ),
        response_type="ISAAC_EXECUTE_RESPONSE",
        response_model=IsaacExecuteResponseV2,
    )
    assert execute.physical_skill_receipts[0].controller_gate == "REJECTED"
    assert endpoint.state.phase == "ABORTED_PHYSICAL_FAILURE"
    with pytest.raises(RuntimeError, match="capture is not the next"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH,
            sign_wire_message(
                "ISAAC_CAPTURE_REQUEST",
                IsaacCaptureRequestV2(
                    run_id=start.run_id,
                    session_id=start.session_id,
                    decision_index=1,
                    previous_physical_receipt_sha256=(
                        execute.physical_skill_receipts[0].receipt_sha256
                    ),
                ),
                SECRET,
            ).model_dump(mode="json"),
        )
    assert backend.execute_calls == 1
