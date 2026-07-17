from xh_agent.task_compiler.base import RecoveryPlanV1


def plan_release() -> RecoveryPlanV1:
    return RecoveryPlanV1(failure_type="RELEASE_FAILURE", evidence=["object_stationary_after_retreat=false"], recovery_subgoals=["Reobserve", "ExplicitOpen", "SafeRetreat", "Reobserve"], retry_budget=2, changed_parameters={"retreat_distance_m": 0.03}, stop_condition="two_explicit_releases_exhausted")
