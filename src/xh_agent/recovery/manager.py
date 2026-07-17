"""Recovery plan dispatcher that requires changed parameters on retry."""

from __future__ import annotations

from .empty_grasp import plan_empty_grasp
from .placement import plan_placement
from .release import plan_release
from xh_agent.task_compiler.base import RecoveryPlanV1


def recovery_for(failure_type: str) -> RecoveryPlanV1:
    planners = {"EMPTY_GRASP": plan_empty_grasp, "UNSTABLE_OR_WRONG_PLACEMENT": plan_placement, "RELEASE_FAILURE": plan_release}
    if failure_type not in planners:
        raise ValueError(f"unsupported recovery type: {failure_type}")
    return planners[failure_type]()
