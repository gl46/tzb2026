"""Actuation-internal contact routing with a public entity-free result."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraspFeedbackV1:
    grasp_success: bool
    tactile_state: str
    carried_track_id: str | None


class NonOracleGraspBroker:
    def route_contact(self, *, contacted_entity: str | None, contact_verified: bool, carried_track_id: str | None) -> tuple[GraspFeedbackV1, dict[str, str | None]]:
        """Keep Gazebo entity routing internal; return generic feedback only."""
        feedback = GraspFeedbackV1(contact_verified, "bilateral_contact" if contact_verified else "no_contact", carried_track_id if contact_verified else None)
        supervision = {"actual_sim_entity_id": contacted_entity, "wrong_object_truth": None}
        return feedback, supervision
