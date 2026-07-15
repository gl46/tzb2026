"""P0 deterministic rule/geometric baseline; no VLM, Student, or Teacher dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from xh_agent.contracts.models import CandidateSkillV0, SkillType, TaskSpecV0


class PlanningBackend(Protocol):
    def plan(self, skills: list[CandidateSkillV0]) -> str: ...


class MockPlanningBackend:
    """Explicitly reports BLOCKED until a MoveIt backend is installed and selected."""

    def plan(self, skills: list[CandidateSkillV0]) -> str:
        del skills
        return "BLOCKED_BACKEND_UNAVAILABLE"


class DeterministicPlanningBackend:
    """A non-physics planner for exercising the B1 contract before MoveIt is wired in."""

    def plan(self, skills: list[CandidateSkillV0]) -> str:
        return "PLANNED" if skills else "BLOCKED_EMPTY_SKILL_SEQUENCE"


class ExecutionEvent(str, Enum):
    EMPTY_GRASP = "empty_grasp"
    SLIP = "slip"
    PATH_BLOCKED = "path_blocked"
    RELEASE_FAILURE = "release_failure"


@dataclass(frozen=True)
class BaselineResult:
    status: str
    selected_object_id: str | None
    skills: list[CandidateSkillV0]
    recovery_skill: CandidateSkillV0 | None
    reason: str


def _skill(kind: SkillType, target: str | None, number: int) -> CandidateSkillV0:
    return CandidateSkillV0(
        skill_type=kind,
        target_object_id=target,
        coordinate_frame="world",
        generated_by="B1_RULE_GEOMETRY",
        candidate_id=f"b1-{number:02d}-{kind.value.lower()}",
        expected_effects=[kind.value.lower()],
    )


def _recovery_for(event: ExecutionEvent, target: str) -> CandidateSkillV0:
    kind = {
        ExecutionEvent.EMPTY_GRASP: SkillType.REGRASP,
        ExecutionEvent.SLIP: SkillType.REGRASP,
        ExecutionEvent.PATH_BLOCKED: SkillType.BACKOFF,
        ExecutionEvent.RELEASE_FAILURE: SkillType.REOBSERVE,
    }[event]
    recovery = _skill(kind, target, 7)
    return recovery.model_copy(update={"preconditions": [event.value], "expected_effects": ["recover"]})


def run_b1(
    task: TaskSpecV0, backend: PlanningBackend | None = None, execution_event: ExecutionEvent | None = None
) -> BaselineResult:
    target = task.target_object_id
    if target is None:
        return BaselineResult("BLOCKED", None, [], None, "target requires scene resolution")
    skills = [_skill(kind, target, index) for index, kind in enumerate((
        SkillType.APPROACH, SkillType.GRASP, SkillType.LIFT, SkillType.MOVE,
        SkillType.PLACE, SkillType.RELEASE,
    ), start=1)]
    planning_status = (backend or DeterministicPlanningBackend()).plan(skills)
    if planning_status != "PLANNED":
        return BaselineResult("BLOCKED", target, skills, _recovery_for(ExecutionEvent.PATH_BLOCKED, target), planning_status)
    if execution_event is not None:
        return BaselineResult("RECOVERY_REQUIRED", target, skills, _recovery_for(execution_event, target), execution_event.value)
    return BaselineResult("READY", target, skills, None, "planned")
