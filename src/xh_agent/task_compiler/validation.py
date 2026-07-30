"""TaskSpec validation helpers kept separate from language compilation."""

from __future__ import annotations

from .base import TaskSpecV1


def validate_task_spec(payload: dict[str, object]) -> TaskSpecV1:
    return TaskSpecV1.model_validate(payload)
