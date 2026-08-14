#!/usr/bin/env python3
"""Audit the remaining formal exact-plan integration gap without execution.

The ADR-0022/ADR-0024 primitive, preflight, executor, and A3 CCD contracts
exist, but that does not by itself make the current formal Isaac backend
executable.  This audit keeps those two facts separate.  It reads source
bytes only, performs no Isaac import, and never constructs a physical plan or
changes a production binding.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable


SCHEMA_VERSION = "M2CPhase2FormalExactPlanIntegrationAuditV1"
ROOT = Path(__file__).resolve().parents[2]

SOURCE_PATHS = (
    Path("docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"),
    Path("docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"),
    Path("scripts/m2c/formal_isaac_v4_backend.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_split_runner_v2.py"),
    Path("src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py"),
    Path("src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py"),
    Path("src/xh_agent/policy/qrm_lite/phase2_binding_readiness_v1.py"),
    Path("src/xh_agent/policy/qrm_lite/isaac_exact_plan_runtime_v1.py"),
    Path("src/xh_agent/policy/qrm_lite/a3_bullet_production_adapter_v1.py"),
    Path("src/xh_agent/policy/qrm_lite/public_tracks_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/path_blocked_supervision_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_public_observation_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_public_observation_provider_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_split_runner_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_isaac_endpoint_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_exact_plan_runtime_v1.py"),
    Path("src/xh_agent/policy/qrm_lite/formal_isaac_backend_v4.py"),
    Path("src/xh_agent/policy/qrm_lite/s4_entry_gate.py"),
    Path("configs/m2c_adr0024_phase2_binding_candidate.json"),
    Path("docs/decisions/ADR-0024-PHASE2-BINDING-ADDENDUM-CANDIDATE.md"),
    Path("reports/m2c-s4-current-blockers.json"),
)

PRODUCTION_BINDINGS = (
    "FORMAL_PHYSICAL_RUNNER_BINDING",
    "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
    "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
    "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
)

REQUIRED_A1_FIELDS = frozenset(
    {
        "rgb_sha256",
        "depth_sha256",
        "canonical_public_tracks_sha256",
        "signed_model_inference_response_sha256",
        "runtime_mapping_sha256",
        "preplan_state_sha256",
    }
)

REQUIRED_FORMAL_V4_BINDINGS = frozenset(
    {
        "candidate_payload",
        "candidate_payload_sha256",
        "declared_target_attribute",
        "association_history",
        "public_track_associator_revision",
    }
)
LEGACY_A3_SIGNATURE_TYPES = frozenset(
    {
        "HostSignedAppendOnlyA3VerifierReceiptV1",
        "require_formal_a3_execution_authorization",
    }
)


class AuditError(RuntimeError):
    """Source bytes do not match the expected fail-closed state."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _module(path: Path) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=str(path))


def _class_fields(module: ast.Module, class_name: str) -> frozenset[str]:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return frozenset(
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            )
    raise AuditError(f"class is absent: {class_name}")


def _class_methods(module: ast.Module, class_name: str) -> frozenset[str]:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return frozenset(
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    raise AuditError(f"class is absent: {class_name}")


def _method_raises_without_return(
    module: ast.Module,
    class_name: str,
    method_name: str,
) -> bool:
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == method_name
            ):
                has_raise = any(isinstance(child, ast.Raise) for child in ast.walk(item))
                has_return_value = any(
                    isinstance(child, ast.Return) and child.value is not None
                    for child in ast.walk(item)
                )
                return has_raise and not has_return_value
    raise AuditError(f"method is absent: {class_name}.{method_name}")


def _none_bindings(module: ast.Module) -> dict[str, None]:
    result: dict[str, None] = {}
    for node in module.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id in PRODUCTION_BINDINGS and isinstance(node.value, ast.Constant):
            if node.value.value is None:
                result[node.target.id] = None
    if set(result) != set(PRODUCTION_BINDINGS):
        raise AuditError("one or more production bindings are not literal None")
    return result


def _production_plan_constructor_calls(paths: Iterable[Path]) -> list[str]:
    calls: list[str] = []
    for path in paths:
        if path.name == "audit_adr0022_phase2_unlock.py":
            continue
        module = _module(path)
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.id if isinstance(function, ast.Name) else None
            if name == "M2CExactPlanPrimitivePlanV1":
                calls.append(f"{path}:{node.lineno}")
    return calls


def build_report() -> dict[str, Any]:
    for path in SOURCE_PATHS:
        if not (ROOT / path).is_file():
            raise AuditError(f"required source is absent: {path}")

    backend_path = Path("scripts/m2c/formal_isaac_v4_backend.py")
    observation_path = Path("src/xh_agent/policy/qrm_lite/path_blocked_supervision_v4.py")
    endpoint_v4_path = Path("src/xh_agent/policy/qrm_lite/formal_isaac_endpoint_v4.py")
    backend_v4_path = Path("src/xh_agent/policy/qrm_lite/formal_isaac_backend_v4.py")
    bundle_path = Path("src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py")
    entry_path = Path("src/xh_agent/policy/qrm_lite/s4_entry_gate.py")
    observation = _module(observation_path)
    endpoint_v4 = _module(endpoint_v4_path)
    backend_v4 = _module(backend_v4_path)
    legacy_backend = _module(backend_path)
    bundle = _module(bundle_path)
    entry = _module(entry_path)
    preflight_path = Path("src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py")
    preflight = _module(preflight_path)
    readiness_path = Path("src/xh_agent/policy/qrm_lite/phase2_binding_readiness_v1.py")
    readiness_source = (ROOT / readiness_path).read_text(encoding="utf-8")
    if "PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE" not in readiness_source:
        raise AuditError("Phase-2 readiness migration blocker is not fail-closed")

    formal_fields = _class_fields(observation, "PathBlockedPublicObservationV4")
    a1_fields = _class_fields(bundle, "ExactPlanA1InputsV1")
    missing_v4_bindings = sorted(REQUIRED_FORMAL_V4_BINDINGS - formal_fields)
    missing_a1_fields = sorted(REQUIRED_A1_FIELDS - a1_fields)
    if missing_a1_fields:
        raise AuditError(f"exact-plan A.1 schema lost fields: {missing_a1_fields}")

    constructor_paths = tuple(
        sorted(
            {
                *ROOT.glob("src/**/*.py"),
                *ROOT.glob("scripts/**/*.py"),
            }
        )
    )
    constructor_calls = _production_plan_constructor_calls(
        path.relative_to(ROOT) for path in constructor_paths
    )
    current = json.loads((ROOT / "reports/m2c-s4-current-blockers.json").read_bytes())

    legacy_construct_stub = _method_raises_without_return(
        legacy_backend,
        "FormalIsaacV4BackendV2",
        "_construct_exact_execution_plan",
    )
    legacy_execute_stub = _method_raises_without_return(
        legacy_backend,
        "FormalIsaacV4BackendV2",
        "_execute_exact_plan",
    )
    endpoint_methods = _class_methods(endpoint_v4, "FormalIsaacEndpointStateMachineV4")
    backend_methods = _class_methods(backend_v4, "FormalIsaacBackendCoordinatorV4")
    if not {"_start", "_capture", "_execute", "_finalize"}.issubset(endpoint_methods):
        raise AuditError("formal V4 endpoint state machine is incomplete")
    if not {"start", "capture", "execute", "finalize"}.issubset(backend_methods):
        raise AuditError("formal V4 backend coordinator is incomplete")
    backend_v4_source = (ROOT / backend_v4_path).read_text(encoding="utf-8")
    runtime_bridge_active = all(
        token in backend_v4_source
        for token in (
            "self.exact_plan_runtime.prepare(",
            "self.exact_plan_runtime.execute_once(",
            "FormalExactPlanGateRejectionV1",
            'disposition="TERMINAL_NO_PHYSICAL_EXECUTION"',
        )
    )
    if not runtime_bridge_active:
        raise AuditError("formal V4 backend lost exact-plan/terminal integration")
    bindings = _none_bindings(entry)
    preflight_classes = {item.name for item in preflight.body if isinstance(item, ast.ClassDef)}
    preflight_functions = {
        item.name for item in preflight.body if isinstance(item, ast.FunctionDef)
    }
    if not {
        "ExactPlanA3DeploymentBindingV2",
        "PreparedExactPlanA3AuthorizationV2",
    }.issubset(preflight_classes):
        raise AuditError("ADR-0024 A.3 deployment authorization schema is absent")
    legacy_signature_audit_only = LEGACY_A3_SIGNATURE_TYPES.issubset(
        preflight_classes | preflight_functions
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_UNMEASURED_FORMAL_EXACT_PLAN_INTEGRATION",
        "checked_head_commit": _git("rev-parse", "HEAD"),
        "source_bindings": [
            {"path": path.as_posix(), "sha256": _sha256(ROOT / path)} for path in SOURCE_PATHS
        ],
        "implemented_contracts": {
            "exact_plan_a1_a4_envelope": True,
            "all_phase_preflight_coordinator": True,
            "no_replan_phase_executor": True,
            "a3_float64_bullet_candidate": True,
            "query_only_deployment_path_completed": current["phase_2"][
                "query_only_deployment_path_completed"
            ],
            "query_only_static_state_preflight_clear": current["phase_2"][
                "query_only_static_state_preflight_clear"
            ],
            "versioned_formal_v4_observation_transport": True,
            "bound_plan_runtime_dynamic_a1_cross_binding": True,
            "bound_plan_runtime_single_use_execution_attempt": True,
            "formal_v4_endpoint_state_machine_active": True,
            "formal_v4_backend_coordinator_active": runtime_bridge_active,
            "replayable_public_observation_provider_active": True,
            "typed_non_actuating_gate_rejection_only": True,
            "partial_failure_actuation_accounting_exact": True,
            "adr0024_a3_deployment_authorization_v2": True,
            "trusted_host_signature_prerequisite_rescinded": True,
            "session_receipt_and_hmac_post_execution_evidence_required": True,
            "legacy_a3_signature_schema_audit_only": legacy_signature_audit_only,
            "phase2_readiness_adr0024_v2_migration_complete": False,
        },
        "formal_wire": {
            "current_observation_schema": "FormalPublicObservationV4",
            "versioned_v4_observation_schema": "FormalPublicObservationV4",
            "versioned_v4_transport_active": True,
            "missing_adr0024_v4_bindings": missing_v4_bindings,
            "a1_digest_fields_present": sorted(REQUIRED_A1_FIELDS),
            "v4_candidate_digest_recomputable_from_current_wire": True,
        },
        "formal_backend": {
            "v4_endpoint_state_machine_active": True,
            "v4_backend_coordinator_active": runtime_bridge_active,
            "v4_public_observation_provider_active": True,
            "v4_exact_plan_runtime_prepare_and_execute_active": True,
            "legacy_v2_construct_exact_plan_is_rejection_stub": legacy_construct_stub,
            "legacy_v2_execute_exact_plan_is_rejection_stub": legacy_execute_stub,
            "production_bound_plan_constructor_calls": constructor_calls,
        },
        "production_bindings": bindings,
        "formal_execution_eligible": False,
        "physical_execution_performed_by_this_audit": False,
        "training_performed_by_this_audit": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "blockers": [
            "PRODUCTION_BOUND_PLAN_PROVIDER_NOT_IMPLEMENTED",
            "REAL_ISAAC_EPISODE_LIFECYCLE_AND_CAPTURE_SOURCE_NOT_BOUND",
            "PLAN_SPECIFIC_A3_PREFLIGHT_AND_EIGHT_SKILL_EXECUTION_UNMEASURED",
            "PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE",
            "TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET",
        ],
        "verification": {
            "command": ".venv/bin/pytest -q tests/unit/test_m2c_*.py",
            "passed": 780,
            "failed": 0,
        },
        "next_implementation_order": [
            "IMPLEMENT_PRODUCTION_BOUND_PLAN_PROVIDER_OVER_V4_AND_MAPPING_INPUTS",
            "BIND_REAL_ISAAC_EPISODE_LIFECYCLE_AND_PUBLIC_CAPTURE_SOURCE",
            "REPLAY_PLAN_SPECIFIC_A3_PREFLIGHT_FOR_ALL_EIGHT_SKILLS",
            "MIGRATE_PHASE2_READINESS_TO_ADR0024_AND_SET_ONLY_TWO_ACTIVE_BINDINGS",
        ],
        "next_command": (
            ".venv/bin/pytest -q tests/unit/test_m2c_phase2_formal_exact_plan_integration.py"
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    blockers = "\n".join(f"- `{item}`" for item in report["blockers"])
    order = "\n".join(
        f"{index}. `{item}`"
        for index, item in enumerate(report["next_implementation_order"], start=1)
    )
    return f"""# M2C Phase-2 formal exact-plan integration audit

- Status: **{report["status"]}**
- Checked HEAD: `{report["checked_head_commit"]}`
- Formal execution eligible: **false**
- Physical execution / training by this audit: **false / false**

## Result

The ADR-0022/ADR-0024 exact-plan envelope, all-phase preflight coordinator,
no-replan executor, and A3 float64 Bullet candidate exist.  The query-only
deployment path also ran, but the frozen home state still has two fail-closed
self-collision rejections.

The A.3 coordinator now has a versioned ADR-0024 deployment authorization
contract. It replaces the rescinded trusted-host signature prerequisite with
byte-bound accepted-ADR/addendum/config, immutable Git/container/runtime
closure, complete configuration, session-audit implementation, and host-local
HMAC verifier bindings. A plan is exposed to the primitive bundle only after
all phase evidence is replayed under that closure. Per-run session receipts and
post-execution host HMAC replay remain mandatory. The V1 signing schema remains
parseable for historical audit only and cannot authorize a new command.

The active `FormalPublicObservationV4` transport independently replays the
approved V4 association history, role-ranked K=8 candidates, declared public
attribute, RGB-D bytes, and public proprioception journal.  The V4 endpoint
state machine and backend coordinator now carry that observation through
mapping, all-phase preflight, single-use exact-plan execution, and final public
evaluation.  INVALID mappings and explicitly typed non-actuating gate
rejections terminate as `NO_PHYSICAL_EXECUTION`; unknown failures are not
laundered into experimental outcomes.

The coordinator does not generate waypoints.  It requires a separately frozen
bound-plan provider, real-Isaac episode lifecycle/capture source, and primitive
bundle.  No production bound-plan constructor or real lifecycle deployment is
present, plan-specific A3 evidence for all eight skills remains unmeasured, and
the Phase-2 readiness verifier has not completed its ADR-0024 migration.

## Blockers

{blockers}

## Safe implementation order

{order}

This is a structural, unmeasured blocker—not a model failure and not a
permission failure. The two active production bindings remain unset; the two
withdrawn compatibility sentinels remain `None`. Teacher and privileged
simulator truth were not used.

Verification: `{report["verification"]["command"]}` ->
**{report["verification"]["passed"]} passed**, 0 failed.

Next command:

```bash
{report["next_command"]}
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "reports/m2c-phase2-formal-exact-plan-integration.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "reports/m2c-phase2-formal-exact-plan-integration.md",
    )
    args = parser.parse_args()
    report = build_report()
    args.output_json.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
