from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanA1InputsV1,
    ExactPlanPhaseContractV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanSourceBindingV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitiveBundleV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.isaac_exact_plan_runtime_v1 import (
    ExactPlanRuntimeUnavailable,
    FROZEN_HELPER_SOURCE_SHA256,
    FrozenProbeExactPlanExecutorV1,
    FrozenProbePreflightUnavailableV1,
    PublicCapturePhaseReceiptV1,
    PublicReassociationPhaseReceiptV1,
    audit_frozen_b0_active_session_surface_v1,
    validate_eight_skill_phase_surface_v1,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ZERO = "0" * 64
ROLES = (
    "PRIMITIVE_ENTRYPOINT",
    "PREFLIGHT_IMPLEMENTATION",
    "EXECUTOR_IMPLEMENTATION",
    "TRANSITIVE_DEPENDENCY_MANIFEST",
    "ISAAC_RUNTIME",
    "IK_ALGORITHM",
    "JOINT_LIMIT_CONFIGURATION",
    "SWEPT_COLLISION_ALGORITHM",
    "ROBOT_ASSET",
    "CONTROLLER_CONFIGURATION",
    "SAFETY_CONFIGURATION",
    "SCENE_ASSET",
)


def _gates() -> ExactExecutionPhaseGatesV2:
    return ExactExecutionPhaseGatesV2(
        ik_detail="non-actuating exact IK",
        joint_limits_detail="frozen limits",
        swept_collision_detail="frozen swept collision",
        controller_detail="ready 60 Hz shape/rate",
        safety_detail="workspace/contact/attachment/staleness",
    )


def _pose(index: int, x: float) -> ExactExecutionPhaseV2:
    return ExactExecutionPhaseV2(
        phase_index=index,
        phase_name=f"LIFT_{index}",
        command="CARTESIAN_POSE",
        goal_position_world_m=(x, 0.2, 0.6),
        orientation_world_wxyz=(0.0, 1.0, 0.0, 0.0),
        steps=60 + index,
        collision_phase=f"LIFT_{index}",
        allowed_robot_contact_paths=("/World/Robot/panda_leftfinger",),
        allowed_external_contact_paths=("/World/M1B/cylinder_01/link",),
        gates=_gates(),
    )


def _phase_contract(phase: ExactExecutionPhaseV2) -> ExactPlanPhaseContractV1:
    return ExactPlanPhaseContractV1(
        phase=phase,
        phase_sha256=canonical_sha256(phase),
        command_rate_hz=60.0,
        command_dimensions=7,
        interpolation_rule="LINEAR_FIXED_STEPS",
        convergence_tolerance_m=0.002,
        timeout_ns=2_000_000_000,
        allowed_robot_links_sha256=canonical_sha256(phase.allowed_robot_contact_paths),
        allowed_environment_paths_sha256=canonical_sha256(()),
        allowed_external_contact_paths_sha256=canonical_sha256(
            phase.allowed_external_contact_paths
        ),
    )


def _bindings(tmp_path: Path) -> tuple[ExactPlanSourceBindingV1, ...]:
    result = []
    for index, role in enumerate(ROLES):
        raw = f"{role}\n".encode()
        path = tmp_path / f"source-{index}"
        path.write_bytes(raw)
        result.append(
            ExactPlanSourceBindingV1(
                role=role,
                path=str(path),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(result)


def _plan(
    tmp_path: Path,
    phases: tuple[ExactExecutionPhaseV2, ...] | None = None,
) -> M2CExactPlanPrimitivePlanV1:
    phases = phases or (_pose(0, 0.1), _pose(1, 0.12))
    contracts = tuple(_phase_contract(item) for item in phases)
    wire = ExactExecutionPlanV2(
        run_id="run-1",
        session_id="session-1",
        decision_index=1,
        observation_id="observation-1",
        capture_receipt_sha256="1" * 64,
        canonical_skill="LIFT",
        runtime_action="B0_CARTESIAN_LIFT",
        execution_parameters_sha256="2" * 64,
        target_track_id="track-blocker",
        phases=phases,
    )
    source_bindings = _bindings(tmp_path)
    schema_projection = tuple(
        {
            "phase_index": item.phase.phase_index,
            "phase_name": item.phase.phase_name,
            "command": item.phase.command,
            "phase_sha256": item.phase_sha256,
            "command_rate_hz": item.command_rate_hz,
            "command_dimensions": item.command_dimensions,
            "interpolation_rule": item.interpolation_rule,
            "timeout_ns": item.timeout_ns,
            "permitted_retry_count": item.permitted_retry_count,
            "attachment_or_removal_selector": item.attachment_or_removal_selector,
            "freshness_transition": item.freshness_transition,
        }
        for item in contracts
    )
    payload: dict[str, Any] = {
        "schema_version": "M2CExactPlanPrimitivePlanV1",
        "bundle_name": "M2CExactPlanPrimitiveBundleV1",
        "exact_execution_plan": wire,
        "exact_execution_plan_sha256": canonical_sha256(wire),
        "inputs": ExactPlanA1InputsV1(
            run_id=wire.run_id,
            session_id=wire.session_id,
            decision_index=wire.decision_index,
            observation_id=wire.observation_id,
            capture_receipt_sha256=wire.capture_receipt_sha256,
            rgb_sha256="3" * 64,
            depth_sha256="4" * 64,
            canonical_public_tracks_sha256="5" * 64,
            signed_model_inference_response_sha256="6" * 64,
            runtime_mapping_sha256="7" * 64,
            canonical_skill=wire.canonical_skill,
            runtime_action=wire.runtime_action,
            target_track_id=wire.target_track_id,
            resolved_execution_parameters_sha256=wire.execution_parameters_sha256,
            plan_synthesis_state_sha256="7" * 64,
            preplan_state_sha256="8" * 64,
            preplan_state_dimensions=8,
            preplan_state_units="rad_7_plus_per_finger_m",
            preplan_state_timestamp_ns=100,
            preplan_state_freshness_limit_ns=10,
            plan_constructed_at_ns=105,
            controller_frequency_hz=60.0,
            command_dimensions=7,
            convergence_tolerance_m=0.002,
            immutable_commit="9" * 40,
            container_image_digest="sha256:" + "a" * 64,
        ),
        "source_bindings": source_bindings,
        "phases": contracts,
        "phase_schema_sha256": canonical_sha256(schema_projection),
    }
    provisional = M2CExactPlanPrimitivePlanV1.model_construct(
        **payload,
        bound_plan_sha256=ZERO,
    )
    dumped = provisional.model_dump(mode="json")
    dumped["bound_plan_sha256"] = canonical_sha256(provisional.semantic_payload())
    return M2CExactPlanPrimitivePlanV1.model_validate(dumped)


def _preflight(plan: M2CExactPlanPrimitivePlanV1) -> ExactPlanPreflightReceiptV1:
    role_hashes = {item.role: item.sha256 for item in plan.source_bindings}
    results = tuple(
        ExactPlanPhasePreflightV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            preplan_state_sha256=plan.inputs.preplan_state_sha256,
            ik_algorithm_sha256=role_hashes["IK_ALGORITHM"],
            limits_configuration_sha256=role_hashes["JOINT_LIMIT_CONFIGURATION"],
            swept_collision_algorithm_sha256=role_hashes["SWEPT_COLLISION_ALGORITHM"],
            controller_configuration_sha256=role_hashes["CONTROLLER_CONFIGURATION"],
            safety_configuration_sha256=role_hashes["SAFETY_CONFIGURATION"],
        )
        for phase in plan.phases
    )
    payload = {
        "schema_version": "ExactPlanPreflightReceiptV1",
        "bound_plan_sha256": plan.bound_plan_sha256,
        "phase_results": [item.model_dump(mode="json") for item in results],
        "all_phases_passed_before_any_command": True,
    }
    return ExactPlanPreflightReceiptV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


class _Journal:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, dict(payload)))


class _Feedback:
    grasp_success = False


class _Probe:
    np = np
    RigidPrim = SimpleNamespace

    def __init__(self, *, fail_second: bool = False) -> None:
        self.fail_second = fail_second
        self.pose_calls: list[dict[str, Any]] = []
        self.selector_calls = 0
        self.gripper_calls = 0
        self.attachment_calls = 0
        self.removal_calls = 0

    def _step_pose(self, _robot: Any, goal: Any, **kwargs: Any) -> dict[str, Any]:
        self.pose_calls.append({"goal": goal.tolist(), **kwargs})
        failed = self.fail_second and len(self.pose_calls) == 2
        return {
            "goal_world_m": goal.tolist(),
            "orientation_world_wxyz": kwargs["orientation_wxyz"].tolist(),
            "steps": kwargs["steps"],
            "final_error_m": 0.1 if failed else 0.001,
            "minimum_error_m": 0.001,
            "collision_gate": {"status": "PASS"},
        }

    def _step_gripper(self, *_args: Any, **_kwargs: Any):
        self.gripper_calls += 1
        return [], [], [], []

    def _attach_preserving_pose(self, *_args: Any, **_kwargs: Any):
        self.attachment_calls += 1
        return {}

    def _remove_attachment(self) -> None:
        self.removal_calls += 1

    def broker_from_window(self, _samples: Any):
        return _Feedback(), {}

    def evaluate_robot_collision_events(self, *_args: Any, **_kwargs: Any):
        return {"status": "PASS"}

    def _execute_m2b_public_regrasp(self, *_args: Any, **_kwargs: Any):
        self.selector_calls += 1
        raise AssertionError("runtime selector must never be called")


def _capture(*_args: Any) -> PublicCapturePhaseReceiptV1:
    return PublicCapturePhaseReceiptV1(
        run_id="run-1",
        session_id="session-1",
        decision_index=1,
        capture_label="fresh",
        captured_at_ns=10,
        rgb_sha256="a" * 64,
        depth_sha256="b" * 64,
        canonical_public_tracks_sha256="c" * 64,
        capture_receipt_sha256="d" * 64,
        real_isaac=False,
        mocked_physics=True,
    )


def _reassociate(*_args: Any) -> PublicReassociationPhaseReceiptV1:
    return PublicReassociationPhaseReceiptV1(
        run_id="run-1",
        session_id="session-1",
        decision_index=1,
        input_capture_receipt_sha256="d" * 64,
        input_public_tracks_sha256="c" * 64,
        requested_public_track_id="track-blocker",
        resulting_public_track_id="track-blocker-v2",
        association_receipt_sha256="e" * 64,
        computed_at_ns=11,
        real_isaac=False,
        mocked_physics=True,
    )


def _executor(
    plan: M2CExactPlanPrimitivePlanV1,
    probe: _Probe,
    journal: _Journal,
    mutation_counter: _MutationCounter | None = None,
    attachment_registry: _AttachmentRegistry | None = None,
):
    return FrozenProbeExactPlanExecutorV1(
        project_root=PROJECT_ROOT,
        mode="CONTRACT_TEST",
        probe=probe,
        robot=object(),
        hand_prim=object(),
        contact_collector=object(),
        sensors={},
        contact_views={},
        journal=journal,
        state_digest=lambda: plan.inputs.preplan_state_sha256,
        capture_public=_capture,
        reassociate_public=_reassociate,
        mutation_counter_source=mutation_counter,
        attachment_state_registry=attachment_registry,
    )


class _MutationCounter:
    def __init__(self) -> None:
        self.scene_mutations = 0
        self.attachment_mutations = 0

    def record_scene_mutations(self, count: int = 1) -> None:
        self.scene_mutations += count

    def record_attachment_mutations(self, count: int = 1) -> None:
        self.attachment_mutations += count


class _AttachmentRegistry:
    def __init__(self) -> None:
        self.attachments = 0
        self.removals = 0

    def commit_attachment(self, **_kwargs: Any) -> SimpleNamespace:
        self.attachments += 1
        return SimpleNamespace(receipt_sha256="c" * 64)

    def commit_removal(self, **_kwargs: Any) -> SimpleNamespace:
        self.removals += 1
        return SimpleNamespace(receipt_sha256="d" * 64)


def test_attachment_mutations_are_recorded_before_frozen_helpers(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    probe = _Probe()
    probe.RigidPrim = lambda path: SimpleNamespace(path=path)
    counter = _MutationCounter()
    registry = _AttachmentRegistry()
    executor = _executor(plan, probe, _Journal(), counter, registry)
    executor._attachment_candidate = "cylinder_01"
    executor._attachment_candidate_phase_index = 0
    attach = SimpleNamespace(
        phase=SimpleNamespace(
            phase_index=1,
            command="ATTACH_CONTACT_ENTITY",
            allowed_external_contact_paths=("/World/M1B/cylinder_01/link",),
            contact_entity_selection="TERMINAL_BILATERAL_CONTACT",
        ),
        phase_sha256="a" * 64,
    )
    remove = SimpleNamespace(
        phase=SimpleNamespace(command="REMOVE_ATTACHMENT"),
        phase_sha256="b" * 64,
    )

    executor._execute_attach(plan, attach)
    executor._execute_remove(plan, remove)

    assert probe.attachment_calls == 1
    assert probe.removal_calls == 1
    assert counter.scene_mutations == 2
    assert counter.attachment_mutations == 2
    assert registry.attachments == 1
    assert registry.removals == 1


def test_frozen_probe_preflight_is_explicitly_unavailable_before_any_command(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    verifier = FrozenProbePreflightUnavailableV1()

    with pytest.raises(ExactPlanRuntimeUnavailable, match="NON_ACTUATING_ALL_PHASE"):
        verifier.verify_phase(plan, plan.phases[0])


def test_exact_executor_helper_hashes_are_shared_by_b0_and_frozen_v4() -> None:
    import ast

    paths = (
        PROJECT_ROOT / "scripts/isaac_m1b_actuation_probe.py",
        Path(
            "/Users/gl/tzb-m2c-evidence/m2c-s2/headroom-v4-terminal/"
            "source/isaac_m2c_blocker_probe.py"
        ),
    )
    if not paths[1].is_file():
        pytest.skip("local read-only V4 terminal bundle is absent")
    observed = []
    for path in paths:
        text = path.read_text()
        tree = ast.parse(text)
        observed.append(
            {
                node.name: hashlib.sha256(
                    (ast.get_source_segment(text, node) or "").encode()
                ).hexdigest()
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in FROZEN_HELPER_SOURCE_SHA256
            }
        )
    assert observed == [dict(FROZEN_HELPER_SOURCE_SHA256)] * 2


def test_executor_forwards_every_exact_pose_field_and_never_calls_selector(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    preflight = _preflight(plan)
    probe = _Probe()
    journal = _Journal()
    executor = _executor(plan, probe, journal)

    assert executor.verify_bound_plan_before_execution(plan, preflight) == (plan.bound_plan_sha256)
    results = [
        executor.execute_precomputed_phase(plan, phase, gate)
        for phase, gate in zip(plan.phases, preflight.phase_results)
    ]

    assert [item.status for item in results] == ["PASS", "PASS"]
    assert all(item.operation_executed is False for item in results)
    assert [item["goal"] for item in probe.pose_calls] == [
        list(phase.phase.goal_position_world_m or ()) for phase in plan.phases
    ]
    assert [item["steps"] for item in probe.pose_calls] == [60, 61]
    assert [item["collision_phase"] for item in probe.pose_calls] == [
        "LIFT_0",
        "LIFT_1",
    ]
    assert probe.selector_calls == 0
    assert [event for event, _ in journal.events].count("EXACT_PLAN_PHASE_EXECUTION_COMMITTED") == 2


def test_mid_plan_failure_poisoning_forbids_continuation_or_replan(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    preflight = _preflight(plan)
    probe = _Probe(fail_second=True)
    journal = _Journal()
    executor = _executor(plan, probe, journal)
    executor.verify_bound_plan_before_execution(plan, preflight)

    first = executor.execute_precomputed_phase(plan, plan.phases[0], preflight.phase_results[0])
    second = executor.execute_precomputed_phase(plan, plan.phases[1], preflight.phase_results[1])

    assert first.status == "PASS"
    assert second.status == "FAILED"
    assert probe.selector_calls == 0
    with pytest.raises(ExactPlanRuntimeUnavailable, match="poisoned"):
        executor.execute_precomputed_phase(plan, plan.phases[1], preflight.phase_results[1])
    assert len(probe.pose_calls) == 2


def test_phase_order_or_state_digest_mismatch_fails_before_helper_call(
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    preflight = _preflight(plan)
    probe = _Probe()
    journal = _Journal()
    executor = _executor(plan, probe, journal)
    executor.verify_bound_plan_before_execution(plan, preflight)

    with pytest.raises(ExactPlanRuntimeUnavailable, match="next preflighted"):
        executor.execute_precomputed_phase(plan, plan.phases[1], preflight.phase_results[1])
    assert probe.pose_calls == []

    wrong_state = FrozenProbeExactPlanExecutorV1(
        project_root=PROJECT_ROOT,
        mode="CONTRACT_TEST",
        probe=_Probe(),
        robot=object(),
        hand_prim=object(),
        contact_collector=object(),
        sensors={},
        contact_views={},
        journal=_Journal(),
        state_digest=lambda: "f" * 64,
        capture_public=_capture,
        reassociate_public=_reassociate,
    )
    with pytest.raises(ExactPlanRuntimeUnavailable, match="state changed"):
        wrong_state.verify_bound_plan_before_execution(plan, preflight)


def test_real_isaac_construction_requires_counter_and_reviewed_deployment_binding() -> None:
    probe = _Probe()
    with pytest.raises(ExactPlanRuntimeUnavailable, match="mutation counter"):
        FrozenProbeExactPlanExecutorV1(
            project_root=PROJECT_ROOT,
            mode="REAL_ISAAC",
            probe=probe,
            robot=object(),
            hand_prim=object(),
            contact_collector=object(),
            sensors={},
            contact_views={},
            journal=_Journal(),
            state_digest=lambda: ZERO,
            capture_public=_capture,
            reassociate_public=_reassociate,
            deployment_binding=None,
        )
    with pytest.raises(ExactPlanRuntimeUnavailable, match="deployment binding"):
        FrozenProbeExactPlanExecutorV1(
            project_root=PROJECT_ROOT,
            mode="REAL_ISAAC",
            probe=probe,
            robot=object(),
            hand_prim=object(),
            contact_collector=object(),
            sensors={},
            contact_views={},
            journal=_Journal(),
            state_digest=lambda: ZERO,
            capture_public=_capture,
            reassociate_public=_reassociate,
            mutation_counter_source=_MutationCounter(),
            attachment_state_registry=_AttachmentRegistry(),
            deployment_binding=None,
        )
    assert probe.pose_calls == []


def test_unchanged_b0_active_session_audit_is_zero_execution_and_digest_bound() -> None:
    receipt = audit_frozen_b0_active_session_surface_v1(PROJECT_ROOT)

    assert receipt.required_entrypoint_present is False
    assert receipt.active_session_unchanged_b0_available is False
    assert receipt.physical_execution_performed is False
    assert receipt.low_level_helper_composition_rejected_as_unchanged_b0 is True
    payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    assert receipt.receipt_sha256 == canonical_sha256(payload)


def test_existing_bundle_with_unavailable_preflight_executes_no_phase(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    probe = _Probe()
    bundle = M2CExactPlanPrimitiveBundleV1(
        project_root=PROJECT_ROOT,
        binding=None,
        preflight_verifier=FrozenProbePreflightUnavailableV1(),
        executor=_executor(plan, probe, _Journal()),
    )

    with pytest.raises(ExactPlanUnavailable, match="binding addendum"):
        bundle.preflight(plan)
    assert probe.pose_calls == []


def test_eight_skill_surface_rejects_missing_skill_before_execution(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    with pytest.raises(ExactPlanRuntimeUnavailable, match="incomplete or extra"):
        validate_eight_skill_phase_surface_v1({"LIFT": plan})
