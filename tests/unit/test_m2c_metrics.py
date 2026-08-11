from __future__ import annotations

import pytest

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopDecisionV1,
    M2BClosedLoopEpisodeV1,
    b0_headroom,
    fc_gain_over_b0,
    model_owned_decision_ratio,
    pure_model_success_episode,
    pure_model_success_exclusion_reasons,
    summarize_method,
)


def decision(step: int, source: str) -> M2BClosedLoopDecisionV1:
    model = source != "B0_BASELINE"
    digest = "a" * 64
    return M2BClosedLoopDecisionV1(
        decision_id=f"decision-{step}-{source}",
        step_id=step,
        selected_skill="REOBSERVE",
        previous_failed_skill="GRASP",
        model_decision=model,
        mapping_status="VALID" if model else "NOT_APPLICABLE",
        ik_gate="NOT_APPLICABLE",
        collision_gate="NOT_APPLICABLE",
        safety_gate="PASS",
        execution_source=source,
        executed_skill="REOBSERVE",
        outcome="SUCCESS" if step else "UNKNOWN",
        registry_sha256=digest if model else None,
        model_checkpoint_sha256=digest if model else None,
        model_input_sha256=digest if model else None,
        model_output_sha256=digest if model else None,
        mapping_result_sha256=digest if model else None,
        gate_evidence_sha256=(
            {"ik": digest, "collision": digest, "safety": digest}
            if model
            else {}
        ),
    )


def episode(decisions: list[M2BClosedLoopDecisionV1]) -> M2BClosedLoopEpisodeV1:
    return M2BClosedLoopEpisodeV1(
        episode_id="m2c-pure-model",
        matched_key="m2c-key",
        method="QRM_COARSE_FC",
        scene_seed=7001,
        failure_type="COMPOUND_FAILURE",
        initial_success=False,
        final_success=True,
        recovery_attempted=True,
        recovery_success=True,
        retries=0,
        task_time_s=5.0,
        decisions=decisions,
    )


def test_pure_model_success_requires_every_recovery_decision_to_be_model_owned() -> None:
    model_only = episode(
        [
            decision(0, "MODEL_SELECTED_B0_SKILL"),
            decision(1, "MODEL_SELECTED_B0_SKILL"),
        ]
    )
    assert pure_model_success_episode(model_only) is True

    with_b0_continuation = episode(
        [
            decision(0, "MODEL_SELECTED_B0_SKILL"),
            decision(1, "B0_BASELINE"),
        ]
    )
    assert pure_model_success_episode(with_b0_continuation) is False
    assert any(
        reason.endswith(":FIXED_B0_CONTINUATION")
        for reason in pure_model_success_exclusion_reasons(
            with_b0_continuation
        )
    )

    metrics = summarize_method([model_only, with_b0_continuation])
    assert metrics["successful_episodes_with_any_model_decision"] == 2
    assert metrics["pure_model_success_episodes"] == 1
    assert len(metrics["pure_model_success_exclusions"]) == 1


def test_pure_model_success_requires_final_task_success() -> None:
    failed = episode([decision(0, "MODEL_SELECTED_B0_SKILL")]).model_copy(
        update={"final_success": False, "recovery_success": False}
    )
    assert pure_model_success_episode(failed) is False


def test_headroom_gain_and_model_owned_ratio_are_frozen() -> None:
    assert b0_headroom(0.75) == pytest.approx(0.25)
    assert fc_gain_over_b0(0.9, 0.75) == pytest.approx(0.15)
    decisions = [
        decision(0, "MODEL_SELECTED_B0_SKILL"),
        decision(1, "MODEL_SELECTED_B0_SKILL"),
        decision(2, "B0_BASELINE"),
    ]
    assert model_owned_decision_ratio(decisions) == pytest.approx(2 / 3)
    assert model_owned_decision_ratio([]) is None


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_headroom_rejects_invalid_rates(value: float) -> None:
    with pytest.raises(ValueError, match="finite rate"):
        b0_headroom(value)
