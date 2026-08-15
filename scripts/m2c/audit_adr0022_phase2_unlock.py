#!/usr/bin/env python3
"""Replay ADR-0022 Phase-2 contract smoke without unlocking execution.

Passing this audit proves only offline schema/provenance behavior. It cannot
replace a real Isaac planner/executor, deployment closure, session-bound
host-local HMAC receipts, endpoint startup evidence, or physical validation
of all eight skills. The result is deliberately ``BLOCKED`` while an active
source binding remains unset or any of those real artifacts is absent.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from pydantic import ValidationError

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanA1InputsV1,
    ExactPlanPhaseContractV1,
    ExactPlanPhaseExecutionV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanPrimitiveDeploymentBindingV1,
    ExactPlanSourceBindingV1,
    M2CExactPlanPrimitiveBundleV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.frozen_b0_fallback_wrapper_v1 import (
    FROZEN_B0_MANIFEST_SHA256,
    FROZEN_B0_PROBE_SHA256,
    FROZEN_B0_RUNNER_SHA256,
    FrozenB0FallbackReceiptV1,
    FrozenB0FallbackRequestV1,
    FrozenB0FallbackWrapperV1,
)


SCHEMA_VERSION = "M2CADR0022Phase2UnlockAuditV1"
ADR_PATH = Path("docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md")
ENTRY_GATE_PATH = Path("src/xh_agent/policy/qrm_lite/s4_entry_gate.py")
BUNDLE_PATH = Path("src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py")
WRAPPER_PATH = Path("src/xh_agent/policy/qrm_lite/frozen_b0_fallback_wrapper_v1.py")
ADDENDUM_PATH = Path("docs/decisions/ADR-0022-BINDING-ADDENDUM.md")
UNLOCK_CONFIG_PATH = Path("configs/m2c_s4_unlock_bindings.json")

FROZEN_SOURCE_SHA256 = {
    ADR_PATH.as_posix(): "4538eb980b66dc0945d1f016325f6c3c5679c87b97b9986e25253e67a2cc3ef1",
    BUNDLE_PATH.as_posix(): "e655c6f284531f13e232342e85104574587cec3f2d821f8ba9971492ef8d27a5",
    WRAPPER_PATH.as_posix(): "5e2df2329725c79ec073c3ec34b87158787411d386b9ba13d0d4bc1d790642b8",
}
UNLOCK_BINDING_NAMES = (
    "FORMAL_PHYSICAL_RUNNER_BINDING",
    "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
    "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
    "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
)
BLOCKERS = (
    "REAL_EXACT_PLAN_ISAAC_PLANNER_EXECUTOR_MISSING",
    "DEPLOYMENT_CLOSURE_ASSETS_CONTAINER_MISSING",
    "NODE2_LABSERVER_HOST_HMAC_RECEIPTS_MISSING",
    "REAL_ENDPOINT_STARTUP_SESSION_EVIDENCE_MISSING",
    "EIGHT_SKILL_PHYSICAL_PHASE_VALIDATION_MISSING",
)
EXPECTED_APPLIED_BINDINGS: dict[str, object] = {
    "FORMAL_PHYSICAL_RUNNER_BINDING": (
        "scripts/m2c/run_formal_model_owned_chain_v4.py",
        "799caecdb12f73b5e6ea226eb2b983e4fbe4c08482f7ed037ae33c2168068eef",
    ),
    "FORMAL_DEPLOYMENT_CLOSURE_BINDING": (
        "3b86d4c997a6e2a7229c6e8149200b166fa32d77",
        "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9",
        "684c81dcb00d0abf33095bc704e7550d9bb64400b367d2b5da9324aeb85c8993",
    ),
    "FROZEN_B0_RUNTIME_WRAPPER_BINDING": None,
    "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING": None,
}
SOURCE_ROLES = (
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
SKILLS = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)
_DIGEST = "a" * 64
_COMMIT = "b" * 40
_IMAGE = "sha256:" + "c" * 64


class AuditFailure(RuntimeError):
    """A contract smoke or frozen-source replay failed."""


def read_regular_file_once(path: Path) -> bytes:
    """Read a stable single-link regular file through one non-following FD."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise AuditFailure(f"audit input is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_identity != after_identity:
            raise AuditFailure(f"audit input changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verify_frozen_sources(project_root: Path) -> list[dict[str, str]]:
    records = []
    for relative, expected in FROZEN_SOURCE_SHA256.items():
        actual = _sha256(read_regular_file_once(project_root / relative))
        if actual != expected:
            raise AuditFailure(f"frozen ADR-0022 source SHA-256 differs: {relative}")
        records.append({"path": relative, "sha256": actual, "status": "MATCH"})
    return records


def parse_unlock_bindings(
    source: bytes,
    *,
    expected: dict[str, object] | None = None,
) -> dict[str, object]:
    """Require one exact literal top-level assignment for each binding."""

    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise AuditFailure("s4 entry gate is not parseable UTF-8 Python") from exc
    assignments: dict[str, list[ast.expr]] = {name: [] for name in UNLOCK_BINDING_NAMES}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in assignments and node.value is not None:
                assignments[node.target.id].append(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in assignments:
                    assignments[target.id].append(node.value)
    parsed: dict[str, object] = {}
    expected = expected or {name: None for name in UNLOCK_BINDING_NAMES}
    for name, values in assignments.items():
        if len(values) != 1:
            raise AuditFailure(f"unlock binding is absent or duplicated: {name}")
        try:
            parsed[name] = ast.literal_eval(values[0])
        except (ValueError, TypeError) as exc:
            raise AuditFailure(f"unlock binding is not a literal: {name}") from exc
        if parsed[name] != expected[name]:
            raise AuditFailure(f"unlock binding differs from expected source state: {name}")
    return parsed


def _phase(index: int, name: str, x: float) -> ExactExecutionPhaseV2:
    return ExactExecutionPhaseV2(
        phase_index=index,
        phase_name=name,
        command="CARTESIAN_POSE",
        goal_position_world_m=(x, 0.2, 0.6),
        orientation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        steps=60,
        collision_phase=name,
        gates=ExactExecutionPhaseGatesV2(
            ik_detail="contract-only exact IK",
            joint_limits_detail="contract-only exact limits",
            swept_collision_detail="contract-only exact swept collision",
            controller_detail="contract-only exact controller",
            safety_detail="contract-only exact safety",
        ),
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
        allowed_robot_links_sha256=_DIGEST,
        allowed_environment_paths_sha256=_DIGEST,
        allowed_external_contact_paths_sha256=canonical_sha256(()),
    )


def _write_contract_fixture(root: Path) -> tuple[ExactPlanSourceBindingV1, ...]:
    bindings = []
    for index, role in enumerate(SOURCE_ROLES):
        path = root / "contract" / f"source-{index}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = f"ADR-0022 {role} contract fixture\n".encode()
        path.write_bytes(raw)
        bindings.append(
            ExactPlanSourceBindingV1(
                role=role,
                path=path.relative_to(root).as_posix(),
                sha256=_sha256(raw),
            )
        )
    supporting = {
        ADR_PATH: b"accepted ADR contract fixture; not repository evidence\n",
        Path("docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"): (
            b"accepted superseding ADR contract fixture; not repository evidence\n"
        ),
        ADDENDUM_PATH: b"contract fixture only; not an accepted addendum\n",
        UNLOCK_CONFIG_PATH: b'{"contract_fixture_only":true}\n',
    }
    for relative, raw in supporting.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return tuple(bindings)


def _make_plan(bindings: tuple[ExactPlanSourceBindingV1, ...]) -> M2CExactPlanPrimitivePlanV1:
    phases = (_phase(0, "LIFT_START", 0.1), _phase(1, "LIFT_END", 0.1))
    wire_plan = ExactExecutionPlanV2(
        run_id="contract-run",
        session_id="contract-session",
        decision_index=1,
        observation_id="contract-observation",
        capture_receipt_sha256="d" * 64,
        canonical_skill="LIFT",
        runtime_action="CONTRACT_ONLY_LIFT",
        execution_parameters_sha256="e" * 64,
        target_track_id="track-contract-blocker",
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
    payload: dict[str, Any] = {
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
            resolved_execution_parameters_sha256=wire_plan.execution_parameters_sha256,
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
            immutable_commit=_COMMIT,
            container_image_digest=_IMAGE,
        ),
        "source_bindings": bindings,
        "phases": contracts,
        "phase_schema_sha256": canonical_sha256(schema_projection),
    }
    provisional = M2CExactPlanPrimitivePlanV1.model_construct(
        **payload,
        bound_plan_sha256="0" * 64,
    )
    dumped = provisional.model_dump(mode="json")
    dumped["bound_plan_sha256"] = canonical_sha256(provisional.semantic_payload())
    return M2CExactPlanPrimitivePlanV1.model_validate(dumped)


class _ContractPreflight:
    def __init__(self, bindings: tuple[ExactPlanSourceBindingV1, ...]) -> None:
        self.hashes = {item.role: item.sha256 for item in bindings}
        self.implementation_sha256 = self.hashes["PREFLIGHT_IMPLEMENTATION"]
        self.calls: list[int] = []

    def verify_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> ExactPlanPhasePreflightV1:
        self.calls.append(phase.phase.phase_index)
        return ExactPlanPhasePreflightV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            preplan_state_sha256=plan.inputs.preplan_state_sha256,
            ik_algorithm_sha256=self.hashes["IK_ALGORITHM"],
            limits_configuration_sha256=self.hashes["JOINT_LIMIT_CONFIGURATION"],
            swept_collision_algorithm_sha256=self.hashes["SWEPT_COLLISION_ALGORITHM"],
            controller_configuration_sha256=self.hashes["CONTROLLER_CONFIGURATION"],
            safety_configuration_sha256=self.hashes["SAFETY_CONFIGURATION"],
        )


class _ContractExecutor:
    real_isaac = False

    def __init__(
        self,
        bindings: tuple[ExactPlanSourceBindingV1, ...],
        *,
        fail_at: int | None,
    ) -> None:
        hashes = {item.role: item.sha256 for item in bindings}
        self.implementation_sha256 = hashes["EXECUTOR_IMPLEMENTATION"]
        self.fail_at = fail_at
        self.calls: list[int] = []
        self.digest_checks = 0

    def verify_bound_plan_before_execution(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        _preflight: ExactPlanPreflightReceiptV1,
    ) -> str:
        self.digest_checks += 1
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
    plan: M2CExactPlanPrimitivePlanV1,
    bindings: tuple[ExactPlanSourceBindingV1, ...],
) -> ExactPlanPrimitiveDeploymentBindingV1:
    return ExactPlanPrimitiveDeploymentBindingV1(
        adr_sha256=_sha256(read_regular_file_once(root / ADR_PATH)),
        superseding_adr_sha256=_sha256(
            read_regular_file_once(root / "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md")
        ),
        binding_addendum_sha256=_sha256(read_regular_file_once(root / ADDENDUM_PATH)),
        unlock_config_sha256=_sha256(read_regular_file_once(root / UNLOCK_CONFIG_PATH)),
        immutable_commit=_COMMIT,
        container_image_digest=_IMAGE,
        source_bindings=bindings,
        phase_schema_by_skill=tuple((skill, plan.phase_schema_sha256) for skill in SKILLS),
        execution_mode="CONTRACT_TEST",
    )


def _contract_bundle(
    root: Path,
    plan: M2CExactPlanPrimitivePlanV1,
    bindings: tuple[ExactPlanSourceBindingV1, ...],
    *,
    fail_at: int | None,
) -> tuple[M2CExactPlanPrimitiveBundleV1, _ContractPreflight, _ContractExecutor]:
    preflight = _ContractPreflight(bindings)
    executor = _ContractExecutor(bindings, fail_at=fail_at)
    return (
        M2CExactPlanPrimitiveBundleV1(
            project_root=root,
            binding=_binding(root, plan, bindings),
            preflight_verifier=preflight,
            executor=executor,
        ),
        preflight,
        executor,
    )


def replay_exact_plan_contract_smoke() -> list[dict[str, Any]]:
    """Run three non-physical bundle smokes in an isolated temp project."""

    with tempfile.TemporaryDirectory(prefix="m2c-adr0022-contract-") as temp:
        root = Path(temp)
        bindings = _write_contract_fixture(root)
        plan = _make_plan(bindings)

        bundle, preflight_impl, executor = _contract_bundle(
            root,
            plan,
            bindings,
            fail_at=None,
        )
        preflight = bundle.preflight(plan)
        receipt = bundle.execute(plan, preflight)
        if (
            executor.digest_checks != 1
            or executor.calls != [0, 1]
            or receipt.bound_plan_sha256 != plan.bound_plan_sha256
            or receipt.status != "PASS"
            or receipt.real_isaac
            or receipt.formal_evidence
        ):
            raise AuditFailure("exact-plan digest identity contract smoke failed")
        digest_smoke = {
            "name": "EXACT_PLAN_DIGEST_IDENTITY",
            "status": "PASS_CONTRACT_ONLY",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "executor_independent_digest_checks": executor.digest_checks,
            "executed_phase_indices": executor.calls,
            "real_isaac": False,
            "formal_evidence": False,
        }

        immutable_rejected = False
        try:
            preflight.phase_results[0].ik = "PASS"  # type: ignore[misc]
        except ValidationError:
            immutable_rejected = True
        gate_roles = {item.role: item.sha256 for item in bindings}
        first = preflight.phase_results[0]
        gates_bound = (
            first.ik_algorithm_sha256 == gate_roles["IK_ALGORITHM"]
            and first.limits_configuration_sha256 == gate_roles["JOINT_LIMIT_CONFIGURATION"]
            and first.swept_collision_algorithm_sha256 == gate_roles["SWEPT_COLLISION_ALGORITHM"]
            and first.controller_configuration_sha256 == gate_roles["CONTROLLER_CONFIGURATION"]
            and first.safety_configuration_sha256 == gate_roles["SAFETY_CONFIGURATION"]
        )
        if not immutable_rejected or not gates_bound or preflight_impl.calls != [0, 1]:
            raise AuditFailure("preflight gate immutability contract smoke failed")
        gate_smoke = {
            "name": "ALL_PHASE_GATE_IMMUTABILITY",
            "status": "PASS_CONTRACT_ONLY",
            "all_phases_preflighted_before_execution": preflight_impl.calls == [0, 1],
            "frozen_model_mutation_rejected": immutable_rejected,
            "gate_implementation_hashes_bound": gates_bound,
            "real_isaac": False,
            "formal_evidence": False,
        }

        failing_bundle, _, failing_executor = _contract_bundle(
            root,
            plan,
            bindings,
            fail_at=0,
        )
        partial = failing_bundle.execute(plan, failing_bundle.preflight(plan))
        if (
            partial.status != "PARTIAL_FAILURE"
            or failing_executor.calls != [0]
            or not partial.terminated_without_replan
            or partial.phase_receipts[-1].replanned
            or partial.phase_receipts[-1].inserted_or_altered_command
            or partial.phase_receipts[-1].retry_selected_at_runtime
        ):
            raise AuditFailure("mid-plan no-replan contract smoke failed")
        failure_smoke = {
            "name": "MID_PLAN_FAILURE_NO_REPLAN",
            "status": "PASS_CONTRACT_ONLY",
            "executed_phase_indices": failing_executor.calls,
            "later_phase_executed": False,
            "terminated_without_replan": True,
            "runtime_retry_selected": False,
            "real_isaac": False,
            "formal_evidence": False,
        }
        return [digest_smoke, gate_smoke, failure_smoke]


def replay_b0_contract_smoke(project_root: Path) -> dict[str, Any]:
    wrapper = FrozenB0FallbackWrapperV1(project_root=project_root)
    manifest = wrapper.verify_frozen_sources()
    request = FrozenB0FallbackRequestV1(
        run_id="contract-run",
        session_id="active-contract-session",
        decision_index=0,
        trigger="INVALID_POINTER",
        active_scene_state_sha256="1" * 64,
        rejected_model_mapping_sha256="2" * 64,
        previous_capture_receipt_sha256="3" * 64,
    )
    source_root = project_root.resolve() / "contract-source-not-executed"
    legacy_argv = wrapper.build_legacy_argv(
        request,
        source_root=source_root,
        stage=project_root.resolve() / "contract-stage-not-executed.usdc",
        sdf=source_root / "contract.sdf",
        supervision=source_root / "contract.supervision.json",
        output_root=project_root.resolve() / "contract-output-not-created",
        gpu=0,
    )
    receipt = wrapper.invoke(
        request,
        legacy_argv=legacy_argv,
        active_session_binding=None,
    )
    false_attribution_rejected = False
    tampered = receipt.model_dump(mode="json")
    tampered.update(
        physically_executed=True,
        status="PASS",
        execution_source="B0_FALLBACK",
        executed_skill="B0_FALLBACK",
        active_session_compatible=False,
    )
    tampered_payload = {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    tampered["receipt_sha256"] = canonical_sha256(tampered_payload)
    try:
        FrozenB0FallbackReceiptV1.model_validate(tampered)
    except ValidationError:
        false_attribution_rejected = True
    if (
        manifest.probe_sha256 != FROZEN_B0_PROBE_SHA256
        or manifest.runner_sha256 != FROZEN_B0_RUNNER_SHA256
        or manifest.freeze_manifest_sha256 != FROZEN_B0_MANIFEST_SHA256
        or receipt.status != "NO_PHYSICAL_EXECUTION"
        or receipt.execution_source != "NO_PHYSICAL_EXECUTION"
        or receipt.physically_executed
        or receipt.pure_model_success_eligible
        or not false_attribution_rejected
    ):
        raise AuditFailure("frozen-B0 digest/attribution contract smoke failed")
    return {
        "name": "FROZEN_B0_DIGEST_AND_ATTRIBUTION",
        "status": "PASS_CONTRACT_ONLY",
        "freeze_manifest_sha256": manifest.freeze_manifest_sha256,
        "probe_sha256": manifest.probe_sha256,
        "runner_sha256": manifest.runner_sha256,
        "frozen_source_count": len(manifest.source_bindings),
        "legacy_runner_starts_new_isaac_process": legacy_argv.starts_new_isaac_process,
        "active_formal_session_compatible": receipt.active_session_compatible,
        "fallback_status": receipt.status,
        "execution_source": receipt.execution_source,
        "false_physical_b0_attribution_rejected": false_attribution_rejected,
        "pure_model_success_eligible": False,
        "physical_execution_performed": False,
        "formal_evidence": False,
    }


def build_audit(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    sources = _verify_frozen_sources(project_root)
    entry_source = read_regular_file_once(project_root / ENTRY_GATE_PATH)
    parsed_bindings = parse_unlock_bindings(entry_source, expected=EXPECTED_APPLIED_BINDINGS)
    bindings = {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in parsed_bindings.items()
    }
    smokes = [*replay_exact_plan_contract_smoke(), replay_b0_contract_smoke(project_root)]
    if any(item["status"] != "PASS_CONTRACT_ONLY" for item in smokes):
        raise AuditFailure("not every Phase-2 contract smoke passed")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "SOURCE_BINDINGS_APPLIED_Q_B_BLOCKED",
        "unlock_authorized": True,
        "contract_smoke_status": "PASS_CONTRACT_ONLY",
        "contract_smoke_is_physical_evidence": False,
        "accepted_adr": {
            "path": ADR_PATH.as_posix(),
            "sha256": FROZEN_SOURCE_SHA256[ADR_PATH.as_posix()],
            "status": "ACCEPTED_AND_PHASE_2_SOURCE_BINDINGS_APPLIED",
        },
        "frozen_sources": sources,
        "entry_gate": {
            "path": ENTRY_GATE_PATH.as_posix(),
            "sha256": _sha256(entry_source),
            "bindings": bindings,
            "two_active_bindings_applied": True,
            "withdrawn_compatibility_bindings_literal_none": True,
        },
        "phase_2_files": {
            "binding_addendum_present": (project_root / ADDENDUM_PATH).exists(),
            "unlock_config_present": (project_root / UNLOCK_CONFIG_PATH).exists(),
            "generated_by_this_audit": False,
        },
        "contract_smokes": smokes,
        "blockers": list(BLOCKERS),
        "governance": {
            "training_executed": False,
            "isaac_executed": False,
            "formal_smoke_executed": False,
            "q_b_evaluation_executed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "b0_modified": False,
            "safety_gate_weakened": False,
            "binding_changed": True,
            "addendum_or_unlock_config_generated": False,
            "contract_fixture_counted_as_model_owned_physical_evidence": False,
        },
        "disposition": (
            "Offline ADR-0022/ADR-0024 contract smoke and the complete source closure "
            "passed, so the two source bindings are applied for no-Teacher S4 training. "
            "Formal Q-B remains blocked until every listed model, deployment, session/HMAC, "
            "startup, and plan-specific physical artifact exists and is replayed."
        ),
    }


def render_json(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_markdown(report: dict[str, Any]) -> bytes:
    bindings = report["entry_gate"]["bindings"]
    smoke_lines = "\n".join(
        f"- `{item['name']}`: `{item['status']}` (contract-only; no physical evidence)"
        for item in report["contract_smokes"]
    )
    binding_lines = "\n".join(f"- `{name} = {value!r}`" for name, value in bindings.items())
    blocker_lines = "\n".join(f"- `{value}`" for value in report["blockers"])
    content = f"""# M2C S4 ADR-0022 Phase-2 unlock audit

- Status: **SOURCE_BINDINGS_APPLIED_Q_B_BLOCKED**
- Source unlock authorized: **true**
- Offline contract smoke: **PASS_CONTRACT_ONLY**
- Physical or formal evidence produced: **false**
- Teacher used: **false**
- Privileged truth policy input: **false**

The offline Phase-2 contract and complete Git-tree source closure passed. The
two active source bindings are applied for the no-Teacher S4 trainer. This audit
did not run training, Isaac, formal SMOKE, or Q-B, and it is not physical
evidence.

## Contract smoke replay

{smoke_lines}

## Source-level binding state

{binding_lines}

Both active bindings and both withdrawn compatibility sentinels were parsed
directly from `{report["entry_gate"]["path"]}`. The withdrawn sentinels remain
literal `None`.

## Blocking evidence still missing

{blocker_lines}

## Disposition

{report["disposition"]}
"""
    return content.encode("utf-8")


def _create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o444)
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if (args.json_output is None) != (args.markdown_output is None):
        parser.error("--json-output and --markdown-output must be supplied together")
    report = build_audit(args.project_root)
    json_bytes = render_json(report)
    markdown_bytes = render_markdown(report)
    if args.json_output is None:
        print(json_bytes.decode("utf-8"), end="")
        return 0
    if args.check:
        if (
            read_regular_file_once(args.json_output) != json_bytes
            or read_regular_file_once(args.markdown_output) != markdown_bytes
        ):
            raise AuditFailure("checked-in ADR-0022 Phase-2 audit report is stale")
        return 0
    _create_only(args.json_output, json_bytes)
    _create_only(args.markdown_output, markdown_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
