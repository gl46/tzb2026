from __future__ import annotations

import hashlib

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopDecisionV1,
    M2BClosedLoopEpisodeV1,
)
from m2c.summarize_s6_matched import (
    EXPECTED_METHODS,
    paired_bootstrap_difference,
    summarize_s6,
)


def decision(key: str, method: str) -> M2BClosedLoopDecisionV1:
    model = method != "B0"
    digest = hashlib.sha256(f"{key}:{method}".encode()).hexdigest()
    return M2BClosedLoopDecisionV1(
        decision_id=f"{key}:{method}:decision-0",
        step_id=0,
        selected_skill="REOBSERVE",
        previous_failed_skill="GRASP",
        model_decision=model,
        mapping_status="VALID" if model else "NOT_APPLICABLE",
        ik_gate="NOT_APPLICABLE",
        collision_gate="NOT_APPLICABLE",
        safety_gate="PASS",
        execution_source=("MODEL_SELECTED_B0_SKILL" if model else "B0_BASELINE"),
        executed_skill="REOBSERVE",
        outcome="SUCCESS",
        registry_sha256=digest if model else None,
        model_checkpoint_sha256=digest if model else None,
        model_input_sha256=digest if model else None,
        model_output_sha256=digest if model else None,
        mapping_result_sha256=digest if model else None,
        gate_evidence_sha256=(
            {
                "ik": digest,
                "collision": digest,
                "safety": digest,
                "execution_outcome": digest,
            }
            if model
            else {}
        ),
    )


def episode(
    index: int,
    method: str,
    *,
    success: bool,
    violation: bool = False,
) -> M2BClosedLoopEpisodeV1:
    key = f"m2c-s6-key-{index:03d}"
    item = decision(key, method)
    if violation:
        item = item.model_copy(
            update={
                "outcome": "FAILURE",
                "collision_or_safety_violation": True,
            }
        )
        success = False
    return M2BClosedLoopEpisodeV1(
        episode_id=f"{key}:{method}",
        matched_key=key,
        method=method,
        scene_seed=20_000 + index,
        failure_type=("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")[index % 3],
        initial_success=False,
        final_success=success,
        recovery_attempted=True,
        recovery_success=success,
        retries=0,
        task_time_s=3.0,
        decisions=[item],
        collision_or_safety_violation=violation,
    )


def nonexecution_episode(index: int, method: str) -> M2BClosedLoopEpisodeV1:
    key = f"m2c-s6-key-{index:03d}"
    digest = hashlib.sha256(f"{key}:{method}:rejected".encode()).hexdigest()
    item = M2BClosedLoopDecisionV1(
        decision_id=f"{key}:{method}:decision-0",
        step_id=0,
        selected_skill="REOBSERVE",
        previous_failed_skill="GRASP",
        model_decision=True,
        mapping_status="REJECTED",
        ik_gate="NOT_RUN",
        collision_gate="NOT_RUN",
        safety_gate="REJECTED",
        execution_source="NONE",
        executed_skill=None,
        outcome="FAILURE",
        registry_sha256=digest,
        model_checkpoint_sha256=digest,
        model_input_sha256=digest,
        model_output_sha256=digest,
        mapping_result_sha256=digest,
    )
    return M2BClosedLoopEpisodeV1(
        episode_id=f"{key}:{method}",
        matched_key=key,
        method=method,
        scene_seed=20_000 + index,
        failure_type=("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")[index % 3],
        initial_success=False,
        final_success=False,
        recovery_attempted=False,
        recovery_success=None,
        retries=0,
        task_time_s=0.0,
        decisions=[item],
    )


def matched_episodes(count: int = 30) -> list[M2BClosedLoopEpisodeV1]:
    rows = []
    for index in range(count):
        for method in EXPECTED_METHODS:
            rows.append(
                episode(
                    index,
                    method,
                    success=(method != "B0"),
                )
            )
    return rows


def test_paired_bootstrap_is_deterministic_and_matched() -> None:
    first = paired_bootstrap_difference(
        [(True, False)] * 20,
        resamples=100,
        seed=7,
    )
    second = paired_bootstrap_difference(
        [(True, False)] * 20,
        resamples=100,
        seed=7,
    )
    assert first == second
    assert first["estimate"] == 1.0
    assert first["interval"] == [1.0, 1.0]


def test_s6_requires_four_methods_thirty_keys_and_fifty_executions() -> None:
    report = summarize_s6(
        matched_episodes(),
        bootstrap_resamples=100,
        bootstrap_seed=7,
    )
    assert report["formal_evaluation_ready"] is True
    assert report["complete_matched_keys"] == 30
    assert report["qrm_model_decisions_executed"] == 90
    assert report["primary_metric"]["name"] == "fc_gain_over_b0"
    assert report["primary_metric"]["estimate"] == 1.0
    assert report["collision_or_safety_violations"] == 0
    assert all(
        metrics["pure_model_success_episodes"]
        <= metrics["successful_episodes_with_any_model_decision"]
        for metrics in report["method_metrics"].values()
    )


def test_s6_fails_closed_below_key_gate_or_on_violation() -> None:
    below = summarize_s6(
        matched_episodes(29),
        bootstrap_resamples=20,
        bootstrap_seed=7,
    )
    assert below["formal_evaluation_ready"] is False
    assert "complete matched keys 29 < 30" in below["findings"]

    unsafe_rows = matched_episodes()
    unsafe_rows[-1] = episode(
        29,
        "QRM_COARSE_FC_MLP",
        success=False,
        violation=True,
    )
    unsafe = summarize_s6(
        unsafe_rows,
        bootstrap_resamples=20,
        bootstrap_seed=7,
    )
    assert unsafe["formal_evaluation_ready"] is False
    assert "collision or safety violations: 1" in unsafe["findings"]


def test_s6_rejects_execution_receipt_reuse_across_episodes() -> None:
    rows = matched_episodes()
    first = rows[1].decisions[0]
    second = rows[5].decisions[0]
    reused = first.gate_evidence_sha256["execution_outcome"]
    rows[5] = rows[5].model_copy(
        update={
            "decisions": [
                second.model_copy(
                    update={
                        "gate_evidence_sha256": {
                            **second.gate_evidence_sha256,
                            "execution_outcome": reused,
                        }
                    }
                )
            ]
        }
    )
    report = summarize_s6(
        rows,
        bootstrap_resamples=20,
        bootstrap_seed=7,
    )
    assert report["formal_evaluation_ready"] is False
    assert report["reused_execution_outcome_receipts"] == {
        reused: [rows[1].episode_id, rows[5].episode_id]
    }


def test_s6_requires_fifty_physically_executed_model_decisions() -> None:
    rows = matched_episodes()
    replacements = 41
    for offset, row in enumerate(rows):
        if replacements and row.method != "B0":
            rows[offset] = nonexecution_episode(
                row.scene_seed - 20_000,
                row.method,
            )
            replacements -= 1
    assert replacements == 0
    report = summarize_s6(
        rows,
        bootstrap_resamples=20,
        bootstrap_seed=7,
    )
    assert report["complete_matched_keys"] == 30
    assert report["qrm_model_decisions_executed"] == 49
    assert report["formal_evaluation_ready"] is False
    assert "physically executed model decisions 49 < 50" in report["findings"]
