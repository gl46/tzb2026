from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_m2c_formal_isaac_endpoint_v4 import (
    ROOT,
    _binding,
    _bound_plan,
    _execute_request,
    _observations,
    _preflight,
)
from test_m2c_formal_split_runner_v4 import _bundle
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPhaseExecutionV1,
    ExactPlanUnavailable,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    FormalExactPlanGateRejectionV1,
    FormalExactPlanRuntimeV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_backend_v4 import (
    FormalIsaacBackendCoordinatorV4,
    FormalIsaacEpisodeStartReceiptV4,
    FormalIsaacFinalEvaluationReceiptV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacCaptureRequestV4,
    IsaacEndpointBindingV4,
    IsaacExecuteRequestV4,
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacStartRequestV4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    MappingRejectionV2,
    RuntimeSkillMappingResultV2,
    load_registry_v2,
)


class _ObservationProvider:
    mode = "REAL_ISAAC"

    def __init__(self, observations: list[Any]) -> None:
        self.observations = observations
        self.deployment = observations[0].association_deployment
        self.attribute_binding = observations[0].declared_attribute_binding
        self.session: tuple[str, str] | None = None
        self.calls: list[dict[str, Any]] = []

    def begin_session(self, *, run_id: str, session_id: str) -> None:
        if self.session is not None:
            raise RuntimeError("contract observation provider is single-use")
        self.session = (run_id, session_id)

    def capture(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        observation = self.observations[int(kwargs["decision_index"])]
        if (
            observation.previous_physical_completed_at_ns
            != kwargs["previous_execution_completed_at_ns"]
        ):
            raise ValueError("contract observation completion chain differs")
        return observation


class _Lifecycle:
    real_isaac = True
    mocked_physics = False

    def __init__(self, binding: IsaacEndpointBindingV4) -> None:
        self.binding = binding
        self.implementation_sha256 = binding.physical_backend_sha256
        self.start_calls = 0
        self.finalize_calls = 0
        self.execution_commits: list[tuple[IsaacExecuteRequestV4, Any]] = []

    def commit_public_execution_v4(
        self,
        *,
        request: IsaacExecuteRequestV4,
        receipt: Any,
    ) -> None:
        self.execution_commits.append((request, receipt))

    def start_episode(
        self,
        request: IsaacStartRequestV4,
    ) -> FormalIsaacEpisodeStartReceiptV4:
        self.start_calls += 1
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacEpisodeStartReceiptV4",
            "run_id": request.run_id,
            "session_id": "contract-v4-session",
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
            "declared_attribute_binding_sha256": request.declared_attribute_binding_sha256,
            "qwen_bundle_sha256": canonical_sha256(request.bundle),
            "failure_observed_at_ns": 50,
            "public_failure_boundary_evidence_sha256": "a" * 64,
            "failure_boundary_derived_from_public_observation": True,
            "real_isaac": True,
            "mocked_physics": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return FormalIsaacEpisodeStartReceiptV4(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )

    def finalize_episode(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacFinalEvaluationReceiptV4:
        self.finalize_calls += 1
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacFinalEvaluationReceiptV4",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "finalize_request_sha256": canonical_sha256(request),
            "last_execution_receipt_sha256": request.last_execution_receipt_sha256,
            "last_bundle_execution_receipt_sha256": (request.last_bundle_execution_receipt_sha256),
            "execution_response_sha256": tuple(
                canonical_sha256(item) for item in execution_responses
            ),
            "public_evaluation_evidence_sha256": "e" * 64,
            "evaluated_at_ns": 9_000,
            "final_task_success": False,
            "completed_model_decisions": 8,
            "outcome_used_as_policy_input": False,
            "real_isaac": True,
            "mocked_physics": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return FormalIsaacFinalEvaluationReceiptV4(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )


class _PlanProvider:
    formal_execution_eligible = True

    def __init__(
        self,
        tmp_path: Path,
        *,
        gate_rejection: FormalExactPlanGateRejectionV1 | None = None,
        generic_failure: bool = False,
    ) -> None:
        self.tmp_path = tmp_path
        self.gate_rejection = gate_rejection
        self.generic_failure = generic_failure
        self.calls = 0

    def build_bound_plan(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: Any,
        mapping: RuntimeSkillMappingResultV2,
    ) -> Any:
        del observation
        self.calls += 1
        if self.gate_rejection is not None:
            raise self.gate_rejection
        if self.generic_failure:
            raise ExactPlanUnavailable("unclassified provider failure")
        return _bound_plan(self.tmp_path, request, mapping)


class _RealBundle:
    formal_execution_eligible = True

    def __init__(self, *, partial_before_command: bool = False) -> None:
        self.partial_before_command = partial_before_command
        self.execute_calls = 0

    def preflight(self, plan: Any) -> Any:
        return _preflight(plan)

    def execute(self, plan: Any, preflight: Any) -> ExactPlanBundleExecutionReceiptV1:
        self.execute_calls += 1
        captured_at_ns = 1_000 + plan.exact_execution_plan.decision_index * 1_000
        if self.partial_before_command:
            phase = plan.phases[0]
            phase_receipts = (
                ExactPlanPhaseExecutionV1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    phase_index=phase.phase.phase_index,
                    phase_sha256=phase.phase_sha256,
                    started_at_ns=captured_at_ns + 10,
                    completed_at_ns=captured_at_ns + 20,
                    status="FAILED",
                    operation_executed=False,
                    controller_outcome="controller did not accept first command",
                    real_isaac=True,
                    contract_test_only=False,
                ),
            )
            status = "PARTIAL_FAILURE"
        else:
            phase_receipts = tuple(
                ExactPlanPhaseExecutionV1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    phase_index=phase.phase.phase_index,
                    phase_sha256=phase.phase_sha256,
                    started_at_ns=captured_at_ns + 1 + index,
                    completed_at_ns=(
                        captured_at_ns + 20
                        if index == len(plan.phases) - 1
                        else captured_at_ns + 2 + index
                    ),
                    status="PASS",
                    operation_executed=True,
                    controller_outcome="contract fixture; not experiment evidence",
                    real_isaac=True,
                    contract_test_only=False,
                )
                for index, phase in enumerate(plan.phases)
            )
            status = "PASS"
        return ExactPlanBundleExecutionReceiptV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            preflight_receipt_sha256=preflight.receipt_sha256,
            phase_receipts=phase_receipts,
            status=status,
            real_isaac=True,
            formal_evidence=True,
        )


def _start_request(binding: IsaacEndpointBindingV4) -> IsaacStartRequestV4:
    observations = _observations()
    return IsaacStartRequestV4(
        run_id="contract-v4-run",
        challenge_nonce="c" * 64,
        challenge_consumption_id="d" * 64,
        challenge_consumption_receipt_sha256="e" * 64,
        matched_key="contract-v4-key",
        scene_seed=1,
        failure_seed=2,
        sdf_sha256="f" * 64,
        supervision_sha256="0" * 64,
        endpoint_binding_sha256=canonical_sha256(binding),
        declared_target_attribute="yellow",
        declared_attribute_binding_sha256=(observations[0].declared_attribute_binding_sha256),
        bundle=_bundle(),
    )


def _backend(
    tmp_path: Path,
    *,
    plan_provider: _PlanProvider | None = None,
    bundle: _RealBundle | None = None,
    clock_values: list[int] | None = None,
) -> tuple[
    FormalIsaacBackendCoordinatorV4,
    _Lifecycle,
    _ObservationProvider,
    _PlanProvider,
    _RealBundle,
]:
    observations = _observations()
    binding = _binding(observations[0])
    lifecycle = _Lifecycle(binding)
    observation_provider = _ObservationProvider(observations)
    plan_provider = plan_provider or _PlanProvider(tmp_path)
    bundle = bundle or _RealBundle()
    values = iter(clock_values or [100_000, 100_001])
    backend = FormalIsaacBackendCoordinatorV4(
        endpoint_binding=binding,
        lifecycle=lifecycle,
        observation_provider=observation_provider,  # type: ignore[arg-type]
        observation_provider_implementation_sha256=(binding.public_observation_provider_sha256),
        exact_plan_runtime=FormalExactPlanRuntimeV1(
            provider=plan_provider,
            bundle=bundle,
        ),
        exact_plan_runtime_implementation_sha256=(binding.formal_exact_plan_runtime_sha256),
        runtime_registry_sha256=binding.runtime_registry_sha256,
        now_ns=lambda: next(values),
    )
    return backend, lifecycle, observation_provider, plan_provider, bundle


def _start_and_capture(
    backend: FormalIsaacBackendCoordinatorV4,
    *,
    index: int = 0,
    previous_receipt: str | None = None,
) -> Any:
    if index == 0:
        backend.start(_start_request(backend.binding))
    return backend.capture(
        IsaacCaptureRequestV4(
            run_id="contract-v4-run",
            session_id="contract-v4-session",
            decision_index=index,
            previous_execution_receipt_sha256=previous_receipt,
        )
    )


def test_backend_composes_exact_eight_cycle_and_public_finalize(tmp_path: Path) -> None:
    backend, lifecycle, provider, plan_provider, bundle = _backend(tmp_path)
    start = backend.start(_start_request(backend.binding))
    registry = load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml")
    history: tuple[PublicExecutedIntentHistoryItemV2, ...] = ()
    previous_receipt = None
    last_response = None
    for index, observation in enumerate(_observations()):
        capture_response = backend.capture(
            IsaacCaptureRequestV4(
                run_id=start.run_id,
                session_id=start.session_id,
                decision_index=index,
                previous_execution_receipt_sha256=previous_receipt,
            )
        )
        assert capture_response.observation == observation
        last_response = backend.execute(
            _execute_request(observation, index=index, history=history),
            registry,
        )
        assert last_response.disposition == "CONTINUE"
        previous_receipt = last_response.execution_receipts[0].receipt_sha256
        if index < 7:
            history = (
                *history,
                PublicExecutedIntentHistoryItemV2(
                    decision_index=index,
                    selected_skill=str(last_response.mapping.canonical_skill),
                    target_track_id=last_response.mapping.target_track_id,
                    destination_cell=None,
                    physical_receipt_sha256=previous_receipt,
                    execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
                ),
            )
    assert last_response is not None
    finalized = backend.finalize(
        IsaacFinalizeRequestV4(
            run_id=start.run_id,
            session_id=start.session_id,
            last_execution_receipt_sha256=(last_response.execution_receipts[0].receipt_sha256),
            last_bundle_execution_receipt_sha256=(last_response.bundle_execution_receipt_sha256),
        )
    )
    assert finalized.final_task_success is False
    assert lifecycle.start_calls == lifecycle.finalize_calls == 1
    assert [item[0].decision_index for item in lifecycle.execution_commits] == list(range(8))
    assert len(provider.calls) == plan_provider.calls == bundle.execute_calls == 8


def test_backend_static_invalid_mapping_is_terminal_without_plan(tmp_path: Path) -> None:
    backend, _, _, provider, bundle = _backend(
        tmp_path,
        clock_values=[1_010, 1_020],
    )
    capture_response = _start_and_capture(backend)
    response = backend.execute(
        _execute_request(capture_response.observation, index=0, invalid=True),
        load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
    )
    assert response.disposition == "TERMINAL_NO_PHYSICAL_EXECUTION"
    assert response.execution_receipts[0].robot_actuation_executed is False
    assert provider.calls == bundle.execute_calls == 0
    with pytest.raises(RuntimeError, match="not currently allowed"):
        backend.capture(
            IsaacCaptureRequestV4(
                run_id="contract-v4-run",
                session_id="contract-v4-session",
                decision_index=0,
            )
        )


def test_backend_only_terminalizes_typed_non_actuating_gate_rejection(
    tmp_path: Path,
) -> None:
    rejection = FormalExactPlanGateRejectionV1(
        gate="collision",
        rejection_reason=MappingRejectionV2.COLLISION_REJECTION,
        detail="frozen swept-volume gate rejected phase 0",
    )
    provider = _PlanProvider(tmp_path, gate_rejection=rejection)
    backend, _, _, _, bundle = _backend(
        tmp_path,
        plan_provider=provider,
        clock_values=[1_010, 1_020],
    )
    observation = _start_and_capture(backend).observation
    response = backend.execute(
        _execute_request(observation, index=0),
        load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
    )
    assert response.mapping.rejection_reason == MappingRejectionV2.COLLISION_REJECTION
    assert response.execution_receipts[0].collision_gate == "REJECTED"
    assert response.disposition == "TERMINAL_NO_PHYSICAL_EXECUTION"
    assert provider.calls == 1
    assert bundle.execute_calls == 0
    with pytest.raises(RuntimeError, match="lacks its exact active capture"):
        backend.execute(
            _execute_request(observation, index=0),
            load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        )
    assert provider.calls == 1


def test_typed_gate_rejection_rejects_mismatched_classification() -> None:
    with pytest.raises(ValueError, match="classification differs"):
        FormalExactPlanGateRejectionV1(
            gate="ik",
            rejection_reason=MappingRejectionV2.COLLISION_REJECTION,
            detail="crossed classification",
        )
    with pytest.raises(ValueError, match="lacks a frozen detail"):
        FormalExactPlanGateRejectionV1(
            gate="safety",
            rejection_reason=MappingRejectionV2.SAFETY_REJECTION,
            detail=" ",
        )


def test_backend_does_not_launder_unclassified_runtime_failure(tmp_path: Path) -> None:
    backend, _, _, provider, bundle = _backend(
        tmp_path,
        plan_provider=_PlanProvider(tmp_path, generic_failure=True),
    )
    observation = _start_and_capture(backend).observation
    with pytest.raises(ExactPlanUnavailable, match="unclassified provider failure"):
        backend.execute(
            _execute_request(observation, index=0),
            load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        )
    assert provider.calls == 1
    assert bundle.execute_calls == 0


def test_backend_partial_failure_before_command_is_honest_and_terminal(
    tmp_path: Path,
) -> None:
    backend, _, _, _, bundle = _backend(
        tmp_path,
        bundle=_RealBundle(partial_before_command=True),
    )
    observation = _start_and_capture(backend).observation
    response = backend.execute(
        _execute_request(observation, index=0),
        load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
    )
    receipt = response.execution_receipts[0]
    assert response.disposition == "TERMINAL_EXECUTION_FAILURE"
    assert response.model_operation_executed_in_real_isaac is False
    assert receipt.executed_in_real_isaac is True
    assert receipt.robot_actuation_executed is False
    assert receipt.outcome == "FAILED"
    assert bundle.execute_calls == 1


def test_backend_rejects_crossed_lifecycle_start_receipt(tmp_path: Path) -> None:
    backend, _, _, _, _ = _backend(tmp_path)
    request = _start_request(backend.binding)
    original = backend.lifecycle.start_episode

    def crossed(start_request: IsaacStartRequestV4) -> FormalIsaacEpisodeStartReceiptV4:
        receipt = original(start_request)
        raw = receipt.model_dump(mode="json")
        raw["matched_key"] = "other-key"
        raw["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in raw.items() if key != "receipt_sha256"}
        )
        return FormalIsaacEpisodeStartReceiptV4.model_validate(raw)

    backend.lifecycle.start_episode = crossed  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="crosses its request"):
        backend.start(request)
