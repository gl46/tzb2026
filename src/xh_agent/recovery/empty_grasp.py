from xh_agent.task_compiler.base import RecoveryPlanV1


def plan_empty_grasp() -> RecoveryPlanV1:
    return RecoveryPlanV1(failure_type="EMPTY_GRASP", evidence=["generic_grasp_contact=false"], recovery_subgoals=["Reobserve", "ReassociateTarget", "Approach", "Regrasp", "Lift"], retry_budget=2, changed_parameters={"approach_offset_m": 0.015}, stop_condition="two_new_pose_attempts_exhausted")
