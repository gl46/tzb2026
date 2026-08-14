from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from test_m2c_exact_plan_primitive_bundle_v1 import _make_binding_files, _make_plan
from test_m2c_formal_public_observation_v4 import _depth, _rgb
from test_m2c_formal_split_runner_v4 import _bundle
from test_m2c_path_blocked_supervision_v4 import (
    attribute_binding,
    capture,
    deployment,
    journal,
    session_receipt,
)
from xh_agent.perception.public_track_associator_v2 import PublicTrackAssociatorV2
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPhaseExecutionV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v2 import AppendOnlyIsaacAuditLogV2
from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v4 import (
    FormalIsaacEndpointStateMachineV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
    formal_public_capture_receipt_v4,
    public_asset_inline_v4,
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
    ModelDecisionExecutionReceiptV4,
    RuntimeSkillRequestV4,
    canonical_runtime_mapping_sha256_v4,
    sign_isaac_wire_message_v4,
    validate_runtime_mapping_v4,
    verify_isaac_wire_message_v4,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
    PublicAssociationReplayFrameV4,
    associated_tracks_to_perception_tracks_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    RuntimeSkillMappingResultV2,
    RuntimeSkillRegistryV2,
    load_registry_v2,
)


ROOT = Path(__file__).resolve().parents[2]
SECRET = b"formal-v4-isaac-endpoint-test-key-32-bytes"


def _binding(observation: FormalPublicObservationV4) -> IsaacEndpointBindingV4:
    return IsaacEndpointBindingV4(
        endpoint_base_url="http://labserver:48134",
        host="labserver",
        implementation_path="src/formal-v4-endpoint.py",
        implementation_sha256="1" * 64,
        physical_backend_path="scripts/formal-v4-backend.py",
        physical_backend_sha256="2" * 64,
        public_observation_provider_path="src/public-v4-provider.py",
        public_observation_provider_sha256="3" * 64,
        formal_exact_plan_runtime_path="src/formal-exact-plan-v4.py",
        formal_exact_plan_runtime_sha256="4" * 64,
        bound_plan_provider_path="src/bound-plan-provider-v4.py",
        bound_plan_provider_sha256="5" * 64,
        primitive_bundle_path="src/exact-plan-bundle-v1.py",
        primitive_bundle_sha256="6" * 64,
        a3_deployment_binding_sha256="7" * 64,
        runtime_registry_path="configs/qrm_runtime_mapping_v2.yaml",
        runtime_registry_sha256="8" * 64,
        association_deployment_sha256=observation.association_deployment_sha256,
        capture_source_implementation_sha256=(
            observation.association_deployment.capture_source_implementation_sha256
        ),
        declared_attribute_selector_implementation_sha256=(
            observation.declared_attribute_binding.selector_source_implementation_sha256
        ),
        immutable_commit="9" * 40,
        container_image_digest="sha256:" + "a" * 64,
        transitive_dependency_manifest_sha256="b" * 64,
    )


def _observations(*, x_offset: float = 0.0) -> list[FormalPublicObservationV4]:
    captures = []
    previous = None
    for index in range(8):
        current = capture(
            1_000 + index * 1_000,
            [
                (0.01 + x_offset + index * 0.001, "yellow", 0.90),
                (0.31 + x_offset + index * 0.001, "blue", 0.95),
            ],
            previous=previous,
        )
        captures.append(current)
        previous = current

    frozen_deployment = deployment()
    frozen_attribute = attribute_binding()
    rgb = _rgb()
    depth = _depth()
    observations: list[FormalPublicObservationV4] = []
    previous_completed_at_ns = 50
    for index, current in enumerate(captures):
        prefix = captures[: index + 1]
        frozen_journal = journal(prefix)
        frozen_session = session_receipt(frozen_journal, frozen_deployment)
        associator = PublicTrackAssociatorV2(
            expected_deployment=frozen_deployment,
            expected_deployment_binding_sha256=(frozen_deployment.deployment_binding_sha256),
            expected_journal=frozen_journal,
            expected_session_receipt=frozen_session,
            expected_session_receipt_sha256=frozen_session.session_receipt_sha256,
        )
        frames: list[PublicAssociationReplayFrameV4] = []
        for item in prefix:
            associated = associator.associate(item)
            frames.append(
                PublicAssociationReplayFrameV4(
                    capture=item,
                    associated_tracks=associated,
                    associated_tracks_sha256=canonical_sha256(
                        [track.model_dump(mode="json") for track in associated]
                    ),
                )
            )
        tracks = associated_tracks_to_perception_tracks_v4(frames[-1].associated_tracks)
        candidates = build_public_track_candidates_v4(
            tracks,
            declared_target_attribute="yellow",
        )
        public = PathBlockedPublicObservationV4(
            schema_version="PathBlockedPublicObservationV4",
            observation_id=f"formal-v4-observation-{index}",
            captured_at_ns=current.timestamp_ns,
            source="PUBLIC_RGBD",
            fresh=True,
            rgb_uri=f"dataset://formal-v4/rgb/{index}.png",
            depth_uri=f"dataset://formal-v4/depth/{index}.npy",
            rgb_sha256=hashlib.sha256(rgb).hexdigest(),
            depth_sha256=hashlib.sha256(depth).hexdigest(),
            capture_receipt_sha256=current.capture_receipt_sha256,
            public_track_associator_revision="PublicTrackAssociatorV2",
            camera_frame=current.protocol.declared_camera_frame,
            position_units="m",
            calibration_sha256=current.protocol.calibration_sha256,
            association_history=frames,
            perception_tracks=tracks,
            declared_target_attribute="yellow",
            candidate_payload=canonical_candidate_payload_v4(candidates),
            candidate_payload_sha256=canonical_candidate_sha256_v4(candidates),
            teacher_used=False,
            privileged_truth_policy_input=False,
            task_target_track_id_used_for_candidates=False,
        )
        candidate_ids = [item.track_id for item in candidates]
        observations.append(
            FormalPublicObservationV4(
                observation=public,
                previous_physical_completed_at_ns=previous_completed_at_ns,
                rgb=public_asset_inline_v4(
                    uri=public.rgb_uri,
                    sha256=public.rgb_sha256,
                    media_type="image/png",
                    data=rgb,
                ),
                depth=public_asset_inline_v4(
                    uri=public.depth_uri,
                    sha256=public.depth_sha256,
                    media_type="application/x-npy",
                    data=depth,
                ),
                canonical_slots=[*candidate_ids, *([None] * (8 - len(candidate_ids)))],
                association_deployment=frozen_deployment,
                association_deployment_sha256=(frozen_deployment.deployment_binding_sha256),
                proprioception_journal=frozen_journal,
                proprioception_journal_sha256=frozen_journal.journal_sha256,
                association_session_receipt=frozen_session,
                association_session_receipt_sha256=(frozen_session.session_receipt_sha256),
                declared_attribute_binding=frozen_attribute,
                declared_attribute_binding_sha256=frozen_attribute.binding_sha256,
                formal_capture_receipt=formal_public_capture_receipt_v4(
                    observation=public,
                    association_deployment_sha256=(frozen_deployment.deployment_binding_sha256),
                    proprioception_journal_sha256=frozen_journal.journal_sha256,
                    association_session_receipt_sha256=(frozen_session.session_receipt_sha256),
                    declared_attribute_binding_sha256=frozen_attribute.binding_sha256,
                ),
            )
        )
        previous_completed_at_ns = current.timestamp_ns + 20
    return observations


def _runtime(
    observation: FormalPublicObservationV4, *, invalid: bool = False
) -> RuntimeSkillRequestV4:
    target = observation.canonical_slots[0]
    assert target is not None
    return RuntimeSkillRequestV4(
        canonical_public_tracks_sha256=observation.canonical_public_tracks_sha256,
        model_class_id="coarse.skill.UNKNOWN" if invalid else "coarse.skill.LIFT",
        skill="UNKNOWN" if invalid else "LIFT",
        model_target_track_id=target,
        model_target_slot=0,
        target_track_provenance="MODEL",
        canonical_track_ids=observation.canonical_slots,
        coordinate_frame="world",
        units="m",
        confidence=1.0,
    )


def _bound_plan(
    tmp_path: Path,
    request: IsaacExecuteRequestV4,
    mapping: RuntimeSkillMappingResultV2,
    *,
    input_updates: dict[str, Any] | None = None,
) -> M2CExactPlanPrimitivePlanV1:
    base = _make_plan(_make_binding_files(tmp_path))
    dumped = base.model_dump(mode="json")
    wire = dumped["exact_execution_plan"]
    wire.update(
        run_id=request.run_id,
        session_id=request.session_id,
        decision_index=request.decision_index,
        observation_id=request.observation_id,
        capture_receipt_sha256=request.capture_receipt_sha256,
        canonical_skill=mapping.canonical_skill,
        runtime_action=mapping.runtime_action,
        execution_parameters_sha256=canonical_sha256(mapping.execution_parameters),
        target_track_id=mapping.target_track_id,
    )
    dumped["exact_execution_plan_sha256"] = canonical_sha256(wire)
    inputs = dumped["inputs"]
    inputs.update(
        run_id=request.run_id,
        session_id=request.session_id,
        decision_index=request.decision_index,
        observation_id=request.observation_id,
        capture_receipt_sha256=request.capture_receipt_sha256,
        rgb_sha256=request.observation.rgb.sha256,
        depth_sha256=request.observation.depth.sha256,
        canonical_public_tracks_sha256=(request.observation.canonical_public_tracks_sha256),
        signed_model_inference_response_sha256=request.inference_response_sha256,
        runtime_mapping_sha256=canonical_runtime_mapping_sha256_v4(mapping),
        canonical_skill=mapping.canonical_skill,
        runtime_action=mapping.runtime_action,
        target_track_id=mapping.target_track_id,
        destination_cell=None,
        resolved_execution_parameters_sha256=canonical_sha256(mapping.execution_parameters),
    )
    inputs.update(input_updates or {})
    dumped["bound_plan_sha256"] = canonical_sha256(
        {key: value for key, value in dumped.items() if key != "bound_plan_sha256"}
    )
    return M2CExactPlanPrimitivePlanV1.model_validate(dumped)


def _preflight(plan: M2CExactPlanPrimitivePlanV1) -> ExactPlanPreflightReceiptV1:
    results = [
        ExactPlanPhasePreflightV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            preplan_state_sha256=plan.inputs.preplan_state_sha256,
            ik_algorithm_sha256="1" * 64,
            limits_configuration_sha256="2" * 64,
            swept_collision_algorithm_sha256="3" * 64,
            controller_configuration_sha256="4" * 64,
            safety_configuration_sha256="5" * 64,
        )
        for phase in plan.phases
    ]
    payload: dict[str, Any] = {
        "schema_version": "ExactPlanPreflightReceiptV1",
        "bound_plan_sha256": plan.bound_plan_sha256,
        "phase_results": [item.model_dump(mode="json") for item in results],
        "all_phases_passed_before_any_command": True,
    }
    return ExactPlanPreflightReceiptV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


def _execution(
    plan: M2CExactPlanPrimitivePlanV1,
    preflight: ExactPlanPreflightReceiptV1,
    *,
    time_floor: int,
) -> ExactPlanBundleExecutionReceiptV1:
    return ExactPlanBundleExecutionReceiptV1(
        bound_plan_sha256=plan.bound_plan_sha256,
        preflight_receipt_sha256=preflight.receipt_sha256,
        phase_receipts=tuple(
            ExactPlanPhaseExecutionV1(
                bound_plan_sha256=plan.bound_plan_sha256,
                phase_index=phase.phase.phase_index,
                phase_sha256=phase.phase_sha256,
                started_at_ns=time_floor + phase.phase.phase_index * 2,
                completed_at_ns=time_floor + phase.phase.phase_index * 2 + 1,
                status="PASS",
                operation_executed=True,
                controller_outcome="contract fixture; never formal evidence",
                real_isaac=True,
                contract_test_only=False,
            )
            for phase in plan.phases
        ),
        status="PASS",
        real_isaac=True,
        formal_evidence=True,
    )


def _receipt(
    *,
    index: int,
    observation: FormalPublicObservationV4,
    skill: str = "LIFT",
) -> ModelDecisionExecutionReceiptV4:
    payload: dict[str, Any] = {
        "schema_version": "ModelDecisionExecutionReceiptV4",
        "receipt_id": f"contract-only-execution-{index}",
        "selected_skill": skill,
        "execution_source": "MODEL_SELECTED_REGISTERED_SKILL",
        "operation_kind": "ROBOT_ACTUATION",
        "outcome": "PASS",
        "executed_in_real_isaac": True,
        "robot_actuation_executed": True,
        "started_at_ns": observation.captured_at_ns + 10,
        "completed_at_ns": observation.captured_at_ns + 20,
        "schema_gate": "PASS",
        "stale_track_gate": "PASS",
        "frame_unit_gate": "PASS",
        "ik_gate": "PASS",
        "collision_gate": "PASS",
        "controller_gate": "PASS",
        "safety_gate": "PASS",
        "collision_or_safety_violation": False,
        "failure_reason": None,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return ModelDecisionExecutionReceiptV4(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


class _Backend:
    formal_evidence = False
    real_physics = False

    def __init__(
        self,
        *,
        tmp_path: Path,
        binding: IsaacEndpointBindingV4,
        observations: list[FormalPublicObservationV4],
        plan_input_updates: dict[str, Any] | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.binding = binding
        self.observations = observations
        self.plan_input_updates = plan_input_updates
        self.execution_responses: list[IsaacExecuteResponseV4] = []

    def start(self, request: IsaacStartRequestV4) -> IsaacStartResponseV4:
        return IsaacStartResponseV4(
            run_id=request.run_id,
            session_id="contract-v4-session",
            start_request_sha256=canonical_sha256(request),
            failure_observed_at_ns=50,
            endpoint_binding_sha256=canonical_sha256(self.binding),
            implementation_sha256=self.binding.implementation_sha256,
            physical_backend_sha256=self.binding.physical_backend_sha256,
            public_observation_provider_sha256=(self.binding.public_observation_provider_sha256),
            formal_exact_plan_runtime_sha256=(self.binding.formal_exact_plan_runtime_sha256),
        )

    def capture(self, request: IsaacCaptureRequestV4) -> IsaacCaptureResponseV4:
        observation = self.observations[request.decision_index]
        return IsaacCaptureResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation=observation,
            formal_observation_sha256=observation.wire_sha256,
        )

    def execute(
        self,
        request: IsaacExecuteRequestV4,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV4:
        base = validate_runtime_mapping_v4(
            request.runtime_request,
            request.observation,
            registry,
        )
        if base.status == "INVALID":
            payload: dict[str, Any] = {
                "schema_version": "ModelDecisionExecutionReceiptV4",
                "receipt_id": f"contract-only-no-action-{request.decision_index}",
                "selected_skill": "NO_PHYSICAL_EXECUTION",
                "execution_source": "NO_PHYSICAL_EXECUTION",
                "operation_kind": "NO_PHYSICAL_EXECUTION",
                "outcome": "NOT_EXECUTED",
                "executed_in_real_isaac": False,
                "robot_actuation_executed": False,
                "started_at_ns": request.observation.captured_at_ns + 10,
                "completed_at_ns": request.observation.captured_at_ns + 20,
                "schema_gate": "PASS",
                "stale_track_gate": "NOT_RUN",
                "frame_unit_gate": "NOT_RUN",
                "ik_gate": "NOT_RUN",
                "collision_gate": "NOT_RUN",
                "controller_gate": "NOT_RUN",
                "safety_gate": "NOT_RUN",
                "collision_or_safety_violation": False,
                "failure_reason": "TERMINAL_NO_PHYSICAL_EXECUTION:INVALID_MAPPING",
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            receipt = ModelDecisionExecutionReceiptV4(
                **payload,
                receipt_sha256=canonical_sha256(payload),
            )
            return IsaacExecuteResponseV4(
                run_id=request.run_id,
                session_id=request.session_id,
                decision_index=request.decision_index,
                observation_id=request.observation_id,
                formal_observation_sha256=request.formal_observation_sha256,
                inference_response_sha256=request.inference_response_sha256,
                mapping=base,
                execution_receipts=[receipt],
                disposition="TERMINAL_NO_PHYSICAL_EXECUTION",
                terminal_failure_outcome=False,
                all_phase_preflight_before_any_command=False,
                model_operation_executed_in_real_isaac=False,
            )

        plan = _bound_plan(
            self.tmp_path,
            request,
            base,
            input_updates=self.plan_input_updates,
        )
        mapping = base.model_copy(
            update={
                "gate_trace": [
                    *base.gate_trace,
                    *[
                        {"gate": gate, "status": "PASS", "detail": "contract-only"}
                        for gate in ("ik", "collision", "controller", "safety")
                    ],
                    {
                        "gate": "exact_plan",
                        "status": "PASS",
                        "plan_sha256": plan.bound_plan_sha256,
                    },
                ]
            }
        )
        preflight = _preflight(plan)
        execution = _execution(
            plan,
            preflight,
            time_floor=request.observation.captured_at_ns + 11,
        )
        receipt = _receipt(
            index=request.decision_index,
            observation=request.observation,
        )
        response = IsaacExecuteResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            formal_observation_sha256=request.formal_observation_sha256,
            inference_response_sha256=request.inference_response_sha256,
            mapping=mapping,
            bound_plan=plan,
            bound_plan_sha256=plan.bound_plan_sha256,
            preflight_receipt=preflight,
            preflight_receipt_sha256=preflight.receipt_sha256,
            bundle_execution_receipt=execution,
            bundle_execution_receipt_sha256=canonical_sha256(execution),
            execution_receipts=[receipt],
            disposition="CONTINUE",
            all_phase_preflight_before_any_command=True,
            model_operation_executed_in_real_isaac=True,
        )
        self.execution_responses.append(response)
        return response

    def finalize(self, request: IsaacFinalizeRequestV4) -> IsaacFinalizeResponseV4:
        return IsaacFinalizeResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            evaluated_at_ns=self.observations[-1].captured_at_ns + 30,
            final_task_success=False,
        )


def _endpoint(
    tmp_path: Path,
    *,
    plan_input_updates: dict[str, Any] | None = None,
) -> tuple[
    FormalIsaacEndpointStateMachineV4,
    _Backend,
    list[FormalPublicObservationV4],
]:
    observations = _observations()
    binding = _binding(observations[0])
    backend = _Backend(
        tmp_path=tmp_path,
        binding=binding,
        observations=observations,
        plan_input_updates=plan_input_updates,
    )
    endpoint = FormalIsaacEndpointStateMachineV4(
        secret=SECRET,
        endpoint_binding=binding,
        registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        backend=backend,
        audit=AppendOnlyIsaacAuditLogV2(tmp_path / "audit"),
    )
    return endpoint, backend, observations


def _call(
    endpoint: FormalIsaacEndpointStateMachineV4,
    *,
    path: str,
    message_type: Any,
    payload: Any,
    response_type: Any,
    response_model: Any,
) -> Any:
    raw = sign_isaac_wire_message_v4(message_type, payload, SECRET).model_dump(mode="json")
    response = endpoint.handle(path, raw)
    return verify_isaac_wire_message_v4(
        response,
        SECRET,
        expected_type=response_type,
        model=response_model,
    )[1]


def _start(
    endpoint: FormalIsaacEndpointStateMachineV4,
) -> IsaacStartResponseV4:
    request = IsaacStartRequestV4(
        run_id="contract-v4-run",
        challenge_nonce="c" * 64,
        challenge_consumption_id="d" * 64,
        challenge_consumption_receipt_sha256="e" * 64,
        matched_key="contract-v4-key",
        scene_seed=1,
        failure_seed=2,
        sdf_sha256="f" * 64,
        supervision_sha256="0" * 64,
        endpoint_binding_sha256=canonical_sha256(endpoint.binding),
        declared_target_attribute="yellow",
        declared_attribute_binding_sha256=(
            endpoint.backend.observations[0].declared_attribute_binding_sha256
        ),
        bundle=_bundle(),
    )
    return _call(
        endpoint,
        path=FORMAL_ISAAC_START_PATH_V4,
        message_type="ISAAC_START_REQUEST_V4",
        payload=request,
        response_type="ISAAC_START_RESPONSE_V4",
        response_model=IsaacStartResponseV4,
    )


def _execute_request(
    observation: FormalPublicObservationV4,
    *,
    index: int,
    invalid: bool = False,
    history: tuple[PublicExecutedIntentHistoryItemV2, ...] = (),
) -> IsaacExecuteRequestV4:
    return IsaacExecuteRequestV4(
        run_id="contract-v4-run",
        session_id="contract-v4-session",
        decision_index=index,
        observation_id=observation.observation_id,
        capture_receipt_sha256=observation.capture_receipt_sha256,
        formal_observation_sha256=observation.wire_sha256,
        canonical_public_tracks_sha256=observation.canonical_public_tracks_sha256,
        inference_response_sha256=hashlib.sha256(f"inference-{index}".encode()).hexdigest(),
        executed_intent_history=list(history),
        executed_intent_history_sha256=canonical_sha256(history),
        observation=observation,
        runtime_request=_runtime(observation, invalid=invalid),
    )


def test_v4_state_machine_runs_exact_eight_cycle_contract_and_finalizes(
    tmp_path: Path,
) -> None:
    endpoint, backend, observations = _endpoint(tmp_path)
    start = _start(endpoint)
    previous_receipt = None
    history: tuple[PublicExecutedIntentHistoryItemV2, ...] = ()
    last_response = None
    for index, observation in enumerate(observations):
        capture_response = _call(
            endpoint,
            path=FORMAL_ISAAC_CAPTURE_PATH_V4,
            message_type="ISAAC_CAPTURE_REQUEST_V4",
            payload=IsaacCaptureRequestV4(
                run_id=start.run_id,
                session_id=start.session_id,
                decision_index=index,
                previous_execution_receipt_sha256=previous_receipt,
            ),
            response_type="ISAAC_CAPTURE_RESPONSE_V4",
            response_model=IsaacCaptureResponseV4,
        )
        assert capture_response.observation == observation
        last_response = _call(
            endpoint,
            path=FORMAL_ISAAC_EXECUTE_PATH_V4,
            message_type="ISAAC_EXECUTE_REQUEST_V4",
            payload=_execute_request(observation, index=index, history=history),
            response_type="ISAAC_EXECUTE_RESPONSE_V4",
            response_model=IsaacExecuteResponseV4,
        )
        assert last_response.disposition == "CONTINUE"
        previous_receipt = last_response.execution_receipts[0].receipt_sha256
        history = endpoint.state.executed_intent_history
    assert last_response is not None
    finalized = _call(
        endpoint,
        path=FORMAL_ISAAC_FINALIZE_PATH_V4,
        message_type="ISAAC_FINALIZE_REQUEST_V4",
        payload=IsaacFinalizeRequestV4(
            run_id=start.run_id,
            session_id=start.session_id,
            last_execution_receipt_sha256=(last_response.execution_receipts[0].receipt_sha256),
            last_bundle_execution_receipt_sha256=(last_response.bundle_execution_receipt_sha256),
        ),
        response_type="ISAAC_FINALIZE_RESPONSE_V4",
        response_model=IsaacFinalizeResponseV4,
    )
    assert finalized.final_task_success is False
    assert len(backend.execution_responses) == 8
    assert endpoint.state.phase == "FINALIZED"
    records = [
        json.loads(line)
        for line in endpoint.audit.service_path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = [record["event_type"] for record in records]
    assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
    assert event_types.count("WIRE_REQUEST_RECEIVED") == 18
    assert event_types.count("WIRE_RESPONSE_COMMITTED") == 18
    assert event_types.count("EXACT_EXECUTION_PLAN_EXECUTED_V4") == 8
    assert "WIRE_REQUEST_REJECTED" not in event_types
    assert "ISAAC_V4_TERMINAL_FAILURE_COMMITTED" not in event_types


def test_v4_invalid_mapping_is_terminal_no_action_and_cannot_retry(tmp_path: Path) -> None:
    endpoint, _, observations = _endpoint(tmp_path)
    start = _start(endpoint)
    _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH_V4,
        message_type="ISAAC_CAPTURE_REQUEST_V4",
        payload=IsaacCaptureRequestV4(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE_V4",
        response_model=IsaacCaptureResponseV4,
    )
    response = _call(
        endpoint,
        path=FORMAL_ISAAC_EXECUTE_PATH_V4,
        message_type="ISAAC_EXECUTE_REQUEST_V4",
        payload=_execute_request(observations[0], index=0, invalid=True),
        response_type="ISAAC_EXECUTE_RESPONSE_V4",
        response_model=IsaacExecuteResponseV4,
    )
    assert response.disposition == "TERMINAL_NO_PHYSICAL_EXECUTION"
    assert response.execution_receipts[0].robot_actuation_executed is False
    assert endpoint.state.phase == "TERMINAL_FAILURE"
    with pytest.raises(RuntimeError, match="not the next"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH_V4,
            sign_isaac_wire_message_v4(
                "ISAAC_CAPTURE_REQUEST_V4",
                IsaacCaptureRequestV4(
                    run_id=start.run_id,
                    session_id=start.session_id,
                    decision_index=0,
                    previous_execution_receipt_sha256=(
                        response.execution_receipts[0].receipt_sha256
                    ),
                ),
                SECRET,
            ).model_dump(mode="json"),
        )


def test_v4_execute_response_audit_failure_poisoned_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, backend, observations = _endpoint(tmp_path)
    start = _start(endpoint)
    _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH_V4,
        message_type="ISAAC_CAPTURE_REQUEST_V4",
        payload=IsaacCaptureRequestV4(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE_V4",
        response_model=IsaacCaptureResponseV4,
    )
    original_append = endpoint.audit.append
    observed_events: list[tuple[str, dict[str, Any]]] = []

    def fail_execute_response_commit(event_type: str, payload: Any) -> None:
        copied = dict(payload)
        if (
            event_type == "WIRE_RESPONSE_COMMITTED"
            and copied.get("path") == FORMAL_ISAAC_EXECUTE_PATH_V4
        ):
            raise OSError("contract audit commit failure")
        observed_events.append((event_type, copied))
        original_append(event_type, copied)

    monkeypatch.setattr(endpoint.audit, "append", fail_execute_response_commit)
    with pytest.raises(OSError, match="contract audit commit failure"):
        _call(
            endpoint,
            path=FORMAL_ISAAC_EXECUTE_PATH_V4,
            message_type="ISAAC_EXECUTE_REQUEST_V4",
            payload=_execute_request(observations[0], index=0),
            response_type="ISAAC_EXECUTE_RESPONSE_V4",
            response_model=IsaacExecuteResponseV4,
        )
    assert len(backend.execution_responses) == 1
    assert observed_events[-1][0] == "WIRE_REQUEST_REJECTED"
    assert observed_events[-1][1]["physical_execution_may_have_occurred"] is True

    with pytest.raises(RuntimeError, match="session is poisoned"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH_V4,
            sign_isaac_wire_message_v4(
                "ISAAC_CAPTURE_REQUEST_V4",
                IsaacCaptureRequestV4(
                    run_id=start.run_id,
                    session_id=start.session_id,
                    decision_index=1,
                ),
                SECRET,
            ).model_dump(mode="json"),
        )


def test_v4_endpoint_replays_dynamic_a1_inputs_and_rejects_self_consistent_splice(
    tmp_path: Path,
) -> None:
    endpoint, backend, observations = _endpoint(
        tmp_path,
        plan_input_updates={"rgb_sha256": "f" * 64},
    )
    start = _start(endpoint)
    _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH_V4,
        message_type="ISAAC_CAPTURE_REQUEST_V4",
        payload=IsaacCaptureRequestV4(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE_V4",
        response_model=IsaacCaptureResponseV4,
    )
    with pytest.raises(ExactPlanUnavailable, match="A.1 inputs differ"):
        _call(
            endpoint,
            path=FORMAL_ISAAC_EXECUTE_PATH_V4,
            message_type="ISAAC_EXECUTE_REQUEST_V4",
            payload=_execute_request(observations[0], index=0),
            response_type="ISAAC_EXECUTE_RESPONSE_V4",
            response_model=IsaacExecuteResponseV4,
        )
    assert len(backend.execution_responses) == 1
    with pytest.raises(RuntimeError, match="session is poisoned"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH_V4,
            sign_isaac_wire_message_v4(
                "ISAAC_CAPTURE_REQUEST_V4",
                IsaacCaptureRequestV4(
                    run_id=start.run_id,
                    session_id=start.session_id,
                    decision_index=1,
                ),
                SECRET,
            ).model_dump(mode="json"),
        )


def test_v4_state_machine_rejects_out_of_order_and_nonprefix_capture(
    tmp_path: Path,
) -> None:
    endpoint, backend, observations = _endpoint(tmp_path)
    with pytest.raises(RuntimeError, match="not the next"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH_V4,
            sign_isaac_wire_message_v4(
                "ISAAC_CAPTURE_REQUEST_V4",
                IsaacCaptureRequestV4(
                    run_id="contract-v4-run",
                    session_id="contract-v4-session",
                    decision_index=0,
                ),
                SECRET,
            ).model_dump(mode="json"),
        )
    start = _start(endpoint)
    _call(
        endpoint,
        path=FORMAL_ISAAC_CAPTURE_PATH_V4,
        message_type="ISAAC_CAPTURE_REQUEST_V4",
        payload=IsaacCaptureRequestV4(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
        ),
        response_type="ISAAC_CAPTURE_RESPONSE_V4",
        response_model=IsaacCaptureResponseV4,
    )
    first_response = _call(
        endpoint,
        path=FORMAL_ISAAC_EXECUTE_PATH_V4,
        message_type="ISAAC_EXECUTE_REQUEST_V4",
        payload=_execute_request(observations[0], index=0, history=()),
        response_type="ISAAC_EXECUTE_RESPONSE_V4",
        response_model=IsaacExecuteResponseV4,
    )
    # This observation is independently replay-valid under the same deployment
    # and timestamps, but its first capture belongs to a different history.
    backend.observations[1] = _observations(x_offset=0.08)[1]
    with pytest.raises(ValueError, match="strict exact extension"):
        endpoint.handle(
            FORMAL_ISAAC_CAPTURE_PATH_V4,
            sign_isaac_wire_message_v4(
                "ISAAC_CAPTURE_REQUEST_V4",
                IsaacCaptureRequestV4(
                    run_id=start.run_id,
                    session_id=start.session_id,
                    decision_index=1,
                    previous_execution_receipt_sha256=(
                        first_response.execution_receipts[0].receipt_sha256
                    ),
                ),
                SECRET,
            ).model_dump(mode="json"),
        )


def test_v4_schema_rejects_invalid_receipt_that_claims_plan_or_b0() -> None:
    observations = _observations()
    registry = load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml")
    request = _execute_request(observations[0], index=0, invalid=True)
    mapping = validate_runtime_mapping_v4(request.runtime_request, request.observation, registry)
    payload: dict[str, Any] = {
        "schema_version": "ModelDecisionExecutionReceiptV4",
        "receipt_id": "bad-b0",
        "selected_skill": "B0_SAFE_HOLD",
        "execution_source": "NO_PHYSICAL_EXECUTION",
        "operation_kind": "NO_PHYSICAL_EXECUTION",
        "outcome": "NOT_EXECUTED",
        "executed_in_real_isaac": False,
        "robot_actuation_executed": False,
        "started_at_ns": observations[0].captured_at_ns + 1,
        "completed_at_ns": observations[0].captured_at_ns + 2,
        "schema_gate": "PASS",
        "stale_track_gate": "NOT_RUN",
        "frame_unit_gate": "NOT_RUN",
        "ik_gate": "NOT_RUN",
        "collision_gate": "NOT_RUN",
        "controller_gate": "NOT_RUN",
        "safety_gate": "NOT_RUN",
        "collision_or_safety_violation": False,
        "failure_reason": "TERMINAL_NO_PHYSICAL_EXECUTION:INVALID_MAPPING",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    with pytest.raises(ValueError, match="no-action receipt has execution claims"):
        ModelDecisionExecutionReceiptV4(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
    payload["selected_skill"] = "NO_PHYSICAL_EXECUTION"
    payload["collision_or_safety_violation"] = True
    with pytest.raises(ValueError, match="no-action receipt has execution claims"):
        ModelDecisionExecutionReceiptV4(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
    assert mapping.status == "INVALID"
    assert mapping.fallback_action == "NO_PHYSICAL_EXECUTION"
