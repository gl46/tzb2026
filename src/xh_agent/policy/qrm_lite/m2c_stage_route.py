"""Deadline-aware, fail-closed stage routing for the M2C goal.

The route reducer keeps three facts separate:

* a Q-A domain result,
* a measured Q-B result, and
* the absence of a Q-B measurement.

In particular, zero eligible training rows or a missing formal evaluation is
never converted into ``pure_model_success_episodes == 0``.  D2 is a measured
zero disposition and is not available before the frozen S4 checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


M2C_TIMEZONE_NAME = "Asia/Shanghai"
S2_DEADLINE_LOCAL_ISO = "2026-08-18T00:00:00+08:00"
S4_DEADLINE_LOCAL_ISO = "2026-08-26T00:00:00+08:00"
S5_DEADLINE_LOCAL_ISO = "2026-08-29T00:00:00+08:00"
S6_HARD_FREEZE_LOCAL_ISO = "2026-09-01T00:00:00+08:00"


class QAState(str, Enum):
    UNMEASURED_OR_INVALID = "UNMEASURED_OR_INVALID"
    FINAL_CANDIDATE_NONPASS = "FINAL_CANDIDATE_NONPASS"
    PASSED = "PASSED"


class QBState(str, Enum):
    UNMEASURED = "UNMEASURED"
    MEASURED_ZERO = "MEASURED_ZERO"
    MEASURED_POSITIVE = "MEASURED_POSITIVE"


class M2CStageRoute(str, Enum):
    S2_IN_PROGRESS_UNMEASURED = "S2_IN_PROGRESS_UNMEASURED"
    D1_FINAL_CANDIDATE_NONPASS = "D1_FINAL_CANDIDATE_NONPASS"
    D1_S2_DEADLINE_UNMEASURED = "D1_S2_DEADLINE_UNMEASURED"
    S4_IN_PROGRESS_UNMEASURED = "S4_IN_PROGRESS_UNMEASURED"
    S4_DEADLINE_BLOCKED_UNMEASURED = "S4_DEADLINE_BLOCKED_UNMEASURED"
    S4_MEASURED_ZERO_CONTINUE_BEFORE_DEADLINE = "S4_MEASURED_ZERO_CONTINUE_BEFORE_DEADLINE"
    S4_DEADLINE_MEASURED_ZERO_AWAITING_D2 = "S4_DEADLINE_MEASURED_ZERO_AWAITING_D2"
    INVALID_PREMATURE_D2 = "INVALID_PREMATURE_D2"
    D2_MEASURED_ZERO = "D2_MEASURED_ZERO"
    S5_REQUIRED_AFTER_Q_B_PASS = "S5_REQUIRED_AFTER_Q_B_PASS"
    S5_DEADLINE_BLOCKED_UNMEASURED = "S5_DEADLINE_BLOCKED_UNMEASURED"
    S6_IN_PROGRESS_AFTER_S5 = "S6_IN_PROGRESS_AFTER_S5"
    S6_HARD_FREEZE_BLOCKED_UNMEASURED = "S6_HARD_FREEZE_BLOCKED_UNMEASURED"
    S7_REQUIRED_AFTER_D1 = "S7_REQUIRED_AFTER_D1"
    S7_REQUIRED_AFTER_D2 = "S7_REQUIRED_AFTER_D2"
    S7_REQUIRED_AFTER_S5 = "S7_REQUIRED_AFTER_S5"
    TERMINAL_EVIDENCE_COMPLETE = "TERMINAL_EVIDENCE_COMPLETE"


@dataclass(frozen=True)
class M2CStageRouteDecision:
    route: M2CStageRoute
    observed_at: str
    d1_triggered: bool
    d2_triggered: bool
    s3_required: bool
    s4_required: bool
    s5_required: bool
    s6_required: bool
    pure_model_success_episodes: int | None
    blockers: tuple[str, ...]


def _checkpoints() -> tuple[ZoneInfo, datetime, datetime, datetime, datetime]:
    try:
        timezone = ZoneInfo(M2C_TIMEZONE_NAME)
    except ZoneInfoNotFoundError as error:
        raise ValueError("M2C stage route requires Asia/Shanghai timezone data") from error
    except Exception as error:
        raise ValueError("M2C stage route requires Asia/Shanghai timezone data") from error
    values = tuple(
        datetime.fromisoformat(value).astimezone(timezone)
        for value in (
            S2_DEADLINE_LOCAL_ISO,
            S4_DEADLINE_LOCAL_ISO,
            S5_DEADLINE_LOCAL_ISO,
            S6_HARD_FREEZE_LOCAL_ISO,
        )
    )
    if tuple(value.isoformat() for value in values) != (
        S2_DEADLINE_LOCAL_ISO,
        S4_DEADLINE_LOCAL_ISO,
        S5_DEADLINE_LOCAL_ISO,
        S6_HARD_FREEZE_LOCAL_ISO,
    ):
        raise ValueError("M2C stage checkpoint timezone/offset changed")
    return timezone, *values


def observe_stage_time() -> datetime:
    """Read the production wall clock once and normalize it to Shanghai."""

    timezone, *_ = _checkpoints()
    observed_ns = time.time_ns()
    if type(observed_ns) is not int or observed_ns <= 0:
        raise ValueError("M2C stage route requires a positive integer system clock")
    seconds, nanoseconds = divmod(observed_ns, 1_000_000_000)
    observed = datetime.fromtimestamp(seconds, tz=timezone).replace(
        microsecond=nanoseconds // 1_000
    )
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("M2C stage route requires a timezone-aware system clock")
    return observed


def evaluate_stage_route(
    *,
    observed_at: datetime,
    q_a_state: QAState,
    q_b_state: QBState,
    d2_claimed: bool,
    s5_verified: bool,
    s6_verified: bool,
    final_verification_passed: bool,
    pure_model_success_episodes: int | None,
    s3_verified: bool = False,
) -> M2CStageRouteDecision:
    """Reduce verified stage evidence into one mutually exclusive goal route."""

    timezone, s2_deadline, s4_deadline, s5_deadline, hard_freeze = _checkpoints()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("M2C route timestamp must be timezone-aware")
    observed = observed_at.astimezone(timezone)
    if q_b_state is QBState.UNMEASURED:
        if pure_model_success_episodes is not None:
            raise ValueError("unmeasured Q-B state may not carry a pure-model count")
    elif q_b_state is QBState.MEASURED_ZERO:
        if pure_model_success_episodes != 0:
            raise ValueError("measured-zero Q-B state must carry pure-model count zero")
    elif pure_model_success_episodes is None or pure_model_success_episodes < 1:
        raise ValueError("positive Q-B state requires at least one pure-model success")

    def decision(
        route: M2CStageRoute,
        *,
        d1: bool = False,
        d2: bool = False,
        s3_required: bool = True,
        s4_required: bool = True,
        s5_required: bool = True,
        blockers: tuple[str, ...] = (),
    ) -> M2CStageRouteDecision:
        return M2CStageRouteDecision(
            route=route,
            observed_at=observed.isoformat(),
            d1_triggered=d1,
            d2_triggered=d2,
            s3_required=s3_required,
            s4_required=s4_required,
            s5_required=s5_required,
            s6_required=True,
            pure_model_success_episodes=pure_model_success_episodes,
            blockers=blockers,
        )

    if q_a_state is QAState.FINAL_CANDIDATE_NONPASS:
        if s6_verified and final_verification_passed:
            return decision(
                M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE,
                d1=True,
                s3_required=False,
                s4_required=False,
                s5_required=False,
            )
        return decision(
            (
                M2CStageRoute.S7_REQUIRED_AFTER_D1
                if s6_verified
                else M2CStageRoute.D1_FINAL_CANDIDATE_NONPASS
            ),
            d1=True,
            s3_required=False,
            s4_required=False,
            s5_required=False,
            blockers=("the final S2 candidate did not pass Q-A; D1 requires S6 and S7 evidence",),
        )
    if q_a_state is QAState.UNMEASURED_OR_INVALID:
        if observed < s2_deadline:
            return decision(
                M2CStageRoute.S2_IN_PROGRESS_UNMEASURED,
                blockers=("Q-A remains unmeasured before the frozen S2 deadline",),
            )
        if s6_verified and final_verification_passed:
            return decision(
                M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE,
                d1=True,
                s3_required=False,
                s4_required=False,
                s5_required=False,
            )
        return decision(
            (
                M2CStageRoute.S7_REQUIRED_AFTER_D1
                if s6_verified
                else M2CStageRoute.D1_S2_DEADLINE_UNMEASURED
            ),
            d1=True,
            s3_required=False,
            s4_required=False,
            s5_required=False,
            blockers=("S2 deadline passed without a verified Q-A headroom/recoverability result",),
        )

    # A Q-A pass is mutually exclusive with D1.  Missing/zero Q-B evidence is
    # classified only after this point.
    if not s3_verified:
        return decision(
            M2CStageRoute.S4_IN_PROGRESS_UNMEASURED,
            blockers=("S3 full class-coverage evidence is absent or failing",),
        )
    if q_b_state is QBState.UNMEASURED:
        if d2_claimed:
            return decision(
                M2CStageRoute.INVALID_PREMATURE_D2,
                blockers=("D2 cannot be claimed when pure-model success is unmeasured",),
            )
        return decision(
            (
                M2CStageRoute.S4_IN_PROGRESS_UNMEASURED
                if observed < s4_deadline
                else M2CStageRoute.S4_DEADLINE_BLOCKED_UNMEASURED
            ),
            blockers=(
                "formal Q-B training/evaluation has not produced a measured pure-model count",
            ),
        )
    if q_b_state is QBState.MEASURED_ZERO:
        if observed < s4_deadline:
            return decision(
                (
                    M2CStageRoute.INVALID_PREMATURE_D2
                    if d2_claimed
                    else M2CStageRoute.S4_MEASURED_ZERO_CONTINUE_BEFORE_DEADLINE
                ),
                blockers=(
                    "measured pure-model success is zero before the frozen S4 deadline; "
                    "D2 is not yet authorized",
                ),
            )
        if not d2_claimed:
            return decision(
                M2CStageRoute.S4_DEADLINE_MEASURED_ZERO_AWAITING_D2,
                blockers=("measured Q-B zero requires an explicit strict D2 terminal disposition",),
            )
        if s6_verified and final_verification_passed:
            return decision(
                M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE,
                d2=True,
                s5_required=False,
            )
        return decision(
            (M2CStageRoute.S7_REQUIRED_AFTER_D2 if s6_verified else M2CStageRoute.D2_MEASURED_ZERO),
            d2=True,
            s5_required=False,
        )

    if not s5_verified:
        return decision(
            (
                M2CStageRoute.S5_REQUIRED_AFTER_Q_B_PASS
                if observed < s5_deadline
                else M2CStageRoute.S5_DEADLINE_BLOCKED_UNMEASURED
            ),
            blockers=("Q-B passed but S5 has no verified governed residual disposition",),
        )
    if not s6_verified:
        return decision(
            (
                M2CStageRoute.S6_IN_PROGRESS_AFTER_S5
                if observed < hard_freeze
                else M2CStageRoute.S6_HARD_FREEZE_BLOCKED_UNMEASURED
            ),
            blockers=("S6 formal matched evaluation evidence is absent",),
        )
    if not final_verification_passed:
        return decision(
            M2CStageRoute.S7_REQUIRED_AFTER_S5,
            blockers=("terminal S7 verification is absent or failing",),
        )
    return decision(M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE)
