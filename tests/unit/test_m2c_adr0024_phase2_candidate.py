from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from m2c.audit_adr0024_phase2_candidate import (
    BINDING_NAMES,
    CandidateAuditFailure,
    EXPECTED_BLOCKERS,
    build_audit,
    load_candidate_config,
    parse_literal_none_bindings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_smoke_is_blocked_unmeasured_and_never_physical() -> None:
    report = build_audit(PROJECT_ROOT)

    assert report["status"] == "CONTRACT_SMOKE_ONLY_BLOCKED_UNMEASURED"
    assert not report["production_binding_authorized"]
    assert report["entry_bindings"] == {name: None for name in BINDING_NAMES}
    assert report["blockers"] == list(EXPECTED_BLOCKERS)
    assert "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING" not in report["blockers"]
    assert "REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING" in report["blockers"]
    assert len(report["contract_smokes"]) == 3
    assert all(item["status"] == "PASS_CONTRACT_ONLY" for item in report["contract_smokes"])
    assert report["a3_local_closure"]["status"] == "NOT_AVAILABLE"
    assert not report["a3_local_closure"]["formal_execution_eligible"]
    assert report["a3_native_build_evidence"]["status"] == (
        "PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY"
    )
    assert report["a3_native_build_evidence"]["builder_image_id"] == (
        "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
    )
    assert not report["a3_native_build_evidence"]["formal_execution_eligible"]
    assert report["a3_read_only_fk_evidence"]["status"] == (
        "PASS_QUERY_ONLY_FK_MATCHES_INDEPENDENT_NODE2_KDL"
    )
    assert report["a3_read_only_fk_evidence"]["comparison_row_count"] == 144
    assert not report["a3_read_only_fk_evidence"]["formal_execution_eligible"]
    assert report["a3_query_only_deployment_smoke"]["clear_result_count"] == 74
    assert report["a3_query_only_deployment_smoke"]["collision_rejection_count"] == 2
    assert not report["a3_query_only_deployment_smoke"]["static_state_preflight_clear"]
    assert not report["a3_query_only_deployment_smoke"]["formal_execution_eligible"]
    assert not report["governance"]["contract_smoke_is_physical_evidence"]
    assert not report["governance"]["teacher_used"]


def test_candidate_config_requires_literal_none_bindings_and_exact_terminal_policy(
    tmp_path: Path,
) -> None:
    source = "\n".join(f"{name}: object | None = None" for name in BINDING_NAMES)
    assert parse_literal_none_bindings(source.encode()) == {name: None for name in BINDING_NAMES}
    with pytest.raises(CandidateAuditFailure, match="literal None"):
        parse_literal_none_bindings(
            source.replace(
                "FORMAL_PHYSICAL_RUNNER_BINDING: object | None = None",
                "FORMAL_PHYSICAL_RUNNER_BINDING: object | None = ('runner', 'digest')",
            ).encode()
        )

    candidate = load_candidate_config(PROJECT_ROOT)
    executor_path = "src/xh_agent/policy/qrm_lite/isaac_exact_plan_runtime_v1.py"
    assert (
        candidate["source_bindings"][executor_path]
        == hashlib.sha256((PROJECT_ROOT / executor_path).read_bytes()).hexdigest()
    )
    assert candidate["b0_policy"]["invalid_or_rejected_action_policy"] == (
        "TERMINAL_NO_PHYSICAL_EXECUTION"
    )
    assert not candidate["b0_policy"]["runtime_wrapper_required"]


def test_candidate_source_tamper_and_false_physical_claim_fail_closed(tmp_path: Path) -> None:
    candidate_path = PROJECT_ROOT / "configs/m2c_adr0024_phase2_binding_candidate.json"
    candidate = json.loads(candidate_path.read_text())
    candidate["evidence_claims"]["formal_execution_eligible"] = True
    fake_root = tmp_path / "project"
    destination = fake_root / "configs/m2c_adr0024_phase2_binding_candidate.json"
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(candidate))

    with pytest.raises(CandidateAuditFailure, match="evidence claims"):
        load_candidate_config(fake_root)


def test_candidate_addendum_explicitly_disclaims_addendum_binding_and_runs() -> None:
    content = (
        PROJECT_ROOT / "docs/decisions/ADR-0024-PHASE2-BINDING-ADDENDUM-CANDIDATE.md"
    ).read_text()
    assert "not an accepted binding addendum" in content
    assert "No training, Isaac scene startup, physical action, SMOKE, Q-B" in content
    assert "Teacher used: **false**" in content
