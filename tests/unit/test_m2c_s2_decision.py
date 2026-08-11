from __future__ import annotations

import pytest

from m2c.s2_decision import (
    PUBLIC_CONTRACT_FINDING,
    CandidateStatus,
    DomainCandidateDecision,
    S2Disposition,
    decide_s2_stop_loss,
)


def record(number: int, status: CandidateStatus) -> DomainCandidateDecision:
    return DomainCandidateDecision(number, status, f"v{number}")


V1_V2_INVALID = [
    record(1, CandidateStatus.INVALID_PUBLIC_CONTRACT),
    record(2, CandidateStatus.INVALID_PUBLIC_CONTRACT),
]


def test_v3_in_progress_does_not_authorize_v4_yet() -> None:
    result = decide_s2_stop_loss(
        [*V1_V2_INVALID, record(3, CandidateStatus.IN_PROGRESS)]
    )
    assert result.disposition == S2Disposition.CONTINUE_CURRENT_CANDIDATE
    assert result.next_candidate_number is None


def test_v3_nonpass_allows_exactly_one_final_domain_candidate() -> None:
    for status in (
        CandidateStatus.INVALID_PUBLIC_CONTRACT,
        CandidateStatus.VALID_Q_A_FAILED,
    ):
        result = decide_s2_stop_loss([*V1_V2_INVALID, record(3, status)])
        assert result.disposition == S2Disposition.ALLOW_FINAL_DOMAIN_CANDIDATE
        assert result.next_candidate_number == 4


def test_invalid_v4_triggers_d1_and_required_finding() -> None:
    result = decide_s2_stop_loss(
        [
            *V1_V2_INVALID,
            record(3, CandidateStatus.INVALID_PUBLIC_CONTRACT),
            record(4, CandidateStatus.INVALID_PUBLIC_CONTRACT),
        ]
    )
    assert result.disposition == S2Disposition.TRIGGER_D1
    assert result.next_candidate_number is None
    assert result.findings == (PUBLIC_CONTRACT_FINDING,)


def test_q_a_pass_stops_domain_iteration() -> None:
    result = decide_s2_stop_loss(
        [*V1_V2_INVALID, record(3, CandidateStatus.Q_A_PASSED)]
    )
    assert result.disposition == S2Disposition.PASS_Q_A
    assert result.findings == ()


def test_v5_is_forbidden() -> None:
    with pytest.raises(ValueError, match="V5"):
        decide_s2_stop_loss(
            [
                *V1_V2_INVALID,
                record(3, CandidateStatus.INVALID_PUBLIC_CONTRACT),
                record(4, CandidateStatus.INVALID_PUBLIC_CONTRACT),
                record(5, CandidateStatus.INVALID_PUBLIC_CONTRACT),
            ]
        )
