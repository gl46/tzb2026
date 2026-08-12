from __future__ import annotations

from datetime import datetime

import pytest

from xh_agent.policy.qrm_lite.m2c_stage_route import (
    M2CStageRoute,
    QAState,
    QBState,
    evaluate_stage_route,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def route(
    when: str,
    *,
    qa: QAState = QAState.PASSED,
    qb: QBState = QBState.UNMEASURED,
    pure: int | None = None,
    d2: bool = False,
    s5: bool = False,
    s6: bool = False,
    final: bool = False,
    s3: bool = True,
):
    return evaluate_stage_route(
        observed_at=at(when),
        q_a_state=qa,
        q_b_state=qb,
        d2_claimed=d2,
        s5_verified=s5,
        s6_verified=s6,
        final_verification_passed=final,
        pure_model_success_episodes=pure,
        s3_verified=s3,
    )


def test_current_q_a_pass_and_unmeasured_q_b_is_not_d1_or_d2() -> None:
    result = route("2026-08-13T12:00:00+08:00")
    assert result.route is M2CStageRoute.S4_IN_PROGRESS_UNMEASURED
    assert result.d1_triggered is False
    assert result.d2_triggered is False
    assert result.pure_model_success_episodes is None


def test_q_a_pass_does_not_authorize_q_b_before_s3_verification() -> None:
    result = route("2026-08-13T12:00:00+08:00", s3=False)
    assert result.route is M2CStageRoute.S4_IN_PROGRESS_UNMEASURED
    assert result.d1_triggered is False
    assert any("S3" in blocker for blocker in result.blockers)


def test_final_candidate_nonpass_triggers_d1_and_skips_s3_to_s5() -> None:
    result = route(
        "2026-08-13T12:00:00+08:00",
        qa=QAState.FINAL_CANDIDATE_NONPASS,
    )
    assert result.route is M2CStageRoute.D1_FINAL_CANDIDATE_NONPASS
    assert result.d1_triggered is True
    assert result.s3_required is False
    assert result.s4_required is False
    assert result.s5_required is False


def test_unmeasured_q_a_only_deadline_routes_to_d1() -> None:
    before = route(
        "2026-08-17T23:59:59+08:00",
        qa=QAState.UNMEASURED_OR_INVALID,
    )
    after = route(
        "2026-08-18T00:00:00+08:00",
        qa=QAState.UNMEASURED_OR_INVALID,
    )
    assert before.route is M2CStageRoute.S2_IN_PROGRESS_UNMEASURED
    assert before.d1_triggered is False
    assert after.route is M2CStageRoute.D1_S2_DEADLINE_UNMEASURED
    assert after.d1_triggered is True


def test_zero_eligible_or_missing_evaluation_never_becomes_d2() -> None:
    result = route("2026-08-27T00:00:00+08:00", pure=None)
    assert result.route is M2CStageRoute.S4_DEADLINE_BLOCKED_UNMEASURED
    assert result.d2_triggered is False
    assert result.pure_model_success_episodes is None


def test_measured_zero_cannot_trigger_d2_before_checkpoint() -> None:
    result = route(
        "2026-08-25T23:59:59+08:00",
        qb=QBState.MEASURED_ZERO,
        pure=0,
        d2=True,
    )
    assert result.route is M2CStageRoute.INVALID_PREMATURE_D2
    assert result.d2_triggered is False


def test_measured_zero_can_trigger_d2_at_checkpoint_and_skips_s5() -> None:
    result = route(
        "2026-08-26T00:00:00+08:00",
        qb=QBState.MEASURED_ZERO,
        pure=0,
        d2=True,
    )
    assert result.route is M2CStageRoute.D2_MEASURED_ZERO
    assert result.d2_triggered is True
    assert result.s5_required is False


def test_measured_zero_at_checkpoint_without_disposition_is_not_unmeasured() -> None:
    result = route(
        "2026-08-26T00:00:00+08:00",
        qb=QBState.MEASURED_ZERO,
        pure=0,
    )
    assert result.route is M2CStageRoute.S4_DEADLINE_MEASURED_ZERO_AWAITING_D2
    assert result.pure_model_success_episodes == 0
    assert result.d2_triggered is False


def test_positive_pure_requires_s5_then_s6_and_final_evidence() -> None:
    s5_pending = route(
        "2026-08-24T00:00:00+08:00",
        qb=QBState.MEASURED_POSITIVE,
        pure=1,
    )
    s6_pending = route(
        "2026-08-29T00:00:00+08:00",
        qb=QBState.MEASURED_POSITIVE,
        pure=1,
        s5=True,
    )
    complete = route(
        "2026-09-02T00:00:00+08:00",
        qb=QBState.MEASURED_POSITIVE,
        pure=1,
        s5=True,
        s6=True,
        final=True,
    )
    assert s5_pending.route is M2CStageRoute.S5_REQUIRED_AFTER_Q_B_PASS
    assert s6_pending.route is M2CStageRoute.S6_IN_PROGRESS_AFTER_S5
    assert complete.route is M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE


def test_verified_d1_and_d2_routes_can_only_finish_after_s6_and_s7() -> None:
    d1_pending = route(
        "2026-08-19T00:00:00+08:00",
        qa=QAState.FINAL_CANDIDATE_NONPASS,
    )
    d1_complete = route(
        "2026-09-02T00:00:00+08:00",
        qa=QAState.FINAL_CANDIDATE_NONPASS,
        s6=True,
        final=True,
    )
    d2_complete = route(
        "2026-09-02T00:00:00+08:00",
        qb=QBState.MEASURED_ZERO,
        pure=0,
        d2=True,
        s6=True,
        final=True,
    )
    assert d1_pending.route is M2CStageRoute.D1_FINAL_CANDIDATE_NONPASS
    assert d1_complete.route is M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE
    assert d1_complete.d1_triggered is True
    assert d2_complete.route is M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE
    assert d2_complete.d2_triggered is True


def test_deadline_routes_never_convert_missing_evidence_into_measured_failure() -> None:
    s5_missing = route(
        "2026-08-29T00:00:00+08:00",
        qb=QBState.MEASURED_POSITIVE,
        pure=1,
    )
    s6_missing = route(
        "2026-09-01T00:00:00+08:00",
        qb=QBState.MEASURED_POSITIVE,
        pure=1,
        s5=True,
    )
    assert s5_missing.route is M2CStageRoute.S5_DEADLINE_BLOCKED_UNMEASURED
    assert s6_missing.route is M2CStageRoute.S6_HARD_FREEZE_BLOCKED_UNMEASURED
    assert s5_missing.d2_triggered is False
    assert s6_missing.d2_triggered is False


@pytest.mark.parametrize(
    ("qb", "pure"),
    [
        (QBState.UNMEASURED, 0),
        (QBState.MEASURED_ZERO, None),
        (QBState.MEASURED_ZERO, 1),
        (QBState.MEASURED_POSITIVE, 0),
        (QBState.MEASURED_POSITIVE, None),
    ],
)
def test_q_b_measurement_state_and_count_are_mutually_consistent(
    qb: QBState,
    pure: int | None,
) -> None:
    with pytest.raises(ValueError):
        route("2026-08-26T00:00:00+08:00", qb=qb, pure=pure)
