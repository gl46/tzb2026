#!/usr/bin/env python3
"""Frozen M2C S2 domain-iteration stop-loss decision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


MAX_DOMAIN_CANDIDATES = 4
PUBLIC_CONTRACT_FINDING = (
    "连续域候选死于公共感知/谓词接纳域而非 B0 恢复能力"
)


class CandidateStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    INVALID_PUBLIC_CONTRACT = "INVALID_PUBLIC_CONTRACT"
    VALID_Q_A_FAILED = "VALID_Q_A_FAILED"
    Q_A_PASSED = "Q_A_PASSED"


class S2Disposition(str, Enum):
    CONTINUE_CURRENT_CANDIDATE = "CONTINUE_CURRENT_CANDIDATE"
    ALLOW_FINAL_DOMAIN_CANDIDATE = "ALLOW_FINAL_DOMAIN_CANDIDATE"
    PASS_Q_A = "PASS_Q_A"
    TRIGGER_D1 = "TRIGGER_D1"


@dataclass(frozen=True)
class DomainCandidateDecision:
    candidate_number: int
    status: CandidateStatus
    reason: str


@dataclass(frozen=True)
class S2Decision:
    disposition: S2Disposition
    next_candidate_number: int | None
    findings: tuple[str, ...]


def decide_s2_stop_loss(
    records: list[DomainCandidateDecision],
) -> S2Decision:
    """Permit at most V4 after V3 and fail closed into D1.

    V1/V2 evidence remains part of the audit trail. V3 may finish normally;
    if it does not pass Q-A, only one final domain candidate (V4) is allowed.
    Any non-pass at V4 triggers D1. Public-contract invalidity at V4 emits the
    user-mandated formal finding verbatim.
    """

    if not records:
        raise ValueError("at least one S2 domain candidate record is required")
    numbers = [record.candidate_number for record in records]
    if numbers != list(range(1, len(records) + 1)):
        raise ValueError("candidate records must be consecutive from V1")
    if len(records) > MAX_DOMAIN_CANDIDATES:
        raise ValueError("V5 and later domain candidates are forbidden")
    if any(
        record.status == CandidateStatus.Q_A_PASSED
        for record in records[:-1]
    ):
        raise ValueError("no candidate may follow a Q-A pass")

    current = records[-1]
    if current.status == CandidateStatus.IN_PROGRESS:
        return S2Decision(
            S2Disposition.CONTINUE_CURRENT_CANDIDATE,
            None,
            (),
        )
    if current.status == CandidateStatus.Q_A_PASSED:
        return S2Decision(S2Disposition.PASS_Q_A, None, ())
    if current.candidate_number < 3:
        return S2Decision(
            S2Disposition.CONTINUE_CURRENT_CANDIDATE,
            current.candidate_number + 1,
            (),
        )
    if current.candidate_number == 3:
        return S2Decision(
            S2Disposition.ALLOW_FINAL_DOMAIN_CANDIDATE,
            4,
            (),
        )

    findings = (
        (PUBLIC_CONTRACT_FINDING,)
        if current.status == CandidateStatus.INVALID_PUBLIC_CONTRACT
        else ()
    )
    return S2Decision(S2Disposition.TRIGGER_D1, None, findings)
