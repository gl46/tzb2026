from xh_agent.task_compiler.base import RecoveryPlanV1


def plan_placement() -> RecoveryPlanV1:
    return RecoveryPlanV1(failure_type="UNSTABLE_OR_WRONG_PLACEMENT", evidence=["object_in_destination=false"], recovery_subgoals=["Reobserve", "Regrasp", "OrientationCorrection", "Place", "Release"], retry_budget=2, changed_parameters={"place_height_offset_m": 0.02}, stop_condition="two_corrected_places_exhausted")
