from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_m2c_exact_plan_primitive_bundle_v1 import (
    _binding,
    _make_binding_files,
    _make_plan,
)
from test_m2c_formal_public_observation_v4 import _formal
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPhaseExecutionV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    FormalExactPlanRuntimeV1,
    PerDecisionExactPlanBundleRuntimeV1,
    canonical_runtime_mapping_sha256_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    IsaacExecuteRequestV2,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacExecuteRequestV4,
    RuntimeSkillRequestV4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    MappingRejectionV2,
    ParameterProvenanceV2,
    RuntimeSkillMappingResultV2,
)


def _mapping() -> RuntimeSkillMappingResultV2:
    target = _formal().canonical_slots[0]
    assert target is not None
    return RuntimeSkillMappingResultV2(
        status="VALID",
        canonical_skill="LIFT",
        runtime_action="B0_CARTESIAN_LIFT",
        target_track_id=target,
        target_track_slot=0,
        parameters={"target_track_id": target},
        execution_parameters={"target_track_id": target},
        parameter_provenance={"target_track_id": ParameterProvenanceV2.MODEL},
        fallback_action="NO_PHYSICAL_EXECUTION",
        fallback_required=False,
        execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        gate_trace=[{"gate": "schema", "status": "PASS"}],
    )


def _request() -> IsaacExecuteRequestV4:
    observation = _formal()
    target = observation.canonical_slots[0]
    assert target is not None
    return IsaacExecuteRequestV4(
        run_id="formal-run-v4",
        session_id="formal-session-v4",
        decision_index=0,
        observation_id=observation.observation_id,
        capture_receipt_sha256=observation.capture_receipt_sha256,
        formal_observation_sha256=observation.wire_sha256,
        canonical_public_tracks_sha256=(observation.canonical_public_tracks_sha256),
        inference_response_sha256="a" * 64,
        executed_intent_history=[],
        executed_intent_history_sha256=canonical_sha256([]),
        observation=observation,
        runtime_request=RuntimeSkillRequestV4(
            canonical_public_tracks_sha256=(observation.canonical_public_tracks_sha256),
            model_class_id="coarse.skill.LIFT",
            skill="LIFT",
            model_target_track_id=target,
            model_target_slot=0,
            target_track_provenance=ParameterProvenanceV2.MODEL,
            canonical_track_ids=observation.canonical_slots,
            parameters={"target_track_id": target},
            parameter_provenance={"target_track_id": ParameterProvenanceV2.MODEL},
            coordinate_frame="world",
            units="m",
            current_phase="RECOVERY",
        ),
    )


def _bound_plan(
    tmp_path: Path,
    *,
    request: IsaacExecuteRequestV4 | None = None,
    mapping: RuntimeSkillMappingResultV2 | None = None,
    input_updates: dict[str, Any] | None = None,
) -> M2CExactPlanPrimitivePlanV1:
    request = request or _request()
    mapping = mapping or _mapping()
    observation = _formal()
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
        rgb_sha256=observation.rgb.sha256,
        depth_sha256=observation.depth.sha256,
        canonical_public_tracks_sha256=observation.canonical_public_tracks_sha256,
        signed_model_inference_response_sha256=request.inference_response_sha256,
        runtime_mapping_sha256=canonical_runtime_mapping_sha256_v1(mapping),
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


class _Provider:
    def __init__(self, plan: M2CExactPlanPrimitivePlanV1) -> None:
        self.plan = plan
        self.calls = 0

    def build_bound_plan(self, **_kwargs: Any) -> M2CExactPlanPrimitivePlanV1:
        self.calls += 1
        return self.plan


class _Bundle:
    def __init__(self, *, preflight_error: bool = False, execute_error: bool = False) -> None:
        self.preflight_error = preflight_error
        self.execute_error = execute_error
        self.preflight_calls = 0
        self.execute_calls = 0

    def preflight(self, plan: M2CExactPlanPrimitivePlanV1) -> ExactPlanPreflightReceiptV1:
        self.preflight_calls += 1
        if self.preflight_error:
            raise ExactPlanUnavailable("contract preflight failure")
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

    def execute(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        preflight: ExactPlanPreflightReceiptV1,
    ) -> ExactPlanBundleExecutionReceiptV1:
        self.execute_calls += 1
        if self.execute_error:
            raise RuntimeError("response lost after possible actuation")
        receipts = tuple(
            ExactPlanPhaseExecutionV1(
                bound_plan_sha256=plan.bound_plan_sha256,
                phase_index=phase.phase.phase_index,
                phase_sha256=phase.phase_sha256,
                started_at_ns=100 + phase.phase.phase_index * 10,
                completed_at_ns=105 + phase.phase.phase_index * 10,
                status="PASS",
                operation_executed=False,
                controller_outcome="contract-only",
                real_isaac=False,
                contract_test_only=True,
            )
            for phase in plan.phases
        )
        return ExactPlanBundleExecutionReceiptV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            preflight_receipt_sha256=preflight.receipt_sha256,
            phase_receipts=receipts,
            status="PASS",
            real_isaac=False,
            formal_evidence=False,
        )


def test_runtime_cross_binds_and_preflights_before_single_execution(tmp_path: Path) -> None:
    request = _request()
    mapping = _mapping()
    observation = _formal()
    provider = _Provider(_bound_plan(tmp_path, request=request, mapping=mapping))
    bundle = _Bundle()
    runtime = FormalExactPlanRuntimeV1(provider=provider, bundle=bundle)

    prepared = runtime.prepare(request=request, observation=observation, mapping=mapping)
    assert provider.calls == 1
    assert bundle.preflight_calls == 1
    assert bundle.execute_calls == 0
    assert prepared.bound_plan.inputs.canonical_public_tracks_sha256 == (
        observation.canonical_public_tracks_sha256
    )
    assert prepared.physical_execution_claimed is False

    receipt = runtime.execute_once(prepared)
    assert receipt.status == "PASS"
    assert receipt.formal_evidence is False
    assert bundle.execute_calls == 1
    with pytest.raises(ExactPlanUnavailable, match="absent or differs"):
        runtime.execute_once(prepared)
    assert bundle.execute_calls == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rgb_sha256", "f" * 64),
        ("canonical_public_tracks_sha256", "f" * 64),
        ("signed_model_inference_response_sha256", "f" * 64),
        ("runtime_mapping_sha256", "f" * 64),
    ],
)
def test_runtime_rejects_dynamic_a1_splice_before_preflight(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    request = _request()
    mapping = _mapping()
    provider = _Provider(
        _bound_plan(tmp_path, request=request, mapping=mapping, input_updates={field: value})
    )
    bundle = _Bundle()
    runtime = FormalExactPlanRuntimeV1(provider=provider, bundle=bundle)
    with pytest.raises(ExactPlanUnavailable, match="A.1 inputs differ"):
        runtime.prepare(request=request, observation=_formal(), mapping=mapping)
    assert bundle.preflight_calls == 0
    assert bundle.execute_calls == 0


def test_runtime_rejects_invalid_mapping_before_calling_provider(tmp_path: Path) -> None:
    request = _request()
    valid = _mapping()
    provider = _Provider(_bound_plan(tmp_path, request=request, mapping=valid))
    bundle = _Bundle()
    runtime = FormalExactPlanRuntimeV1(provider=provider, bundle=bundle)
    invalid = RuntimeSkillMappingResultV2(
        status="INVALID",
        rejection_reason=MappingRejectionV2.IK_REJECTION,
        fallback_action="NO_PHYSICAL_EXECUTION",
        fallback_required=True,
        execution_attribution="NO_PHYSICAL_EXECUTION",
    )
    with pytest.raises(ExactPlanUnavailable, match="only a VALID"):
        runtime.prepare(request=request, observation=_formal(), mapping=invalid)
    assert provider.calls == 0
    assert bundle.preflight_calls == 0


def test_runtime_rejects_legacy_v2_request_before_provider(tmp_path: Path) -> None:
    mapping = _mapping()
    provider = _Provider(_bound_plan(tmp_path, mapping=mapping))
    bundle = _Bundle()
    runtime = FormalExactPlanRuntimeV1(provider=provider, bundle=bundle)
    legacy_request = IsaacExecuteRequestV2.model_construct()

    with pytest.raises(ExactPlanUnavailable, match="requires a V4 execute request"):
        runtime.prepare(
            request=legacy_request,  # type: ignore[arg-type]
            observation=_formal(),
            mapping=mapping,
        )
    assert provider.calls == 0
    assert bundle.preflight_calls == 0
    assert bundle.execute_calls == 0


def test_runtime_preflight_failure_never_calls_executor(tmp_path: Path) -> None:
    request = _request()
    mapping = _mapping()
    bundle = _Bundle(preflight_error=True)
    runtime = FormalExactPlanRuntimeV1(
        provider=_Provider(_bound_plan(tmp_path, request=request, mapping=mapping)),
        bundle=bundle,
    )
    with pytest.raises(ExactPlanUnavailable, match="contract preflight failure"):
        runtime.prepare(request=request, observation=_formal(), mapping=mapping)
    assert bundle.execute_calls == 0


def test_runtime_consumes_plan_before_executor_exception(tmp_path: Path) -> None:
    request = _request()
    mapping = _mapping()
    bundle = _Bundle(execute_error=True)
    runtime = FormalExactPlanRuntimeV1(
        provider=_Provider(_bound_plan(tmp_path, request=request, mapping=mapping)),
        bundle=bundle,
    )
    prepared = runtime.prepare(request=request, observation=_formal(), mapping=mapping)
    with pytest.raises(RuntimeError, match="response lost"):
        runtime.execute_once(prepared)
    with pytest.raises(ExactPlanUnavailable, match="absent or differs"):
        runtime.execute_once(prepared)
    assert bundle.execute_calls == 1


def test_mapping_digest_excludes_gate_trace_but_binds_semantics() -> None:
    original = _mapping()
    changed_trace = original.model_copy(deep=True)
    changed_trace.gate_trace.append({"gate": "exact_plan", "status": "PASS"})
    assert canonical_runtime_mapping_sha256_v1(original) == (
        canonical_runtime_mapping_sha256_v1(changed_trace)
    )

    changed_target = original.model_copy(deep=True)
    changed_target.target_track_id = "track-ffffffff"
    assert canonical_runtime_mapping_sha256_v1(original) != (
        canonical_runtime_mapping_sha256_v1(changed_target)
    )


class _ProductionBundle(_Bundle):
    formal_execution_eligible = True

    def __init__(self, *, project_root: Path, binding: Any, execute_error: bool = False) -> None:
        super().__init__(execute_error=execute_error)
        self.project_root = project_root.resolve()
        self.binding = binding


class _BundleFactory:
    formal_execution_eligible = True

    def __init__(self, *, project_root: Path, binding: Any) -> None:
        self.project_root = project_root
        self.binding = binding
        self.bundles: list[_ProductionBundle] = []

    def build_bundle(self, _plan: M2CExactPlanPrimitivePlanV1) -> _ProductionBundle:
        bundle = _ProductionBundle(project_root=self.project_root, binding=self.binding)
        self.bundles.append(bundle)
        return bundle


def _production_binding(tmp_path: Path):  # noqa: ANN202
    bindings = _make_binding_files(tmp_path)
    plan = _make_plan(bindings)
    raw = _binding(tmp_path, bindings, plan).model_dump(mode="json")
    raw["execution_mode"] = "REAL_ISAAC"
    return type(_binding(tmp_path, bindings, plan)).model_validate(raw)


def test_per_decision_runtime_rotates_single_use_bundle_for_distinct_plans(
    tmp_path: Path,
) -> None:
    binding = _production_binding(tmp_path)
    factory = _BundleFactory(project_root=tmp_path, binding=binding)
    rotating = PerDecisionExactPlanBundleRuntimeV1(
        project_root=tmp_path,
        binding=binding,
        factory=factory,
    )
    first = _bound_plan(tmp_path)
    second_raw = first.model_dump(mode="json")
    second_raw["inputs"]["decision_index"] = 1
    second_raw["exact_execution_plan"]["decision_index"] = 1
    second_raw["exact_execution_plan_sha256"] = canonical_sha256(second_raw["exact_execution_plan"])
    second_raw["bound_plan_sha256"] = canonical_sha256(
        {key: value for key, value in second_raw.items() if key != "bound_plan_sha256"}
    )
    second = M2CExactPlanPrimitivePlanV1.model_validate(second_raw)

    first_preflight = rotating.preflight(first)
    first_receipt = rotating.execute(first, first_preflight)
    second_preflight = rotating.preflight(second)
    second_receipt = rotating.execute(second, second_preflight)

    assert first_receipt.status == second_receipt.status == "PASS"
    assert len(factory.bundles) == 2
    assert factory.bundles[0] is not factory.bundles[1]
    assert all(bundle.preflight_calls == bundle.execute_calls == 1 for bundle in factory.bundles)


def test_per_decision_runtime_consumes_failed_factory_attempt(tmp_path: Path) -> None:
    binding = _production_binding(tmp_path)

    class _FailingFactory(_BundleFactory):
        def build_bundle(self, _plan: M2CExactPlanPrimitivePlanV1) -> _ProductionBundle:
            raise ExactPlanUnavailable("production graph unavailable")

    rotating = PerDecisionExactPlanBundleRuntimeV1(
        project_root=tmp_path,
        binding=binding,
        factory=_FailingFactory(project_root=tmp_path, binding=binding),
    )
    plan = _bound_plan(tmp_path)
    with pytest.raises(ExactPlanUnavailable, match="production graph unavailable"):
        rotating.preflight(plan)
    with pytest.raises(ExactPlanUnavailable, match="already consumed"):
        rotating.preflight(plan)


def test_per_decision_runtime_consumes_before_executor_exception(tmp_path: Path) -> None:
    binding = _production_binding(tmp_path)

    class _FailingExecutionFactory(_BundleFactory):
        def build_bundle(self, _plan: M2CExactPlanPrimitivePlanV1) -> _ProductionBundle:
            bundle = _ProductionBundle(
                project_root=self.project_root,
                binding=self.binding,
                execute_error=True,
            )
            self.bundles.append(bundle)
            return bundle

    factory = _FailingExecutionFactory(project_root=tmp_path, binding=binding)
    rotating = PerDecisionExactPlanBundleRuntimeV1(
        project_root=tmp_path,
        binding=binding,
        factory=factory,
    )
    plan = _bound_plan(tmp_path)
    preflight = rotating.preflight(plan)
    with pytest.raises(RuntimeError, match="response lost"):
        rotating.execute(plan, preflight)
    with pytest.raises(ExactPlanUnavailable, match="absent or differs"):
        rotating.execute(plan, preflight)
