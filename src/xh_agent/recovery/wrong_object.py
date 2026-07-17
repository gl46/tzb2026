"""Recovery plan for a perceptually detected non-target grasp."""

from xh_agent.task_compiler.base import RecoveryPlanV1


def plan_wrong_object() -> RecoveryPlanV1:
    return RecoveryPlanV1(
        failure_type="WRONG_OBJECT",
        evidence=["post_grasp_carried_track_mismatch"],
        recovery_subgoals=["Reobserve", "SafePlaceNonTarget", "ReassociateTarget", "Approach", "Regrasp"],
        retry_budget=2,
        changed_parameters={"target_association_gate": "fresh_carried_track_required"},
        stop_condition="two_new_target_associations_exhausted",
    )
