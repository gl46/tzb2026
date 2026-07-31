from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from m2b.run_matched_closed_loop_batch import (
    baseline_episode,
    injection_is_valid,
    matched_key,
    matched_pairs,
    qrm_execution_episode,
    qrm_nonexecution_episode,
    run_or_load_execution,
    validate_journal_episode,
)
from xh_agent.policy.qrm_lite.closed_loop_metrics import summarize_method
from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    PhysicalRuntimeGateReceiptV1,
)
from xh_agent.policy.qrm_lite.prospective_mapping import (
    M2BProspectiveRuntimeDecisionV1,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    RuntimeSkillRequestV1,
    load_registry,
    validate_runtime_mapping,
)


ROOT = Path(__file__).parents[2]
REGISTRY_PATH = ROOT / "configs/qrm_runtime_mapping.yaml"
REGISTRY = load_registry(REGISTRY_PATH)
DIGEST = "a" * 64


def prospective(*, rejected: bool = False) -> M2BProspectiveRuntimeDecisionV1:
    request = RuntimeSkillRequestV1(
        model_class_id="coarse.recovery.REOBSERVE",
        skill="REOBSERVE",
        task_target_track_id="track-1",
        available_track_ids=["track-1"],
        coordinate_frame="policy_rgbd_optical",
        units="none",
        current_phase="RECOVERY",
        confidence=0.9,
    )
    mapping = validate_runtime_mapping(
        request,
        REGISTRY,
        ik_check=lambda _action, _parameters: (True, None),
        collision_check=lambda _action, _parameters: (True, None),
        safety_check=(
            (lambda _action, _parameters: (False, "blocked"))
            if rejected
            else (lambda _action, _parameters: (True, None))
        ),
    )
    mapping_sha256 = hashlib.sha256(
        mapping.model_dump_json().encode()
    ).hexdigest()
    return M2BProspectiveRuntimeDecisionV1(
        decision_id="prospective-sample-1",
        sample_id="episode-1:coarse-recovery-0",
        failure_type="EMPTY_GRASP",
        request=request,
        mapping=mapping,
        ik_gate="PASS",
        collision_gate="PASS",
        safety_gate="REJECTED" if rejected else "PASS",
        registry_sha256=hashlib.sha256(
            REGISTRY_PATH.read_bytes()
        ).hexdigest(),
        model_checkpoint_sha256="b" * 64,
        model_input_sha256="c" * 64,
        model_output_sha256="d" * 64,
        request_sha256="e" * 64,
        structural_mapping_result_sha256="f" * 64,
        mapping_result_sha256=mapping_sha256,
        source_hashes={"scene.sdf": DIGEST},
        isolated_preflight_evidence_path="/evidence/preflight.json",
        isolated_preflight_evidence_sha256="9" * 64,
        prospective_planning_check=True,
        isolated_from_evaluation_rollout=True,
        evaluation_execution_started=False,
    )


def receipt(*, success: bool = True) -> PhysicalRuntimeGateReceiptV1:
    return PhysicalRuntimeGateReceiptV1(
        failure_type="EMPTY_GRASP",
        recovery_skill="REOBSERVE",
        runtime_action="HOLD_AND_CAPTURE_PUBLIC_RGBD",
        ik_gate="NOT_APPLICABLE",
        collision_gate="NOT_APPLICABLE",
        safety_gate="PASS",
        physical_recovery_success=success,
        details={"source": "TEST_PHYSICAL_EXECUTION"},
    )


def test_matched_selection_round_robins_all_failure_classes() -> None:
    base = prospective()
    failures = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
    no_fc = {
        f"episode-{index}:coarse-recovery-0": base.model_copy(
            update={
                "sample_id": f"episode-{index}:coarse-recovery-0",
                "failure_type": failure,
            }
        )
        for index, failure in enumerate(failures)
    }
    fc = {
        sample_id: item.model_copy(
            update={"model_checkpoint_sha256": "8" * 64}
        )
        for sample_id, item in no_fc.items()
    }
    selected = matched_pairs(no_fc, fc, max_keys=3)
    assert {pair[0].failure_type for pair in selected} == set(failures)


def test_matched_selection_rejects_different_adapter_samples() -> None:
    record = prospective()
    with pytest.raises(ValueError, match="held-out samples differ"):
        matched_pairs(
            {record.sample_id: record},
            {},
            max_keys=1,
        )


def test_matched_key_binds_scene_sources() -> None:
    first = matched_key(
        sample_id="sample-1",
        scene_seed=4000,
        failure_type="EMPTY_GRASP",
        source_hashes={"scene.sdf": "a" * 64},
    )
    second = matched_key(
        sample_id="sample-1",
        scene_seed=4000,
        failure_type="EMPTY_GRASP",
        source_hashes={"scene.sdf": "b" * 64},
    )
    assert first != second


def test_qrm_execution_records_fixed_continuation_separately() -> None:
    episode = qrm_execution_episode(
        key="m2b-match-1",
        method="QRM_COARSE_FC",
        scene_seed=4000,
        failure_type="EMPTY_GRASP",
        recovery_sequence=["REOBSERVE", "REGRASP"],
        previous_failed_skill="GRASP",
        prospective=prospective(),
        receipt=receipt(),
        execution_evidence_sha256="7" * 64,
        elapsed_s=3.0,
    )
    assert episode.decisions[0].execution_source == "MODEL_SELECTED_B0_SKILL"
    assert episode.decisions[0].outcome == "UNKNOWN"
    assert episode.decisions[1].execution_source == "B0_BASELINE"
    metrics = summarize_method([episode])
    assert metrics["model_decisions_executed"] == 1
    assert metrics["model_success_episodes"] == 0
    assert metrics["system_success_with_non_model_continuation"] == 1


def test_baseline_and_rejected_model_attribution_remain_separate() -> None:
    baseline = baseline_episode(
        key="m2b-match-1",
        scene_seed=4000,
        failure_type="EMPTY_GRASP",
        recovery_sequence=["REOBSERVE", "REGRASP"],
        previous_failed_skill="GRASP",
        receipt=receipt(),
        evidence_sha256="7" * 64,
        elapsed_s=3.0,
    )
    assert all(not item.model_decision for item in baseline.decisions)
    rejected = qrm_nonexecution_episode(
        key="m2b-match-1",
        method="QRM_COARSE_NO_FC",
        scene_seed=4000,
        failure_type="EMPTY_GRASP",
        previous_failed_skill="GRASP",
        prospective=prospective(rejected=True),
    )
    assert rejected.recovery_attempted is False
    assert rejected.decisions[0].execution_source == "NONE"


def test_injection_must_be_physically_established() -> None:
    payload = {
        "m2b_injection_pass": True,
        "m2b_empty_grasp_injection": {"training_eligible": True},
    }
    assert injection_is_valid(payload, "EMPTY_GRASP") is True
    payload["m2b_empty_grasp_injection"]["training_eligible"] = False
    assert injection_is_valid(payload, "EMPTY_GRASP") is False


def test_execution_journal_binds_episode_outcome_evidence() -> None:
    episode = qrm_execution_episode(
        key="m2b-match-1",
        method="QRM_COARSE_FC",
        scene_seed=4000,
        failure_type="EMPTY_GRASP",
        recovery_sequence=["REOBSERVE"],
        previous_failed_skill="GRASP",
        prospective=prospective(),
        receipt=receipt(),
        execution_evidence_sha256="7" * 64,
        elapsed_s=3.0,
    )
    journal = {
        "schema_version": "M2BClosedLoopExecutionJournalV1",
        "episode_id": episode.episode_id,
        "method": episode.method,
        "matched_key": episode.matched_key,
        "status": "EVALUATION_EXECUTION_RECORDED",
        "execution_evidence_path": "/evidence/eval.json",
        "execution_evidence_sha256": "7" * 64,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    validate_journal_episode(journal, episode)
    journal["execution_evidence_sha256"] = "6" * 64
    with pytest.raises(ValueError, match="not bound"):
        validate_journal_episode(journal, episode)


def test_execution_loader_verifies_root_sources_and_physical_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_hashes = {"scene.sdf": "a" * 64}
    evidence_path = "/runs/eval/empty/attempt-01/actuation-probe.json"
    payload = {
        "source_hashes": source_hashes,
        "m2b_injection_pass": True,
        "m2b_empty_grasp_injection": {"training_eligible": True},
        "m2b_public_rgbd": {
            "simulator_truth_policy_input": False,
            "captures": [{"label": "empty_grasp_reobserve"}],
        },
        "m2b_recovery": {
            "empty_grasp": {"training_eligible": True}
        },
    }
    raw = json.dumps(payload).encode()
    monkeypatch.setattr(
        "m2b.run_matched_closed_loop_batch.remote_exists",
        lambda _host, _path: True,
    )
    monkeypatch.setattr(
        "m2b.run_matched_closed_loop_batch.remote_json",
        lambda _host, _path: {
            "attempts": [{"evidence": evidence_path, "elapsed_s": 2.5}]
        },
    )
    monkeypatch.setattr(
        "m2b.run_matched_closed_loop_batch.remote_bytes",
        lambda _host, path: raw if path == evidence_path else b"",
    )
    loaded, path, digest, elapsed_s, returncode = run_or_load_execution(
        host="isaac",
        command=["python3", "runner.py"],
        summary_path="/runs/eval/physical-failure-smoke.json",
        failure_type="EMPTY_GRASP",
        expected_runtime_action="HOLD_AND_CAPTURE_PUBLIC_RGBD",
        expected_source_hashes=source_hashes,
    )
    assert loaded.physical_recovery_success is True
    assert path == evidence_path
    assert digest == hashlib.sha256(raw).hexdigest()
    assert elapsed_s == 2.5
    assert returncode == 0


def test_execution_loader_rejects_evidence_outside_run_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "m2b.run_matched_closed_loop_batch.remote_exists",
        lambda _host, _path: True,
    )
    monkeypatch.setattr(
        "m2b.run_matched_closed_loop_batch.remote_json",
        lambda _host, _path: {
            "attempts": [{"evidence": "/other/evidence.json"}]
        },
    )
    with pytest.raises(ValueError, match="escapes"):
        run_or_load_execution(
            host="isaac",
            command=["python3", "runner.py"],
            summary_path="/runs/eval/physical-failure-smoke.json",
            failure_type="EMPTY_GRASP",
            expected_runtime_action="HOLD_AND_CAPTURE_PUBLIC_RGBD",
            expected_source_hashes={"scene.sdf": "a" * 64},
        )
