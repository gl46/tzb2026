from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from m2c.audit_s4_training_eligibility_yield_adr0025 import (
    OFFLINE_REPLAY_SHA256,
    S4YieldAuditError,
    build_report,
    read_bound_json,
    render_markdown,
    verify_source_binding,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_yield_audit_replays_forty_six_unique_keys_and_zero_eligible() -> None:
    report = build_report(project_root=PROJECT_ROOT)

    assert report["status"] == "BLOCKED_ZERO_OBSERVED_ELIGIBLE_CHAIN_YIELD"
    audit_path = PROJECT_ROOT / report["audit_implementation"]["path"]
    assert (
        report["audit_implementation"]["sha256"]
        == hashlib.sha256(audit_path.read_bytes()).hexdigest()
    )
    assert report["identity_audit"] == {
        "attempt_rows": 47,
        "duplicate_attempt_rows_within_first_v3_report": 1,
        "source_identity_sets_pairwise_disjoint": True,
        "unique_v3_train_identities": 11,
        "unique_v4_train_identities": 35,
        "unique_train_identities_total": 46,
    }
    assert report["observed_yield"]["complete_eight_step_chains"] == 37
    assert report["observed_yield"]["eligible_training_episodes"] == 0
    assert report["observed_yield"]["eligible_yield_per_unique_train_identity"] == 0.0
    assert report["observed_yield"]["finite_key_projection_for_one_eligible_episode"] is None
    assert report["checkpoint_implication"]["s4_pure_model_success_episodes"] is None
    assert report["checkpoint_implication"]["pure_zero_claimed"] is False
    assert report["evidence_claims"]["training_performed"] is False
    assert report["evidence_claims"]["teacher_used"] is False


def test_complete_chain_taxonomy_and_episode_atomic_predicate_are_exact() -> None:
    report = build_report(project_root=PROJECT_ROOT)

    assert report["complete_chain_failure_taxonomy"] == {
        "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED": 1,
        "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED": 25,
        "TERMINAL_PREGRASP_IK_GATE_REJECTED": 11,
    }
    predicate = report["frozen_training_predicate"]
    assert predicate["final_task_success_required"] is True
    assert predicate["exact_step_count_required"] == 8
    assert predicate["failed_episode_emits_intermediate_training_rows"] is False
    assert predicate["minimum_code_level_eligible_episode_count"] == 1
    assert predicate["predicate_changed_by_this_audit"] is False


def test_scene19083_schema_replay_does_not_reinterpret_physical_failure() -> None:
    report = build_report(project_root=PROJECT_ROOT)

    replay = report["scene_19083_offline_replay"]
    assert replay["sha256"] == OFFLINE_REPLAY_SHA256
    assert replay["schema_upgrade_passed"] is True
    assert replay["source_final_task_success"] is False
    assert replay["replayed_final_task_success"] is False
    assert replay["training_sample_eligible"] is False
    assert replay["offline_dataset_sample_count"] == 0
    assert replay["terminal_execution_status"] == "CONTACT_GATE_REJECTED"


def test_bound_report_tamper_is_rejected(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "reports/m2c-s4-v4-scene19083-offline-raw-capacity-replay.json"
    value = json.loads(source.read_text())
    value["unchanged_outcome"]["training_sample_eligible"] = True
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(value, sort_keys=True) + "\n")

    with pytest.raises(S4YieldAuditError, match="SHA-256"):
        read_bound_json(
            tampered,
            expected_sha256=OFFLINE_REPLAY_SHA256,
            label="tampered offline replay",
        )


def test_eligibility_source_drift_is_rejected(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "src/xh_agent/policy/qrm_lite/path_blocked_collection_v4.py"
    copied = tmp_path / "path_blocked_collection_v4.py"
    copied.write_bytes(source.read_bytes() + b"\n# drift\n")

    with pytest.raises(S4YieldAuditError, match="SHA-256"):
        verify_source_binding(
            copied,
            expected_sha256="467ce96ea2b5db7b84904bbe489e4436f43f82587acefbb56027bd927119216c",
            markers=(),
        )


def test_markdown_does_not_claim_measured_model_zero() -> None:
    markdown = render_markdown(build_report(project_root=PROJECT_ROOT))

    assert "0/46 = 0.0" in markdown
    assert "0/37 = 0.0" in markdown
    assert "pure model success remains `null`" in markdown
    assert "does not change that predicate, B0, a safety gate, or a threshold" in markdown
