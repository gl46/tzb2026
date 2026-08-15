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
    assert "COMPLETE_SCENE_ENVIRONMENT_SWEPT_COLLISION_PROVIDER_NOT_BOUND" in report["blockers"]
    assert "REAL_ATTACHED_OBJECT_PHASE_GEOMETRY_RESOLVER_NOT_BOUND" in report["blockers"]
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
    assert report["a3_acm_evidence"]["authorized_pair_count"] == 2
    assert report["a3_acm_evidence"]["criterion"] == "A_OFFICIAL_UPSTREAM_SRDF"
    assert not report["a3_acm_evidence"]["formal_execution_eligible"]
    assert report["a3_query_only_deployment_smoke"]["request_segment_count"] == 74
    assert report["a3_query_only_deployment_smoke"]["clear_result_count"] == 74
    assert report["a3_query_only_deployment_smoke"]["collision_rejection_count"] == 0
    assert report["a3_query_only_deployment_smoke"]["static_state_preflight_clear"]
    assert not report["a3_query_only_deployment_smoke"]["formal_execution_eligible"]
    synthesis = report["exact_plan_synthesis_candidate"]
    assert synthesis["registered_skill_count"] == 8
    assert synthesis["runtime_parameter_adaptation_allowed"] is False
    assert synthesis["physical_execution_claimed"] is False
    assert synthesis["query_source_contract_active"] is True
    assert synthesis["per_decision_component_graph_contract_active"] is True
    assert synthesis["public_track_collision_safety_binding_contract_active"] is True
    assert synthesis["real_scene_safety_binding_source_bound"] is False
    assert synthesis["real_query_source_bound"] is False
    assert synthesis["real_per_decision_component_graph_bound"] is False
    assert synthesis["reviewed_production_deployment_bound"] is False
    assert synthesis["formal_execution_eligible"] is False
    component_graph = report["per_decision_exact_plan_component_graph"]
    assert component_graph["status"] == "PASS_CONTRACT_ONLY_NOT_PRODUCTION_BOUND"
    assert component_graph["same_scene_mutation_counter_bound"] is True
    assert component_graph["complete_query_preflight_executor_graph_constructed"] is True
    assert component_graph["real_eight_skill_receipts_present"] is False
    assert component_graph["formal_authorization"] is False
    episode_io = report["formal_isaac_episode_io_candidate"]
    assert episode_io["shared_persistent_scene_owner_required"] is True
    assert episode_io["public_failure_boundary_evidence_bound"] is True
    assert episode_io["eight_capture_prefix_replay_bound"] is True
    assert episode_io["public_final_evaluation_bound"] is True
    assert episode_io["source_and_git_snapshot_verified_before_owner_contact"] is True
    assert episode_io["real_scene_owner_deployment_bound"] is False
    assert episode_io["http_backend_factory_bound"] is False
    assert episode_io["formal_execution_eligible"] is False
    hmac = report["formal_v4_host_local_hmac_verifier"]
    assert hmac["status"] == "PASS_CONTRACT_ONLY_NO_REAL_HOST_RECEIPTS"
    assert hmac["node2_and_labserver_replay_implemented"] is True
    assert hmac["variable_terminal_envelope_counts_supported"] is True
    assert hmac["trusted_host_signature_required"] is False
    assert hmac["real_host_receipts_present"] is False
    assert hmac["formal_authorization"] is False
    readiness = report["phase2_readiness_verifier"]
    assert readiness == {
        "status": "PASS_ADR0024_V2_CONTRACT_NO_REAL_EVIDENCE_INDEX",
        "evidence_index_schema": "M2CADR0024Phase2EvidenceIndexV2",
        "signed_host_receipts_required": False,
        "active_session_b0_wrapper_required": False,
        "real_evidence_index_present": False,
        "binding_application_authorized": False,
    }
    scene = report["formal_isaac_a3_scene_source"]
    assert scene == {
        "status": "PASS_CONTRACT_ONLY_NO_REAL_SCENE_RECEIPT",
        "complete_scene_collision_link_count": 8,
        "post_stability_mutation_counter_active": True,
        "attached_object_phase_geometry_replay_active": True,
        "real_scene_state_receipt_present": False,
        "real_attached_object_phase_geometry_receipt_present": False,
        "formal_authorization": False,
    }
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
    callback_path = "src/xh_agent/policy/qrm_lite/a3_exact_plan_callbacks_v1.py"
    assert (
        candidate["source_bindings"][callback_path]
        == hashlib.sha256((PROJECT_ROOT / callback_path).read_bytes()).hexdigest()
    )
    for complete_scene_path in (
        "scripts/m2c/formal_isaac_v4_backend.py",
        "src/xh_agent/policy/qrm_lite/a3_attached_object_phase_geometry_v1.py",
        "src/xh_agent/policy/qrm_lite/a3_scene_environment_v1.py",
        "src/xh_agent/policy/qrm_lite/a3_complete_scene_collision_v2.py",
        "src/xh_agent/policy/qrm_lite/a3_complete_scene_swept_collision_evidence_v2.py",
        "src/xh_agent/policy/qrm_lite/a3_complete_scene_swept_collision_v2.py",
        "src/xh_agent/policy/qrm_lite/formal_isaac_mutation_counter_v1.py",
    ):
        assert (
            candidate["source_bindings"][complete_scene_path]
            == hashlib.sha256((PROJECT_ROOT / complete_scene_path).read_bytes()).hexdigest()
        )
    assert (
        candidate["source_bindings"]["src/xh_agent/policy/qrm_lite/formal_split_host_v4.py"]
        == hashlib.sha256(
            (PROJECT_ROOT / "src/xh_agent/policy/qrm_lite/formal_split_host_v4.py").read_bytes()
        ).hexdigest()
    )
    assert (
        candidate["source_bindings"]["scripts/m2c/run_formal_model_owned_chain_v4.py"]
        == hashlib.sha256(
            (PROJECT_ROOT / "scripts/m2c/run_formal_model_owned_chain_v4.py").read_bytes()
        ).hexdigest()
    )
    assert (
        candidate["source_bindings"]["scripts/m2c/serve_formal_isaac_endpoint_v4.py"]
        == hashlib.sha256(
            (PROJECT_ROOT / "scripts/m2c/serve_formal_isaac_endpoint_v4.py").read_bytes()
        ).hexdigest()
    )
    for path in (
        "src/xh_agent/policy/qrm_lite/offline_wire_auth_v4.py",
        "scripts/m2c/verify_formal_wire_auth_v4.py",
        "src/xh_agent/policy/qrm_lite/formal_isaac_episode_io_v4.py",
    ):
        assert (
            candidate["source_bindings"][path]
            == hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
        )
    synthesis = candidate["exact_plan_synthesis_candidate"]
    for key in (
        "configuration_path",
        "dependency_manifest_path",
        "backend_implementation_path",
        "query_source_implementation_path",
        "active_session_query_implementation_path",
        "per_decision_bundle_factory_implementation_path",
        "per_decision_component_source_implementation_path",
        "formal_runtime_factory_implementation_path",
    ):
        sha_key = {
            "configuration_path": "configuration_file_sha256",
            "dependency_manifest_path": "dependency_manifest_sha256",
            "backend_implementation_path": "backend_implementation_sha256",
            "query_source_implementation_path": "query_source_implementation_sha256",
            "active_session_query_implementation_path": (
                "active_session_query_implementation_sha256"
            ),
            "per_decision_bundle_factory_implementation_path": (
                "per_decision_bundle_factory_implementation_sha256"
            ),
            "per_decision_component_source_implementation_path": (
                "per_decision_component_source_implementation_sha256"
            ),
            "formal_runtime_factory_implementation_path": (
                "formal_runtime_factory_implementation_sha256"
            ),
        }[key]
        assert (
            synthesis[sha_key]
            == hashlib.sha256((PROJECT_ROOT / synthesis[key]).read_bytes()).hexdigest()
        )
    dependencies = json.loads((PROJECT_ROOT / synthesis["dependency_manifest_path"]).read_text())[
        "dependencies"
    ]
    assert len(dependencies) == 69
    for path in (
        "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_bundle_factory_v1.py",
        "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_components_v1.py",
        "src/xh_agent/policy/qrm_lite/a3_complete_scene_swept_collision_v2.py",
        "src/xh_agent/policy/qrm_lite/controlled_panda_fk_v1.py",
        "src/xh_agent/policy/qrm_lite/isaac_exact_plan_runtime_v1.py",
    ):
        assert dependencies[path] == hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
    episode_io = candidate["episode_io_candidate"]
    assert (
        episode_io["implementation_sha256"]
        == hashlib.sha256(
            (PROJECT_ROOT / episode_io["implementation_path"]).read_bytes()
        ).hexdigest()
    )
    assert episode_io["implementation_commit"] == ("961f370420b8c2073b4431751574a48502ce6c70")


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
    assert "A_OFFICIAL_UPSTREAM_SRDF" in content
    assert "All 74 governed child-pair requests were clear" in content
    assert "FormalIsaacExactPlanComponentSourceV1" in content
    assert "exact 9-joint executor/FK state" in content
    assert "No training, Isaac scene startup, physical action, Q-B" in content
    assert "Teacher used: **false**" in content
