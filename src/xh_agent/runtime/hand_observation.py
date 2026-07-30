"""ROS-independent hand endpoint evidence checks."""

from __future__ import annotations


def hand_endpoint_observation_succeeded(
    *,
    controller_succeeded: bool,
    fresh_sample_count: int,
    required_fresh_samples: int,
    max_position_error_m: float,
    mimic_tracking_error_m: float,
    goal_tolerance_m: float,
    observation_slack_m: float,
) -> bool:
    """Accept an endpoint only when its bounded observation is current."""

    return bool(
        controller_succeeded
        and fresh_sample_count >= required_fresh_samples
        and max_position_error_m <= goal_tolerance_m + observation_slack_m
        and mimic_tracking_error_m <= goal_tolerance_m + observation_slack_m
    )
