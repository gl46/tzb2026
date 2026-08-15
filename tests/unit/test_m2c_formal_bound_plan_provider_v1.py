from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_m2c_formal_exact_plan_runtime_v1 import _bound_plan, _mapping, _request
from test_m2c_formal_public_observation_v4 import _formal
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanUnavailable,
)
from xh_agent.policy.qrm_lite.formal_bound_plan_provider_v1 import (
    BoundExactPlanSynthesisResultV1,
    FormalBoundExactPlanProviderV1,
    FormalPreplanStateReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    canonical_runtime_mapping_sha256_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


class _Backend:
    implementation_sha256 = "8" * 64

    def __init__(
        self,
        tmp_path: Path,
        *,
        real_isaac: bool = False,
        mocked_physics: bool = True,
        state_updates: dict[str, Any] | None = None,
        raises: bool = False,
    ) -> None:
        self.tmp_path = tmp_path
        self.real_isaac = real_isaac
        self.mocked_physics = mocked_physics
        self.state_updates = state_updates or {}
        self.raises = raises
        self.calls = 0

    def synthesize_bound_plan(self, *, request, observation, mapping):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.raises:
            raise RuntimeError("query-only synthesis backend failed")
        plan = _bound_plan(
            self.tmp_path,
            request=request,
            mapping=mapping,
            input_updates={
                "preplan_state_timestamp_ns": observation.captured_at_ns + 1,
                "plan_constructed_at_ns": observation.captured_at_ns + 2,
            },
        )
        state_payload: dict[str, Any] = {
            "schema_version": "FormalPreplanStateReceiptV1",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "plan_synthesis_state_sha256": plan.inputs.plan_synthesis_state_sha256,
            "state_sha256": plan.inputs.preplan_state_sha256,
            "state_frame": plan.inputs.preplan_state_frame,
            "state_dimensions": plan.inputs.preplan_state_dimensions,
            "state_units": plan.inputs.preplan_state_units,
            "state_timestamp_ns": plan.inputs.preplan_state_timestamp_ns,
            "freshness_limit_ns": plan.inputs.preplan_state_freshness_limit_ns,
            "query_source_implementation_sha256": "9" * 64,
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
        state_payload.update(self.state_updates)
        state_payload["receipt_sha256"] = canonical_sha256(state_payload)
        state = FormalPreplanStateReceiptV1.model_validate(state_payload)
        result_payload: dict[str, Any] = {
            "schema_version": "BoundExactPlanSynthesisResultV1",
            "request_sha256": canonical_sha256(request),
            "formal_observation_sha256": observation.wire_sha256,
            "runtime_mapping_sha256": canonical_runtime_mapping_sha256_v1(mapping),
            "synthesis_backend_implementation_sha256": self.implementation_sha256,
            "preplan_state_receipt": state.model_dump(mode="json"),
            "bound_plan": plan.model_dump(mode="json"),
            "plan_constructed_before_any_command": True,
            "physical_execution_claimed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        result_payload["result_sha256"] = canonical_sha256(result_payload)
        return BoundExactPlanSynthesisResultV1.model_validate(result_payload)


def _provider(tmp_path: Path, backend: _Backend) -> FormalBoundExactPlanProviderV1:
    return FormalBoundExactPlanProviderV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        backend=backend,
        deployment=None,
    )


def test_bound_provider_returns_one_fully_cross_bound_plan(tmp_path: Path) -> None:
    request = _request()
    observation = _formal()
    mapping = _mapping()
    backend = _Backend(tmp_path)
    provider = _provider(tmp_path, backend)

    plan = provider.build_bound_plan(
        request=request,
        observation=observation,
        mapping=mapping,
    )

    assert plan.inputs.preplan_state_timestamp_ns == observation.captured_at_ns + 1
    assert plan.inputs.plan_constructed_at_ns == observation.captured_at_ns + 2
    assert plan.inputs.runtime_mapping_sha256 == canonical_runtime_mapping_sha256_v1(mapping)
    assert provider.formal_execution_eligible is False
    assert backend.calls == 1


def test_bound_provider_consumes_request_before_retry(tmp_path: Path) -> None:
    request = _request()
    observation = _formal()
    mapping = _mapping()
    backend = _Backend(tmp_path)
    provider = _provider(tmp_path, backend)

    provider.build_bound_plan(request=request, observation=observation, mapping=mapping)
    with pytest.raises(ExactPlanUnavailable, match="already consumed"):
        provider.build_bound_plan(request=request, observation=observation, mapping=mapping)
    assert backend.calls == 1


def test_bound_provider_rejects_crossed_state_and_still_consumes(tmp_path: Path) -> None:
    request = _request()
    observation = _formal()
    mapping = _mapping()
    backend = _Backend(tmp_path, state_updates={"state_sha256": "f" * 64})
    provider = _provider(tmp_path, backend)

    with pytest.raises(ExactPlanUnavailable, match="crosses its query-only"):
        provider.build_bound_plan(request=request, observation=observation, mapping=mapping)
    with pytest.raises(ExactPlanUnavailable, match="already consumed"):
        provider.build_bound_plan(request=request, observation=observation, mapping=mapping)
    assert backend.calls == 1


def test_bound_provider_does_not_retry_lost_query_result(tmp_path: Path) -> None:
    request = _request()
    observation = _formal()
    mapping = _mapping()
    backend = _Backend(tmp_path, raises=True)
    provider = _provider(tmp_path, backend)

    with pytest.raises(RuntimeError, match="backend failed"):
        provider.build_bound_plan(request=request, observation=observation, mapping=mapping)
    with pytest.raises(ExactPlanUnavailable, match="already consumed"):
        provider.build_bound_plan(request=request, observation=observation, mapping=mapping)
    assert backend.calls == 1


def test_contract_provider_rejects_real_or_unmocked_dependency(tmp_path: Path) -> None:
    for backend in (
        _Backend(tmp_path, real_isaac=True),
        _Backend(tmp_path, mocked_physics=False),
    ):
        with pytest.raises(ExactPlanUnavailable, match="production dependencies"):
            _provider(tmp_path, backend)


def test_real_provider_requires_reviewed_deployment(tmp_path: Path) -> None:
    backend = _Backend(tmp_path, real_isaac=True, mocked_physics=False)
    with pytest.raises(ExactPlanUnavailable, match="deployment differs"):
        FormalBoundExactPlanProviderV1(
            project_root=tmp_path,
            mode="REAL_ISAAC",
            backend=backend,
            deployment=None,
        )
