#!/usr/bin/env python3
"""ADR-0008 no-contact physical-mimic and adapter acceptance probe."""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import rclpy
from control_msgs.action import FollowJointTrajectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from m1a_contact_calibration_client import (  # noqa: E402
    CalibrationClient,
    HAND_JOINTS,
    classify_contacts,
    runtime_link_pose,
)


PHYSICAL_MASTER_JOINT = "panda_finger_joint2"
FOLLOWER_JOINT = "panda_finger_joint1"
PROBES = (
    ("symmetric_open", [0.040, 0.040], True),
    ("symmetric_q2_master_close", [0.010, 0.010], True),
    ("asymmetric_rejected", [0.010, 0.040], False),
    ("symmetric_reopen", [0.040, 0.040], True),
)
PASSIVE_INITIAL_VALUE_M = 0.020
PASSIVE_INITIAL_TOLERANCE_M = 0.001


def observed(client: CalibrationClient) -> list[float]:
    return [client.latest_hand.get(name, math.nan) for name in HAND_JOINTS]


def finger_link_poses() -> dict[str, list[float] | None]:
    return {
        "left": runtime_link_pose("panda_leftfinger"),
        "right": runtime_link_pose("panda_rightfinger"),
    }


def displacement_m(before: list[float] | None, after: list[float] | None) -> float | None:
    if before is None or after is None:
        return None
    return math.sqrt(sum((before[index] - after[index]) ** 2 for index in range(3)))


def main() -> int:
    rclpy.init()
    client = CalibrationClient()
    try:
        if not client.wait_calibration_ready():
            print(json.dumps({"status": "HAND_ACTUATION_PROBE_BLOCKED", "reason": "ROS_ENDPOINTS_UNAVAILABLE"}))
            return 2
        deadline = time.monotonic() + 10.0
        while len(client.latest_hand) != len(HAND_JOINTS) and time.monotonic() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        if len(client.latest_hand) != len(HAND_JOINTS):
            print(json.dumps({"status": "HAND_ACTUATION_PROBE_BLOCKED", "reason": "HAND_JOINT_STATE_UNAVAILABLE"}))
            return 2
        passive_before = observed(client)
        passive_before_links = finger_link_poses()
        client.contact_window(0.5)
        passive_after = observed(client)
        passive_after_links = finger_link_poses()
        passive_error = max(
            abs(position - PASSIVE_INITIAL_VALUE_M)
            for position in passive_after
            if not math.isnan(position)
        )
        passive_no_sag = passive_error <= PASSIVE_INITIAL_TOLERANCE_M
        results = []
        for label, command, should_forward in PROBES:
            before = observed(client)
            before_links = finger_link_poses()
            action = client.command_hand(command)
            contacts = client.contact_window(0.20)
            after = observed(client)
            after_links = finger_link_poses()
            results.append({
                "label": label,
                "before_positions_m": before,
                "command_positions_m": command,
                "after_positions_m": after,
                "before_link_poses_world_xyz_rpy": before_links,
                "after_link_poses_world_xyz_rpy": after_links,
                "finger_link_displacement_m": {
                    side: displacement_m(before_links[side], after_links[side])
                    for side in before_links
                },
                "action": action,
                "contact_observation": classify_contacts(contacts),
                "should_forward": should_forward,
                "physical_command_emitted": any(
                    bool(decision.get("physical_command_emitted"))
                    for decision in action.get("adapter_decisions", [])
                ),
                "all_channels_reached_command": bool(action.get("succeeded")),
            })
        symmetric = [item for item in results if item["should_forward"]]
        rejected = next(item for item in results if item["label"] == "asymmetric_rejected")
        close = next(item for item in results if item["label"] == "symmetric_q2_master_close")
        controls_verified = bool(
            passive_no_sag
            and
            all(item["all_channels_reached_command"] and item["physical_command_emitted"] for item in symmetric)
            and close["action"].get("mimic_tracking_error_m", math.inf) <= 0.001
            and all(
                displacement is not None and displacement >= 0.02
                for displacement in close["finger_link_displacement_m"].values()
            )
            and not rejected["all_channels_reached_command"]
            and rejected["action"].get("controller_result_error_code")
            == FollowJointTrajectory.Result.INVALID_GOAL
            and rejected["action"].get("controller_result_error_string")
            == "ASYMMETRIC_MIMIC_COMMAND_REJECTED"
            and not rejected["physical_command_emitted"]
        )
        print(json.dumps({
            "status": "HAND_MIMIC_Q2_MASTER_VERIFIED" if controls_verified else "HAND_MIMIC_Q2_MASTER_NOT_VERIFIED",
            "scope": "HOME_POSE_NO_ARM_MOTION_NO_OBJECT_CONTACT",
            "joint_names": HAND_JOINTS,
            "physical_master_joint": PHYSICAL_MASTER_JOINT,
            "follower_joint": FOLLOWER_JOINT,
            "tracking_tolerance_m": 0.001,
            "passive_initial_state": {
                "expected_position_m": PASSIVE_INITIAL_VALUE_M,
                "tolerance_m": PASSIVE_INITIAL_TOLERANCE_M,
                "before_positions_m": passive_before,
                "after_positions_m": passive_after,
                "before_link_poses_world_xyz_rpy": passive_before_links,
                "after_link_poses_world_xyz_rpy": passive_after_links,
                "max_error_m": passive_error,
                "no_sag_verified": passive_no_sag,
            },
            "asymmetric_adapter_contract": "INVALID_GOAL:ASYMMETRIC_MIMIC_COMMAND_REJECTED",
            "probes": results,
            "controls_verified": controls_verified,
        }))
        return 0
    finally:
        if rclpy.ok():
            client.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
