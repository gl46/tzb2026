"""Expected predicates for every public M1B-beta skill."""

from __future__ import annotations

from xh_agent.task_compiler.base import ExpectedOutcomeV1


_PREDICATES = {
    "Approach": {"target_visible": True, "collision_free": True},
    "Grasp": {"generic_grasp_contact": True},
    "Lift": {"carried_object_rises": True, "collision_free": True},
    "Transport": {"carried_object_present": True, "near_destination": True},
    "Place": {"object_in_destination": True},
    "Release": {"object_stationary_after_retreat": True},
}


def expected_for(skill: str) -> ExpectedOutcomeV1:
    predicates = _PREDICATES.get(skill, {"observation_available": True})
    return ExpectedOutcomeV1(skill_name=skill, predicates=predicates, numeric_tolerances={"position_error_m": 0.05})
