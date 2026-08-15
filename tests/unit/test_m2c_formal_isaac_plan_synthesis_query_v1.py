from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from test_m2c_formal_exact_plan_synthesis_v1 import (
    _configuration,
    _request_and_mapping,
)
from test_m2c_isaac_active_session_query_v1 import _provider
from xh_agent.policy.qrm_lite.formal_exact_plan_synthesis_v1 import (
    ConfiguredFormalExactPlanSynthesisBackendV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_plan_synthesis_query_v1 import (
    FormalIsaacPlanSynthesisQueryUnavailable,
    FormalIsaacPlanSynthesisStateQueryV1,
    FormalPlanSynthesisSceneSafetyBindingV1,
    IsaacActiveSessionQueryProviderFactoryV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = "/World/M1B/cylinder_01/link"
ENVIRONMENT_PATHS = (
    "/World/M1B/cylinder_01/link",
    "/World/M1B/partition_bin/link",
    "/World/M1B/work_table/link",
)


class _SceneSafetySource:
    implementation_sha256 = "b" * 64
    real_isaac = False
    mocked_physics = True

    def __init__(
        self,
        counters: Any,
        *,
        updates: dict[str, Any] | None = None,
        mutate_after_binding: bool = False,
    ) -> None:
        self.mutation_counter_source = counters
        self.updates = updates or {}
        self.mutate_after_binding = mutate_after_binding
        self.calls = 0

    def query_scene_safety_binding(self, *, request, observation, after_ns):  # type: ignore[no-untyped-def]
        self.calls += 1
        counters = self.mutation_counter_source.snapshot_mutation_counters()
        skill = request.runtime_request.skill
        target = request.runtime_request.model_target_track_id
        attached = target if skill in {"LIFT", "MOVE", "PLACE", "RELEASE"} else None
        payload: dict[str, Any] = {
            "schema_version": "FormalPlanSynthesisSceneSafetyBindingV1",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "executed_intent_history_sha256": request.executed_intent_history_sha256,
            "selected_skill": skill,
            "target_public_track_id": target,
            "target_external_contact_path": TARGET_PATH if target is not None else None,
            "target_binding_receipt_sha256": "c" * 64 if target is not None else None,
            "attached_public_track_id": attached,
            "attached_external_contact_path": TARGET_PATH if attached is not None else None,
            "active_attachment_receipt_sha256": "d" * 64 if attached is not None else None,
            "environment_collision_paths": ENVIRONMENT_PATHS,
            "scene_geometry_receipt_sha256": "e" * 64,
            "source_implementation_sha256": self.implementation_sha256,
            "observed_at_ns": after_ns + 1,
            "mutation_counters_before": counters,
            "mutation_counters_after": counters,
            "real_isaac": False,
            "mocked_physics": True,
            "simulator_paths_used_for_skill_or_pointer_selection": False,
            "simulator_paths_exposed_to_model": False,
            "simulator_paths_used_only_for_a3_gates": True,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "controller_commands": 0,
            "attachment_mutations": 0,
            "teacher_used": False,
            "evaluator_identity_used": False,
            "task_spec_fallback_used": False,
            "privileged_truth_policy_input": False,
        }
        payload.update(self.updates)
        binding = FormalPlanSynthesisSceneSafetyBindingV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
        if self.mutate_after_binding:
            self.mutation_counter_source.writes += 1
        return binding


def _query(
    *,
    source_updates: dict[str, Any] | None = None,
    mutate_after_binding: bool = False,
) -> tuple[FormalIsaacPlanSynthesisStateQueryV1, _SceneSafetySource]:
    active, runtime = _provider()
    factory = IsaacActiveSessionQueryProviderFactoryV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime=active.runtime,
        configuration=active.configuration,
    )
    source = _SceneSafetySource(
        runtime.mutation_counter_source,
        updates=source_updates,
        mutate_after_binding=mutate_after_binding,
    )
    query = FormalIsaacPlanSynthesisStateQueryV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        active_session_factory=factory,
        scene_safety_source=source,
        freshness_limit_ns=1_000_000,
    )
    return query, source


@pytest.mark.parametrize(
    ("skill", "attached"),
    (("GRASP", False), ("LIFT", True), ("REOBSERVE", False)),
)
def test_query_composes_one_mutation_free_state(
    skill: str,
    attached: bool,
) -> None:
    request, _ = _request_and_mapping(skill)
    query, source = _query()

    snapshot = query.query_plan_synthesis_state(
        request=request,
        observation=request.observation,
    )

    assert source.calls == 1
    assert snapshot.state.active_session_runtime_receipt_sha256
    assert snapshot.state.scene_safety_binding_receipt_sha256
    assert snapshot.state.scene_geometry_receipt_sha256 == "e" * 64
    assert snapshot.state.dynamic_contact_allowlist_paths == (
        (TARGET_PATH,) if skill != "REOBSERVE" else ()
    )
    assert (snapshot.state.attached_public_track_id is not None) is attached
    assert (snapshot.state.active_attachment_receipt_sha256 is not None) is attached
    assert snapshot.receipt.plan_synthesis_state_sha256 == snapshot.state.state_sha256
    assert snapshot.receipt.state_sha256 == snapshot.state.active_session_state_sha256
    assert snapshot.receipt.state_sha256 != snapshot.state.state_sha256
    assert snapshot.receipt.state_units == "rad_7_plus_per_finger_m"
    assert snapshot.receipt.query_source_implementation_sha256 == query.implementation_sha256


def test_query_source_drives_the_frozen_grasp_plan(tmp_path: Path) -> None:
    request, mapping = _request_and_mapping("GRASP")
    query, _ = _query()
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 4,
    )

    result = backend.synthesize_bound_plan(
        request=request,
        observation=request.observation,
        mapping=mapping,
    )

    attach = result.bound_plan.exact_execution_plan.phases[6]
    assert attach.command == "ATTACH_CONTACT_ENTITY"
    assert attach.allowed_external_contact_paths == (TARGET_PATH,)
    assert result.preplan_state_receipt.query_source_implementation_sha256 == (
        query.implementation_sha256
    )
    assert result.bound_plan.inputs.plan_synthesis_state_sha256 == (
        result.preplan_state_receipt.plan_synthesis_state_sha256
    )
    assert result.bound_plan.inputs.preplan_state_sha256 == (
        result.preplan_state_receipt.state_sha256
    )
    active_session = query.claim_active_session_query_provider(result.bound_plan)
    active_state = active_session.read_active_state(result.bound_plan)
    assert active_state.state_sha256 == result.bound_plan.inputs.preplan_state_sha256
    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="already claimed"):
        query.claim_active_session_query_provider(result.bound_plan)


def test_query_consumes_request_before_any_retry() -> None:
    request, _ = _request_and_mapping("GRASP")
    query, _ = _query()
    query.query_plan_synthesis_state(request=request, observation=request.observation)

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="already consumed"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)


def test_unclaimed_state_blocks_another_decision() -> None:
    request, _ = _request_and_mapping("GRASP")
    query, _ = _query()
    query.query_plan_synthesis_state(request=request, observation=request.observation)
    other = request.model_copy(update={"run_id": "other-formal-run"})

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="not bound"):
        query.query_plan_synthesis_state(request=other, observation=other.observation)


def test_crossed_plan_consumes_captured_provider(tmp_path: Path) -> None:
    request, mapping = _request_and_mapping("GRASP")
    query, _ = _query()
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 4,
    )
    result = backend.synthesize_bound_plan(
        request=request,
        observation=request.observation,
        mapping=mapping,
    )
    crossed_inputs = result.bound_plan.inputs.model_copy(
        update={"plan_synthesis_state_sha256": "f" * 64}
    )
    crossed = result.bound_plan.model_copy(update={"inputs": crossed_inputs})

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="crosses"):
        query.claim_active_session_query_provider(crossed)
    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="already claimed"):
        query.claim_active_session_query_provider(result.bound_plan)


def test_query_rejects_crossed_public_target() -> None:
    request, _ = _request_and_mapping("GRASP")
    query, _ = _query(source_updates={"target_public_track_id": "track-deadbeef"})

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="crosses"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)


def test_query_rejects_grasp_with_existing_attachment() -> None:
    request, _ = _request_and_mapping("GRASP")
    query, _ = _query(
        source_updates={
            "attached_public_track_id": request.runtime_request.model_target_track_id,
            "attached_external_contact_path": TARGET_PATH,
            "active_attachment_receipt_sha256": "d" * 64,
        }
    )

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="already attached"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)


def test_query_rejects_transport_with_crossed_attachment() -> None:
    request, _ = _request_and_mapping("MOVE")
    query, _ = _query(source_updates={"attached_public_track_id": "track-deadbeef"})

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="selected attachment"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)


def test_query_rejects_any_scene_mutation() -> None:
    request, _ = _request_and_mapping("GRASP")
    query, _ = _query(mutate_after_binding=True)

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="mutated"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)


def test_constructor_rejects_sources_with_different_counters() -> None:
    active, _ = _provider()
    _, other_runtime = _provider()
    factory = IsaacActiveSessionQueryProviderFactoryV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime=active.runtime,
        configuration=active.configuration,
    )
    source = _SceneSafetySource(other_runtime.mutation_counter_source)

    with pytest.raises(FormalIsaacPlanSynthesisQueryUnavailable, match="one mutation counter"):
        FormalIsaacPlanSynthesisStateQueryV1(
            project_root=ROOT,
            mode="CONTRACT_TEST",
            active_session_factory=factory,
            scene_safety_source=source,
            freshness_limit_ns=1_000_000,
        )


def test_factory_returns_a_fresh_single_use_provider_per_decision() -> None:
    active, _ = _provider()
    factory = IsaacActiveSessionQueryProviderFactoryV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime=active.runtime,
        configuration=active.configuration,
    )
    first = factory.create_active_session_query_provider()
    second = factory.create_active_session_query_provider()

    assert first is not second
    assert first.mutation_counter_source is second.mutation_counter_source
    first.capture_preplan_state(context_sha256="1" * 64, after_ns=100)
    second.capture_preplan_state(context_sha256="2" * 64, after_ns=100)


def test_scene_binding_rejects_partial_or_noncanonical_safety_paths() -> None:
    request, _ = _request_and_mapping("GRASP")
    query, _ = _query(
        source_updates={
            "target_binding_receipt_sha256": None,
        }
    )
    with pytest.raises(ValueError, match="partial"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)

    query, _ = _query(
        source_updates={
            "environment_collision_paths": tuple(reversed(ENVIRONMENT_PATHS)),
        }
    )
    with pytest.raises(ValueError, match="not canonical"):
        query.query_plan_synthesis_state(request=request, observation=request.observation)
