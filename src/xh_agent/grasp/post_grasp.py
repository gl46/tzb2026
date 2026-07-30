"""Public post-grasp identity check plus evaluator-only supervision record.

The online check compares two perception track identifiers.  It receives no
Gazebo entity identity and never decides whether the actuator may attach.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PostGraspIdentityV1:
    target_track_id: str
    carried_track_id: str | None
    identity_status: str
    wrong_object_detected: bool
    reobservation_required: bool


def evaluate_post_grasp_identity(*, target_track_id: str, carried_track_id: str | None) -> PostGraspIdentityV1:
    """Classify a fresh perception result without simulator truth.

    A missing carried association is intentionally not converted into success;
    it requests another observation.  A different public track is a concrete
    WRONG_OBJECT recovery event even if the physical grasp is otherwise valid.
    """
    if carried_track_id is None:
        return PostGraspIdentityV1(target_track_id, None, "CARRIED_TRACK_UNOBSERVED", False, True)
    if carried_track_id == target_track_id:
        return PostGraspIdentityV1(target_track_id, carried_track_id, "TARGET_TRACK_CONFIRMED", False, False)
    return PostGraspIdentityV1(target_track_id, carried_track_id, "WRONG_OBJECT", True, False)


def evaluator_supervision_record(*, actual_sim_entity_id: str, wrong_object: bool) -> dict[str, object]:
    """Return a record for offline evaluation; callers must not pass it online."""
    if not actual_sim_entity_id.startswith("cylinder_"):
        raise ValueError("supervision identity must be an industrial cylinder")
    return {
        "actual_sim_entity_id": actual_sim_entity_id,
        "wrong_object": wrong_object,
        "truth_boundary": "evaluation_only_not_available_to_policy",
    }
