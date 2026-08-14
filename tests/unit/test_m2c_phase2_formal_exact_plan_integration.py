from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from m2c.audit_phase2_formal_exact_plan_integration import build_report


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/m2c-phase2-formal-exact-plan-integration.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def test_phase2_integration_audit_replays_current_fail_closed_sources() -> None:
    recorded = json.loads(REPORT.read_bytes())
    replayed = build_report()

    assert recorded["schema_version"] == "M2CPhase2FormalExactPlanIntegrationAuditV1"
    assert recorded["status"] == "BLOCKED_UNMEASURED_FORMAL_EXACT_PLAN_INTEGRATION"
    assert recorded["formal_execution_eligible"] is False
    assert recorded["physical_execution_performed_by_this_audit"] is False
    assert recorded["training_performed_by_this_audit"] is False
    assert recorded["teacher_used"] is False
    assert recorded["privileged_truth_policy_input"] is False

    assert recorded["source_bindings"] == replayed["source_bindings"]
    assert recorded["formal_wire"] == replayed["formal_wire"]
    assert recorded["formal_backend"] == replayed["formal_backend"]
    assert recorded["production_bindings"] == replayed["production_bindings"]
    assert recorded["blockers"] == replayed["blockers"]
    assert recorded["verification"] == {
        "command": ".venv/bin/pytest -q tests/unit/test_m2c_*.py",
        "passed": 809,
        "failed": 0,
    }

    for binding in recorded["source_bindings"]:
        assert _sha256(ROOT / binding["path"]) == binding["sha256"]

    report_commit = _git("log", "-1", "--format=%H", "--", str(REPORT.relative_to(ROOT)))
    checked = recorded["checked_head_commit"]
    head = _git("rev-parse", "HEAD")
    assert checked == head or checked in _git("show", "-s", "--format=%P", report_commit).split()


def test_audit_separates_implemented_contracts_from_missing_formal_path() -> None:
    report = json.loads(REPORT.read_bytes())

    assert all(
        report["implemented_contracts"][name]
        for name in (
            "exact_plan_a1_a4_envelope",
            "all_phase_preflight_coordinator",
            "no_replan_phase_executor",
            "a3_float64_bullet_candidate",
            "query_only_deployment_path_completed",
            "adr0024_a3_deployment_authorization_v2",
            "trusted_host_signature_prerequisite_rescinded",
            "session_receipt_and_hmac_post_execution_evidence_required",
            "legacy_a3_signature_schema_audit_only",
            "formal_v4_endpoint_state_machine_active",
            "formal_v4_backend_coordinator_active",
            "formal_v4_host_orchestrator_active",
            "formal_v4_http_service_shell_active",
            "formal_v4_host_local_hmac_replay_active",
            "replayable_public_observation_provider_active",
            "typed_non_actuating_gate_rejection_only",
            "partial_failure_actuation_accounting_exact",
            "deployment_bound_plan_provider_contract_active",
        )
    )
    assert (
        report["implemented_contracts"]["phase2_readiness_adr0024_v2_migration_complete"] is False
    )
    assert "PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE" in report["blockers"]
    assert report["implemented_contracts"]["query_only_static_state_preflight_clear"] is False
    assert report["formal_backend"] == {
        "v4_endpoint_state_machine_active": True,
        "v4_backend_coordinator_active": True,
        "v4_public_observation_provider_active": True,
        "v4_exact_plan_runtime_prepare_and_execute_active": True,
        "v4_bound_plan_provider_contract_active": True,
        "v4_host_orchestrator_contract_active": True,
        "v4_http_service_shell_active": True,
        "v4_http_service_backend_factory_bound": False,
        "legacy_v2_construct_exact_plan_is_rejection_stub": True,
        "legacy_v2_execute_exact_plan_is_rejection_stub": True,
        "production_bound_plan_constructor_calls": [],
    }
    assert report["formal_wire"]["missing_adr0024_v4_bindings"] == []
    assert report["formal_wire"]["v4_candidate_digest_recomputable_from_current_wire"] is True
    assert report["formal_wire"]["versioned_v4_observation_schema"] == ("FormalPublicObservationV4")
    assert report["formal_wire"]["versioned_v4_transport_active"] is True
    assert "REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND" in report["blockers"]
    assert report["implemented_contracts"]["versioned_formal_v4_observation_transport"] is True
    assert report["implemented_contracts"]["bound_plan_runtime_dynamic_a1_cross_binding"] is True
    assert (
        report["implemented_contracts"]["bound_plan_runtime_single_use_execution_attempt"] is True
    )
    assert set(report["production_bindings"]) == {
        "FORMAL_PHYSICAL_RUNNER_BINDING",
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
    }
    assert all(value is None for value in report["production_bindings"].values())
