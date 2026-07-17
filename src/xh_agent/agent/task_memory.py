"""Public task memory transitions."""

from __future__ import annotations

from xh_agent.task_compiler.base import TaskMemoryV1


def begin(memory: TaskMemoryV1, subgoal: str, track_id: str | None) -> TaskMemoryV1:
    return memory.model_copy(update={"current_subgoal": subgoal, "selected_track": track_id, "attempt_count": memory.attempt_count + 1})


def complete(memory: TaskMemoryV1, subgoal: str, observation_summary: dict[str, object]) -> TaskMemoryV1:
    return memory.model_copy(update={"current_subgoal": None, "completed_subgoals": [*memory.completed_subgoals, subgoal], "last_observation_summary": observation_summary})
