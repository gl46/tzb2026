from __future__ import annotations

import pytest

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopDecisionV1,
    M2BClosedLoopEpisodeV1,
    summarize_matched,
    summarize_method,
)


def _decision(
    *,
    model: bool,
    source: str,
    outcome: str = "SUCCESS",
) -> M2BClosedLoopDecisionV1:
    fallback = source == "B0_FALLBACK"
    baseline = source == "B0_BASELINE"
    return M2BClosedLoopDecisionV1(
        decision_id=f"decision-{source}",
        step_id=0,
        selected_skill="REOBSERVE",
        previous_failed_skill="GRASP",
        model_decision=model,
        mapping_status=(
            "NOT_APPLICABLE" if baseline else "REJECTED" if fallback else "VALID"
        ),
        ik_gate="NOT_APPLICABLE" if not fallback else "NOT_RUN",
        collision_gate="NOT_APPLICABLE" if not fallback else "NOT_RUN",
        safety_gate="PASS" if not fallback else "REJECTED",
        execution_source=source,
        executed_skill="REOBSERVE",
        fallback_reason="SAFETY_REJECTION" if fallback else None,
        outcome=outcome,
    )


def _episode(
    key: str,
    method: str,
    decision: M2BClosedLoopDecisionV1,
    *,
    final_success: bool = True,
) -> M2BClosedLoopEpisodeV1:
    return M2BClosedLoopEpisodeV1(
        episode_id=f"{key}-{method}",
        matched_key=key,
        method=method,
        scene_seed=int(key.split("-")[-1]),
        failure_type="EMPTY_GRASP",
        initial_success=False,
        final_success=final_success,
        recovery_attempted=True,
        recovery_success=final_success,
        retries=1,
        task_time_s=2.0,
        decisions=[decision],
    )


def test_model_execution_requires_valid_complete_gates() -> None:
    with pytest.raises(ValueError, match="completed passing gates"):
        M2BClosedLoopDecisionV1(
            decision_id="bad-model-execution",
            step_id=0,
            selected_skill="REOBSERVE",
            model_decision=True,
            mapping_status="VALID",
            ik_gate="NOT_RUN",
            collision_gate="NOT_APPLICABLE",
            safety_gate="PASS",
            execution_source="MODEL_SELECTED_B0_SKILL",
            executed_skill="REOBSERVE",
        )


def test_fallback_success_is_system_success_not_model_success() -> None:
    episode = _episode(
        "scene-5000",
        "QRM_COARSE_FC",
        _decision(model=True, source="B0_FALLBACK"),
    )
    metrics = summarize_method([episode])
    assert metrics["final_task_success_rate"] == 1.0
    assert metrics["system_success_with_b0_fallback"] == 1
    assert metrics["model_success_episodes"] == 0
    assert metrics["model_decisions_executed"] == 0
    assert metrics["model_decisions_fallback"] == 1


def test_matched_gate_requires_twenty_real_model_executions() -> None:
    episodes = []
    for seed in range(5000, 5010):
        key = f"scene-{seed}"
        episodes.extend(
            [
                _episode(
                    key,
                    "B0",
                    _decision(model=False, source="B0_BASELINE"),
                ),
                _episode(
                    key,
                    "QRM_COARSE_NO_FC",
                    _decision(
                        model=True, source="MODEL_SELECTED_B0_SKILL"
                    ),
                ),
                _episode(
                    key,
                    "QRM_COARSE_FC",
                    _decision(
                        model=True, source="MODEL_SELECTED_B0_SKILL"
                    ),
                ),
            ]
        )
    report = summarize_matched(
        episodes,
        expected_methods=("B0", "QRM_COARSE_NO_FC", "QRM_COARSE_FC"),
    )
    assert report["formal_evaluation_ready"] is True
    assert report["qrm_model_decisions_executed"] == 20
    assert report["episodes"] == 30


def test_matched_gate_reports_missing_method() -> None:
    episodes = [
        _episode(
            "scene-5000",
            "B0",
            _decision(model=False, source="B0_BASELINE"),
        )
    ]
    report = summarize_matched(
        episodes,
        expected_methods=("B0", "QRM_COARSE_FC"),
    )
    assert report["formal_evaluation_ready"] is False
    assert report["findings"] == [
        "scene-5000: missing methods ['QRM_COARSE_FC']"
    ]
