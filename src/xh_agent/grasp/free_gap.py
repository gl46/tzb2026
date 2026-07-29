"""ADR-0016 free-gap yaw geometry shared by simulator adapters."""

from __future__ import annotations

import math
from collections.abc import Sequence


CALIBRATION_FREE_GAP_YAW_CANDIDATES_RAD = tuple(
    math.radians(value) for value in range(0, 180, 15)
)
FINGER_SWEEP_BOUND_RADIUS_M = 0.0148
FINGER_SWEEP_CENTER_OFFSET_M = 0.0039
FREE_GAP_MIN_CLEARANCE_M = 0.005


def isaac_top_down_orientation_wxyz(
    yaw_rad: float,
) -> tuple[float, float, float, float]:
    """Return Isaac wxyz for ADR-0016's documented Rz(yaw) Rx(pi) pose."""

    if not math.isfinite(yaw_rad):
        raise ValueError("top-down yaw must be finite")
    return (
        0.0,
        math.cos(yaw_rad / 2.0),
        math.sin(yaw_rad / 2.0),
        0.0,
    )


def select_free_gap_yaw_from_xy(
    target_xy: Sequence[float],
    neighbors: Sequence[Sequence[float]],
    *,
    source: str,
    open_finger_m: float = 0.04,
    neighbor_radius_m: float = 0.015,
) -> dict[str, object]:
    """Select the safest open-jaw descent yaw on ADR-0016's 15° grid."""

    if len(target_xy) != 2 or any(len(neighbor) != 2 for neighbor in neighbors):
        raise ValueError("free-gap geometry requires 2D target and neighbor points")
    if (
        not source
        or open_finger_m <= 0
        or neighbor_radius_m <= 0
        or not all(
            math.isfinite(float(value))
            for point in (target_xy, *neighbors)
            for value in point
        )
    ):
        raise ValueError("free-gap geometry contains invalid values")
    arm_offset = open_finger_m + FINGER_SWEEP_CENTER_OFFSET_M
    candidates = []
    for yaw_rad in CALIBRATION_FREE_GAP_YAW_CANDIDATES_RAD:
        closing = (math.sin(yaw_rad), -math.cos(yaw_rad))
        clearance = math.inf
        for sign in (1.0, -1.0):
            finger_center = (
                float(target_xy[0]) + sign * arm_offset * closing[0],
                float(target_xy[1]) + sign * arm_offset * closing[1],
            )
            for neighbor in neighbors:
                distance = math.hypot(
                    finger_center[0] - float(neighbor[0]),
                    finger_center[1] - float(neighbor[1]),
                )
                clearance = min(
                    clearance,
                    distance
                    - FINGER_SWEEP_BOUND_RADIUS_M
                    - neighbor_radius_m,
                )
        candidates.append(
            {
                "yaw_rad": yaw_rad,
                "min_clearance_m": clearance,
            }
        )
    best = max(candidates, key=lambda item: item["min_clearance_m"])
    return {
        "selected_yaw_rad": best["yaw_rad"],
        "min_clearance_m": best["min_clearance_m"],
        "clearance_ok": best["min_clearance_m"] >= FREE_GAP_MIN_CLEARANCE_M,
        "candidates": candidates,
        "source": source,
    }
