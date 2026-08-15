from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/m2c-s4-current-blockers.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _load_binding(binding: dict[str, str]) -> dict[str, object]:
    path = ROOT / binding["path"]
    assert _sha256(path) == binding["sha256"]
    return json.loads(path.read_bytes())


def _v3_counts(bindings: list[dict[str, str]]) -> tuple[int, int]:
    keys: set[str] = set()
    chains = 0
    for binding in bindings:
        source = _load_binding(binding)
        assert source["observed_counts"]["training_samples_eligible"] == 0
        assert source["observed_counts"]["training_samples_packaged"] == 0
        for attempt in source["attempts"]:
            keys.add(attempt["identity"]["matched_key"])
            evidence = attempt["classification_evidence"]
            if evidence.get("chain_schema") == "M2CPathBlockedProbeChainV3":
                assert evidence["physical_chain_steps"] == 8
                chains += 1
    return len(keys), chains


def _v4_counts(bindings: list[dict[str, str]]) -> tuple[int, int, int, int]:
    keys: set[str] = set()
    chains = physical_receipts = safety_violations = 0
    for binding in bindings:
        source = _load_binding(binding)
        counts = source["observed_counts"]
        assert counts["training_samples_eligible"] == 0
        assert counts["training_samples_packaged"] == 0
        for attempt in source["attempts"]:
            keys.add(attempt["identity"]["matched_key"])
            if attempt.get("raw_chain_schema") == "M2CPathBlockedRawProbeChainV4":
                chains += 1
                physical_receipts += attempt["physical_skill_receipts"]
                safety_violations += attempt["collision_or_safety_violations"]
    return len(keys), chains, physical_receipts, safety_violations


def test_current_s4_blocker_report_replays_v3_and_v4_collection() -> None:
    report = json.loads(REPORT.read_bytes())

    assert report["schema_version"] == "M2CS4CurrentBlockersV2"
    assert report["status"] == (
        "BLOCKED_UNMEASURED_ZERO_ELIGIBLE_YIELD_AND_FORMAL_EXACT_PLAN_INTEGRATION"
    )
    assert report["q_a_state"] == "PASSED"
    assert report["q_b_state"] == "UNMEASURED"
    assert report["pure_model_success_episodes"] is None
    assert report["d1_triggered"] is False
    assert report["d2_triggered"] is False

    training = report["path_blocked_training"]
    v3_bindings = training["source_reports"][:2]
    v4_bindings = training["source_reports"][2:]
    assert _v3_counts(v3_bindings) == (11, 10)
    assert _v4_counts(v4_bindings) == (51, 39, 312, 0)
    assert training["unique_v3_train_keys_attempted"] == 11
    assert training["unique_v4_train_keys_consumed"] == 51
    assert training["unique_train_keys_consumed_total"] == 62
    assert training["raw_v3_eight_step_chains"] == 10
    assert training["raw_v4_eight_step_chains"] == 39
    assert training["physical_skill_receipts_v4"] == 312
    assert training["collision_or_safety_violations_v4"] == 0
    assert training["training_samples_eligible"] == 0
    assert training["training_samples_packaged"] == 0
    assert training["original_frozen_v4_train_manifest_exhausted"] is True
    assert training["v4_extension1_train_keys_consumed"] == 15
    assert training["remaining_unconsumed_v4_extension1_train_keys"] == 21
    assert training["frozen_v4_train_keys_total"] == 72
    assert not any(
        training[field]
        for field in (
            "training_executed",
            "model_rollout_executed",
            "formal_q_b_evaluation_executed",
            "active_selected_key_preregistration_present",
            "collection_execution_authorized",
        )
    )

    permission = training["permission_issue_resolution"]
    assert permission["resolved_for_observed_batch23_path"] is True
    assert permission["batch04_stage_output_permission_failures"] == 3
    assert training["batch_04_preregistered_and_consumed"] is True
    assert training["latest_completed_batch"] == "BATCH_23"

    report_commit = _git("log", "-1", "--format=%H", "--", str(REPORT.relative_to(ROOT)))
    checked_commit = report["checked_head_commit"]
    current_head = _git("rev-parse", "HEAD")
    assert (
        checked_commit == current_head
        or checked_commit in _git("show", "-s", "--format=%P", report_commit).split()
    )


def test_raw_detection_capacity_is_accepted_but_training_remains_fail_closed() -> None:
    report = json.loads(REPORT.read_bytes())
    training = report["path_blocked_training"]
    accepted = training["accepted_raw_capacity_decision"]
    assert _sha256(ROOT / accepted["path"]) == accepted["sha256"]
    assert accepted["status"] == "ACCEPTED_HUMAN_DECISION"
    assert accepted["selected_option"] == "A"
    assert accepted["max_raw_public_detections"] == 32
    assert accepted["observed_maximum_is_not_numeric_authority"] is True
    assert accepted["offline_replay_authorized"] is True
    assert accepted["new_collection_authorized"] is True
    assert accepted["training_authorized"] is False
    assert training["raw_detection_capacity_decision_required"] is False

    replay = _load_binding(training["scene_19083_offline_replay"])
    assert replay["status"] == "PASS_OFFLINE_REPLAY_EXCLUDED_UNCHANGED_PHYSICAL_FAILURE"
    assert replay["unchanged_outcome"]["training_sample_eligible"] is False
    assert replay["unchanged_outcome"]["offline_dataset_sample_count"] == 0
    yield_report = _load_binding(training["training_eligibility_yield"])
    assert yield_report["observed_yield"]["eligible_training_episodes"] == 0
    assert yield_report["identity_audit"]["unique_train_identities_total"] == 62
    assert yield_report["observed_yield"]["complete_eight_step_chains"] == 49
    assert yield_report["observed_yield"]["finite_key_projection_for_one_eligible_episode"] is None

    extension = training["training_manifest_extension1"]
    assert _sha256(ROOT / extension["path"]) == extension["sha256"]

    batch08 = _load_binding(training["source_reports"][-16])
    raw_attempt = next(
        attempt for attempt in batch08["attempts"] if attempt.get("raw_probe_sha256")
    )
    assert raw_attempt["raw_capture_detection_counts"] == [7, 13, 11, 7, 8, 9, 10, 10]
    assert raw_attempt["raw_chain_final_task_success"] is False
    assert raw_attempt["host_replay_passed"] is False
    assert raw_attempt["training_sample_packaged"] is False

    batch09 = _load_binding(training["source_reports"][-15])
    assert batch09["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch09["observed_counts"]["host_replay_passes"] == 3
    assert batch09["observed_counts"]["physical_skill_receipts"] == 24
    assert batch09["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch09["observed_counts"]["training_samples_eligible"] == 0

    batch10 = _load_binding(training["source_reports"][-14])
    assert batch10["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch10["observed_counts"]["host_replay_passes"] == 3
    assert batch10["observed_counts"]["physical_skill_receipts"] == 24
    assert batch10["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch10["observed_counts"]["training_samples_eligible"] == 0

    batch11 = _load_binding(training["source_reports"][-13])
    assert batch11["observed_counts"]["stage_process_exit_139"] == 1
    assert batch11["observed_counts"]["stage_acceptance_passes"] == 2
    assert batch11["observed_counts"]["host_replay_passes"] == 2
    assert batch11["observed_counts"]["physical_skill_receipts"] == 16
    assert batch11["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch11["observed_counts"]["training_samples_eligible"] == 0

    batch12 = _load_binding(training["source_reports"][-12])
    assert batch12["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch12["observed_counts"]["host_replay_passes"] == 3
    assert batch12["observed_counts"]["physical_skill_receipts"] == 24
    assert batch12["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch12["observed_counts"]["training_samples_eligible"] == 0

    batch13 = _load_binding(training["source_reports"][-11])
    assert batch13["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch13["observed_counts"]["host_replay_passes"] == 3
    assert batch13["observed_counts"]["physical_skill_receipts"] == 24
    assert batch13["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch13["observed_counts"]["training_samples_eligible"] == 0

    batch14 = _load_binding(training["source_reports"][-10])
    assert batch14["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch14["observed_counts"]["host_replay_passes"] == 3
    assert batch14["observed_counts"]["physical_skill_receipts"] == 24
    assert batch14["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch14["observed_counts"]["training_samples_eligible"] == 0

    batch15 = _load_binding(training["source_reports"][-9])
    assert batch15["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch15["observed_counts"]["host_replay_passes"] == 3
    assert batch15["observed_counts"]["physical_skill_receipts"] == 24
    assert batch15["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch15["observed_counts"]["training_samples_eligible"] == 0

    batch16 = _load_binding(training["source_reports"][-8])
    assert batch16["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch16["observed_counts"]["host_replay_passes"] == 3
    assert batch16["observed_counts"]["physical_skill_receipts"] == 24
    assert batch16["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch16["observed_counts"]["training_samples_eligible"] == 0

    batch17 = _load_binding(training["source_reports"][-7])
    assert batch17["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch17["observed_counts"]["host_replay_passes"] == 3
    assert batch17["observed_counts"]["physical_skill_receipts"] == 24
    assert batch17["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch17["observed_counts"]["training_samples_eligible"] == 0

    batch18 = _load_binding(training["source_reports"][-6])
    assert batch18["observed_counts"]["stage_acceptance_passes"] == 1
    assert batch18["observed_counts"]["host_replay_passes"] == 1
    assert batch18["observed_counts"]["physical_skill_receipts"] == 8
    assert batch18["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch18["observed_counts"]["training_samples_eligible"] == 0

    batch19 = _load_binding(training["source_reports"][-5])
    assert batch19["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch19["observed_counts"]["host_replay_passes"] == 3
    assert batch19["observed_counts"]["physical_skill_receipts"] == 24
    assert batch19["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch19["observed_counts"]["training_samples_eligible"] == 0

    batch20 = _load_binding(training["source_reports"][-4])
    assert batch20["observed_counts"]["stage_process_exit_139"] == 1
    assert batch20["observed_counts"]["stage_acceptance_passes"] == 2
    assert batch20["observed_counts"]["host_replay_passes"] == 2
    assert batch20["observed_counts"]["physical_skill_receipts"] == 16
    assert batch20["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch20["observed_counts"]["training_samples_eligible"] == 0

    batch21 = _load_binding(training["source_reports"][-3])
    assert batch21["observed_counts"]["stage_acceptance_passes"] == 3
    assert batch21["observed_counts"]["host_replay_passes"] == 3
    assert batch21["observed_counts"]["physical_skill_receipts"] == 24
    assert batch21["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch21["observed_counts"]["training_samples_eligible"] == 0

    batch22 = _load_binding(training["source_reports"][-2])
    assert batch22["observed_counts"]["stage_process_exit_139"] == 2
    assert batch22["observed_counts"]["stage_acceptance_passes"] == 1
    assert batch22["observed_counts"]["host_replay_passes"] == 1
    assert batch22["observed_counts"]["physical_skill_receipts"] == 8
    assert batch22["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch22["observed_counts"]["training_samples_eligible"] == 0

    batch23 = _load_binding(training["source_reports"][-1])
    assert batch23["observed_counts"]["stage_process_exit_139"] == 1
    assert batch23["observed_counts"]["stage_acceptance_passes"] == 2
    assert batch23["observed_counts"]["host_replay_passes"] == 2
    assert batch23["observed_counts"]["physical_skill_receipts"] == 16
    assert batch23["observed_counts"]["collision_or_safety_violations"] == 0
    assert batch23["observed_counts"]["training_samples_eligible"] == 0


def test_phase2_query_only_evidence_remains_non_authorizing() -> None:
    report = json.loads(REPORT.read_bytes())
    phase2 = report["phase_2"]

    candidate = _load_binding(phase2["candidate_config"])
    addendum = phase2["candidate_addendum"]
    assert _sha256(ROOT / addendum["path"]) == addendum["sha256"]
    comparison = _load_binding(phase2["query_only_comparison_report"])

    assert candidate["status"] == "CONTRACT_SMOKE_ONLY_BLOCKED_UNMEASURED"
    assert comparison["status"] == "PASS_QUERY_ONLY_A3_ACM_SMOKE_CLEAR"
    assert phase2["query_only_deployment_path_completed"] is True
    assert phase2["query_only_static_state_preflight_clear"] is True
    assert phase2["query_only_clear_child_pairs"] == 74
    assert phase2["query_only_collision_rejections"] == 0
    assert phase2["query_only_query_failures"] == 0
    assert phase2["a3_phase_swept_collision_contract_active"] is True
    assert phase2["a3_phase_evidence_replay_active"] is True
    assert phase2["real_a3_phase_evidence_present"] is False
    assert phase2["a3_attachment_transition_contract_active"] is True
    assert phase2["a3_attachment_evidence_replay_active"] is True
    assert phase2["exact_plan_query_callback_composite_active"] is True
    assert phase2["complete_continuous_self_collision_provider_contract_active"] is True
    assert phase2["scene_environment_geometry_contract_active"] is True
    assert phase2["scene_environment_state_query_contract_active"] is True
    assert phase2["formal_isaac_scene_query_sources_wired"] is True
    assert phase2["formal_isaac_post_stability_mutation_counter_active"] is True
    assert phase2["attached_object_phase_geometry_contract_active"] is True
    assert phase2["attached_object_phase_geometry_derivation_evidence_replay_active"] is True
    assert phase2["complete_scene_environment_swept_collision_provider_contract_active"] is True
    assert phase2["contract_scene_collision_primitive_count"] == 8
    assert phase2["contract_scene_dynamic_collision_primitive_count"] == 6
    assert phase2["contract_scene_static_collision_primitive_count"] == 2
    assert phase2["complete_scene_environment_swept_collision_provider_bound"] is False
    assert phase2["real_scene_environment_state_receipt_present"] is False
    assert phase2["real_attached_object_phase_geometry_resolver_bound"] is False
    assert phase2["real_runtime_snapshot_bound"] is False
    assert phase2["bound_plan_provider_contract_active"] is True
    assert phase2["exact_plan_synthesis_backend_contract_active"] is True
    assert phase2["per_decision_exact_plan_component_graph_contract_active"] is True
    assert phase2["real_per_decision_exact_plan_component_graph_bound"] is False
    synthesis = phase2["exact_plan_synthesis_configuration_candidate"]
    assert synthesis["sha256"] == _sha256(ROOT / synthesis["path"])
    assert synthesis["dependency_manifest_sha256"] == _sha256(
        ROOT / synthesis["dependency_manifest_path"]
    )
    assert synthesis["implementation_commit"] == "1b97b6edb7e3678dd134a113f678e9d8feda9175"
    assert synthesis["registered_skill_count"] == 8
    assert synthesis["query_source_contract_active"] is True
    assert synthesis["per_decision_component_graph_contract_active"] is True
    assert synthesis["public_track_collision_safety_binding_contract_active"] is True
    assert synthesis["real_scene_safety_binding_source_bound"] is False
    assert synthesis["real_query_source_bound"] is False
    assert synthesis["real_per_decision_component_graph_bound"] is False
    assert synthesis["reviewed_production_deployment_bound"] is False
    assert synthesis["formal_execution_eligible"] is False
    assert phase2["real_bound_plan_synthesis_backend_bound"] is False
    assert phase2["formal_v4_episode_io_contract_active"] is True
    episode_io = phase2["formal_v4_episode_io_implementation"]
    assert episode_io["sha256"] == _sha256(ROOT / episode_io["path"])
    assert episode_io["implementation_commit"] == ("961f370420b8c2073b4431751574a48502ce6c70")
    assert phase2["formal_v4_shared_persistent_scene_owner_required"] is True
    assert phase2["formal_v4_public_failure_boundary_evidence_bound"] is True
    assert phase2["formal_v4_eight_capture_prefix_replay_bound"] is True
    assert phase2["formal_v4_public_final_evaluation_bound"] is True
    assert phase2["real_formal_v4_episode_io_deployment_bound"] is False
    assert phase2["exact_plan_executor_contract_active"] is True
    assert phase2["real_exact_plan_executor_deployment_binding_bound"] is False
    assert phase2["formal_v4_host_orchestrator_contract_active"] is True
    assert phase2["formal_v4_http_service_shell_active"] is True
    assert phase2["formal_v4_host_local_hmac_verifier_active"] is True
    assert phase2["phase2_readiness_adr0024_v2_migration_complete"] is True
    assert phase2["s4_entry_gate_formal_v4_replay_active"] is True
    assert phase2["real_node2_and_labserver_hmac_receipts_present"] is False
    assert phase2["real_formal_v4_isaac_http_service_bound"] is False
    assert phase2["formal_execution_eligible"] is False
    assert phase2["remaining_rejected_pairs"] == comparison["query_result"]["rejected_pairs"]
    assert all(
        phase2[field] is None
        for field in (
            "formal_physical_runner_binding",
            "formal_deployment_closure_binding",
            "frozen_b0_runtime_wrapper_binding",
            "offline_wire_authentication_verifier_binding",
        )
    )
    assert "A3_STATIC_HOME_SELF_COLLISION_PREFLIGHT_REJECTED" not in phase2["blockers"]
    assert "COMPLETE_SCENE_ENVIRONMENT_SWEPT_COLLISION_PROVIDER_NOT_BOUND" in phase2["blockers"]
    assert "REAL_ATTACHED_OBJECT_PHASE_GEOMETRY_RESOLVER_NOT_BOUND" in phase2["blockers"]
    assert "REAL_PUBLIC_TRACK_TO_COLLISION_PATH_A3_SAFETY_BINDING_NOT_BOUND" in phase2["blockers"]
    assert "REVIEWED_REAL_ISAAC_EPISODE_IO_DEPLOYMENT_NOT_BOUND" in phase2["blockers"]
    assert "REAL_ISAAC_EPISODE_LIFECYCLE_AND_CAPTURE_SOURCE_NOT_BOUND" not in phase2["blockers"]
    assert "REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND" in phase2["blockers"]
    assert "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING" not in phase2["blockers"]
    assert "REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING" in phase2["blockers"]
    assert "S4_ENTRY_GATE_FORMAL_V4_EVIDENCE_REPLAY_NOT_BOUND" not in phase2["blockers"]
    assert "TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET" in phase2["blockers"]
    assert "PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE" not in phase2["blockers"]


def test_current_s4_report_preserves_governance_and_s6_freeze() -> None:
    report = json.loads(REPORT.read_bytes())
    governance = report["governance"]
    assert governance == {
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "b0_changed": False,
        "production_safety_or_execution_gate_changed": False,
        "a3_contract_candidate_changed_under_adr0024": True,
        "existing_evidence_reinterpreted": False,
        "additional_collection_executed_after_batch_03": True,
        "scripted_public_physical_supervision_collection_executed": True,
        "training_executed": False,
        "phase2_physical_smoke_executed": False,
        "formal_q_b_evaluation_executed": False,
    }
    assert report["verification"]["s6_evaluation_manifest_sha256"] == _sha256(
        ROOT / "configs/m2c_s6_evaluation_keys.json"
    )
    assert report["verification"]["s6_and_entry_focused_tests"] == 36
    assert report["verification"]["s6_and_entry_focused_tests_passed"] is True

    directive = report["governing_directive"]
    assert _sha256(ROOT / directive["path"]) == directive["sha256"]
    assert directive["status"] == "ACCEPTED_HUMAN_DECISION"
    assert {item["selected_option"] for item in report["human_decisions_resolved"]} == {
        "A",
        "B",
    }
