from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanA1InputsV1,
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPhaseContractV1,
    ExactPlanPhaseExecutionV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanPrimitiveDeploymentBindingV1,
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


DIGEST = "a" * 64
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64
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


def _gate() -> ExactExecutionPhaseGatesV2:
    return ExactExecutionPhaseGatesV2(
        ik_detail="exact IK",
        joint_limits_detail="exact limits",
        swept_collision_detail="exact swept collision",
        controller_detail="exact controller",
        safety_detail="exact safety",
    )


def _phase(index: int, name: str, x: float) -> ExactExecutionPhaseV2:
    return ExactExecutionPhaseV2(
        phase_index=index,
        phase_name=name,
        command="CARTESIAN_POSE",
        goal_position_world_m=(x, 0.2, 0.6),
        orientation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        steps=60,
        collision_phase=name,
        gates=_gate(),
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
        allowed_robot_links_sha256=DIGEST,
        allowed_environment_paths_sha256=DIGEST,
        allowed_external_contact_paths_sha256=canonical_sha256(()),
    )


def _make_binding_files(root: Path) -> tuple[ExactPlanSourceBindingV1, ...]:
    bindings = []
    for index, role in enumerate(ROLES):
        path = root / f"source-{index}.bin"
        raw = f"{role}\n".encode()
        path.write_bytes(raw)
        bindings.append(
            ExactPlanSourceBindingV1(
                role=role,
                path=path.name,
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(bindings)


def _make_plan(
    bindings: tuple[ExactPlanSourceBindingV1, ...],
) -> M2CExactPlanPrimitivePlanV1:
    phases = (_phase(0, "LIFT_START", 0.1), _phase(1, "LIFT_END", 0.1))
    wire_plan = ExactExecutionPlanV2(
        run_id="run-1",
        session_id="session-1",
        decision_index=1,
        observation_id="observation-1",
        capture_receipt_sha256="d" * 64,
        canonical_skill="LIFT",
        runtime_action="M2C_LIFT_V1",
        execution_parameters_sha256="e" * 64,
        target_track_id="track-blocker",
        phases=phases,
    )
    contracts = tuple(_phase_contract(phase) for phase in phases)
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
    payload = {
        "schema_version": "M2CExactPlanPrimitivePlanV1",
        "bundle_name": "M2CExactPlanPrimitiveBundleV1",
        "exact_execution_plan": wire_plan,
        "exact_execution_plan_sha256": canonical_sha256(wire_plan),
        "inputs": ExactPlanA1InputsV1(
            run_id=wire_plan.run_id,
            session_id=wire_plan.session_id,
            decision_index=wire_plan.decision_index,
            observation_id=wire_plan.observation_id,
            capture_receipt_sha256=wire_plan.capture_receipt_sha256,
            rgb_sha256="1" * 64,
            depth_sha256="2" * 64,
            canonical_public_tracks_sha256="3" * 64,
            signed_model_inference_response_sha256="4" * 64,
            runtime_mapping_sha256="5" * 64,
            canonical_skill=wire_plan.canonical_skill,
            runtime_action=wire_plan.runtime_action,
            target_track_id=wire_plan.target_track_id,
            resolved_execution_parameters_sha256=(wire_plan.execution_parameters_sha256),
            plan_synthesis_state_sha256="5" * 64,
            preplan_state_sha256="6" * 64,
            preplan_state_dimensions=8,
            preplan_state_units="rad_7_plus_per_finger_m",
            preplan_state_timestamp_ns=100,
            preplan_state_freshness_limit_ns=10_000_000,
            plan_constructed_at_ns=105,
            controller_frequency_hz=60.0,
            command_dimensions=7,
            convergence_tolerance_m=0.002,
            immutable_commit=COMMIT,
            container_image_digest=IMAGE,
        ),
        "source_bindings": bindings,
        "phases": contracts,
        "phase_schema_sha256": canonical_sha256(schema_projection),
    }
    # ``model_construct`` is used only to materialize schema defaults before
    # the canonical digest; the returned object is fully validated below.
    provisional = M2CExactPlanPrimitivePlanV1.model_construct(
        **payload,
        bound_plan_sha256="0" * 64,
    )
    dumped = provisional.model_dump(mode="json")
    dumped["bound_plan_sha256"] = canonical_sha256(provisional.semantic_payload())
    return M2CExactPlanPrimitivePlanV1.model_validate(dumped)


class _Preflight:
    def __init__(self, implementation_sha256: str) -> None:
        self.implementation_sha256 = implementation_sha256
        self.calls: list[int] = []
        self.attachment_binding_calls: list[str] = []

    def verify_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> ExactPlanPhasePreflightV1:
        self.calls.append(phase.phase.phase_index)
        hashes = {item.role: item.sha256 for item in plan.source_bindings}
        return ExactPlanPhasePreflightV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            preplan_state_sha256=plan.inputs.preplan_state_sha256,
            ik_algorithm_sha256=hashes["IK_ALGORITHM"],
            limits_configuration_sha256=hashes["JOINT_LIMIT_CONFIGURATION"],
            swept_collision_algorithm_sha256=hashes["SWEPT_COLLISION_ALGORITHM"],
            controller_configuration_sha256=hashes["CONTROLLER_CONFIGURATION"],
            safety_configuration_sha256=hashes["SAFETY_CONFIGURATION"],
        )

    def planned_attachment_bindings(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> tuple[object, ...]:
        self.attachment_binding_calls.append(plan.bound_plan_sha256)
        return ()


class _Executor:
    def __init__(
        self,
        implementation_sha256: str,
        *,
        fail_at: int | None = None,
        real_isaac: bool = False,
        stop_after_bind: bool = False,
    ) -> None:
        self.implementation_sha256 = implementation_sha256
        self.fail_at = fail_at
        self.real_isaac = real_isaac
        self.stop_after_bind = stop_after_bind
        self.calls: list[int] = []
        self.attachment_binding_calls: list[tuple[str, tuple[object, ...]]] = []

    def bind_preflight_attachment_bindings(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        bindings: tuple[object, ...],
    ) -> None:
        self.attachment_binding_calls.append((plan.bound_plan_sha256, bindings))

    def verify_bound_plan_before_execution(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        _preflight: ExactPlanPreflightReceiptV1,
    ) -> str:
        if self.stop_after_bind:
            raise ExactPlanUnavailable("unit-only stop after attachment handoff")
        return plan.bound_plan_sha256

    def execute_precomputed_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        _preflight: ExactPlanPhasePreflightV1,
    ) -> ExactPlanPhaseExecutionV1:
        index = phase.phase.phase_index
        self.calls.append(index)
        failed = index == self.fail_at
        return ExactPlanPhaseExecutionV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=index,
            phase_sha256=phase.phase_sha256,
            started_at_ns=100 + index * 10,
            completed_at_ns=105 + index * 10,
            status="FAILED" if failed else "PASS",
            operation_executed=False,
            controller_outcome="contract-only failure" if failed else "contract-only pass",
            real_isaac=False,
            contract_test_only=True,
        )


def _binding(
    root: Path,
    bindings: tuple[ExactPlanSourceBindingV1, ...],
    plan: M2CExactPlanPrimitivePlanV1,
    *,
    execution_mode: str = "CONTRACT_TEST",
) -> ExactPlanPrimitiveDeploymentBindingV1:
    bound_files = {
        "docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md": (
            b"accepted ADR contract fixture\n"
        ),
        "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md": (
            b"accepted superseding ADR contract fixture\n"
        ),
        "docs/decisions/ADR-0022-BINDING-ADDENDUM.md": b"binding contract fixture\n",
        "configs/m2c_s4_unlock_bindings.json": b"{}\n",
    }
    for relative, raw in bound_files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    schemas = tuple(
        (skill, plan.phase_schema_sha256)
        for skill in (
            "GRASP",
            "LIFT",
            "MOVE",
            "PLACE",
            "RELEASE",
            "REOBSERVE",
            "REASSOCIATE_TARGET",
            "REGRASP",
        )
    )
    return ExactPlanPrimitiveDeploymentBindingV1(
        adr_sha256=hashlib.sha256(
            bound_files["docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"]
        ).hexdigest(),
        superseding_adr_sha256=hashlib.sha256(
            bound_files["docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"]
        ).hexdigest(),
        binding_addendum_sha256=hashlib.sha256(
            bound_files["docs/decisions/ADR-0022-BINDING-ADDENDUM.md"]
        ).hexdigest(),
        unlock_config_sha256=hashlib.sha256(
            bound_files["configs/m2c_s4_unlock_bindings.json"]
        ).hexdigest(),
        immutable_commit=COMMIT,
        container_image_digest=IMAGE,
        source_bindings=bindings,
        phase_schema_by_skill=schemas,
        execution_mode=execution_mode,
    )


def _bundle(
    root: Path,
    plan: M2CExactPlanPrimitivePlanV1,
    bindings: tuple[ExactPlanSourceBindingV1, ...],
    *,
    fail_at: int | None = None,
) -> tuple[M2CExactPlanPrimitiveBundleV1, _Preflight, _Executor]:
    hashes = {item.role: item.sha256 for item in bindings}
    preflight = _Preflight(hashes["PREFLIGHT_IMPLEMENTATION"])
    executor = _Executor(hashes["EXECUTOR_IMPLEMENTATION"], fail_at=fail_at)
    bundle = M2CExactPlanPrimitiveBundleV1(
        project_root=root,
        binding=_binding(root, bindings, plan),
        preflight_verifier=preflight,
        executor=executor,
    )
    return bundle, preflight, executor


def test_bundle_preflights_every_phase_before_execution_and_keeps_exact_order(
    tmp_path: Path,
) -> None:
    bindings = _make_binding_files(tmp_path)
    plan = _make_plan(bindings)
    bundle, preflight, executor = _bundle(tmp_path, plan, bindings)

    gate_receipt = bundle.preflight(plan)
    assert preflight.calls == [0, 1]
    assert executor.calls == []

    receipt = bundle.execute(plan, gate_receipt)
    assert isinstance(receipt, ExactPlanBundleExecutionReceiptV1)
    assert receipt.status == "PASS"
    assert receipt.formal_evidence is False
    assert executor.calls == [0, 1]
    assert [item.phase_sha256 for item in receipt.phase_receipts] == [
        item.phase_sha256 for item in plan.phases
    ]


def test_mid_plan_failure_stops_without_retry_or_replan(tmp_path: Path) -> None:
    bindings = _make_binding_files(tmp_path)
    plan = _make_plan(bindings)
    bundle, _, executor = _bundle(tmp_path, plan, bindings, fail_at=0)

    receipt = bundle.execute(plan, bundle.preflight(plan))

    assert receipt.status == "PARTIAL_FAILURE"
    assert receipt.terminated_without_replan is True
    assert executor.calls == [0]
    assert receipt.phase_receipts[0].replanned is False
    assert receipt.phase_receipts[0].retry_selected_at_runtime is False


def test_missing_binding_or_source_tamper_prevents_any_execution(tmp_path: Path) -> None:
    bindings = _make_binding_files(tmp_path)
    plan = _make_plan(bindings)
    executor = _Executor(
        dict((item.role, item.sha256) for item in bindings)["EXECUTOR_IMPLEMENTATION"]
    )
    unbound = M2CExactPlanPrimitiveBundleV1(
        project_root=tmp_path,
        binding=None,
        preflight_verifier=None,
        executor=executor,
    )
    with pytest.raises(ExactPlanUnavailable, match="binding addendum"):
        unbound.preflight(plan)
    assert executor.calls == []

    (tmp_path / "source-0.bin").write_bytes(b"tampered")
    bound, _, executor = _bundle(tmp_path, plan, bindings)
    with pytest.raises(ExactPlanUnavailable, match="source digest differs"):
        bound.preflight(plan)
    assert executor.calls == []


def test_plan_is_deeply_immutable_and_digest_tamper_is_rejected(tmp_path: Path) -> None:
    bindings = _make_binding_files(tmp_path)
    plan = _make_plan(bindings)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        plan.inputs.run_id = "changed"  # type: ignore[misc]
    payload = plan.model_dump(mode="json")
    payload["phases"][0]["timeout_ns"] += 1
    with pytest.raises(ValidationError, match="canonical digest differs"):
        M2CExactPlanPrimitivePlanV1.model_validate(payload)


def test_real_bundle_hands_preflight_attachment_bindings_to_executor_first(
    tmp_path: Path,
) -> None:
    bindings = _make_binding_files(tmp_path)
    plan = _make_plan(bindings)
    hashes = {item.role: item.sha256 for item in bindings}
    preflight = _Preflight(hashes["PREFLIGHT_IMPLEMENTATION"])
    executor = _Executor(
        hashes["EXECUTOR_IMPLEMENTATION"],
        real_isaac=True,
        stop_after_bind=True,
    )
    bundle = M2CExactPlanPrimitiveBundleV1(
        project_root=tmp_path,
        binding=_binding(
            tmp_path,
            bindings,
            plan,
            execution_mode="REAL_ISAAC",
        ),
        preflight_verifier=preflight,
        executor=executor,
    )
    receipt = bundle.preflight(plan)

    with pytest.raises(ExactPlanUnavailable, match="unit-only stop"):
        bundle.execute(plan, receipt)

    assert preflight.attachment_binding_calls == [plan.bound_plan_sha256]
    assert executor.attachment_binding_calls == [(plan.bound_plan_sha256, ())]
    assert executor.calls == []
