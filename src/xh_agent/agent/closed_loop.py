"""Step-record construction enforcing a new observation after every skill."""

from __future__ import annotations

from .comparator import compare
from .expected_outcome import expected_for
from xh_agent.task_compiler.base import StepRecordV1


def record_step(*, step_id: int, skill: str, before_id: str, before_timestamp_ns: int, after_id: str, after_timestamp_ns: int, actual: dict[str, bool], command_ref: str) -> StepRecordV1:
    expected = expected_for(skill)
    outcome, residual = compare(expected, actual)
    return StepRecordV1(step_id=step_id, skill_name=skill, observation_before_id=before_id, observation_before_timestamp_ns=before_timestamp_ns, expected_outcome=expected, command_or_trajectory_ref=command_ref, controller_result="OBSERVED", observation_after_id=after_id, observation_after_timestamp_ns=after_timestamp_ns, actual_predicates=actual, comparison=outcome, residual_summary=residual, failure_type=None if outcome == "SUCCESS" else "OBSERVATION_MISMATCH", next_decision="continue" if outcome == "SUCCESS" else "reobserve_or_recover")
