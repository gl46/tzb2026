"""Expected-versus-actual rule comparator; no simulator truth input."""

from __future__ import annotations

from xh_agent.task_compiler.base import ExpectedOutcomeV1


def compare(expected: ExpectedOutcomeV1, actual: dict[str, bool]) -> tuple[str, dict[str, bool]]:
    residual = {name: actual.get(name, False) == desired for name, desired in expected.predicates.items()}
    if all(residual.values()):
        return "SUCCESS", residual
    if actual.get("observation_available", False) and actual.get("target_visible", False):
        return "UNCERTAIN_REOBSERVE", residual
    return "FAILURE_RECOVERABLE", residual
