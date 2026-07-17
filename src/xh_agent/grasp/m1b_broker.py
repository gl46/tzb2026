"""ADR-0013 actuation-internal same-entity selector for industrial cylinders."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class M1BGraspFeedbackV1:
    grasp_success: bool
    tactile_state: str
    reobservation_required: bool


def width_window_from_perceived_diameter(diameter_m: float) -> tuple[float, float]:
    """Conservative public perception-derived width window, never truth size."""
    if not 0.01 <= diameter_m <= 0.12:
        raise ValueError("perceived cylinder diameter must be in [0.01, 0.12] m")
    nominal = min(0.075, max(0.035, diameter_m + 0.010))
    return max(0.0, nominal - 0.012), min(0.08, nominal + 0.012)


class M1BContactBroker:
    """Entity names are retained only in the returned actuator-internal record."""

    def select(self, *, left_entities: set[str], right_entities: set[str]) -> tuple[M1BGraspFeedbackV1, dict[str, str | bool | None]]:
        common = sorted(left_entities & right_entities)
        if len(common) != 1 or not common[0].startswith("cylinder_"):
            return M1BGraspFeedbackV1(False, "no_same_entity_bilateral_contact", True), {
                "actual_sim_entity_id": None,
                "attach_topic": None,
                "same_entity_contact": False,
            }
        entity = common[0]
        return M1BGraspFeedbackV1(True, "bilateral_same_entity_contact", True), {
            "actual_sim_entity_id": entity,
            "attach_topic": f"/xh/m1b/{entity}/attach",
            "same_entity_contact": True,
        }
