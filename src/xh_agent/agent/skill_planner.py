"""Parameter-free public skill sequencing for the M1B-beta baseline."""

from __future__ import annotations

from xh_agent.task_compiler.base import TaskSpecV1


MAJOR_SKILLS = ("Approach", "Grasp", "Lift", "Transport", "Place", "Release")


def plan(task: TaskSpecV1) -> list[str]:
    if task.need_clarification:
        return ["Observe", "AskClarification"]
    return ["Observe", *MAJOR_SKILLS, "Retreat"]
