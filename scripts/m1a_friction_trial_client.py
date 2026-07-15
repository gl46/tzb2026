#!/usr/bin/env python3
"""One bounded, unconstrained S2 friction-grasp trial in the dynamic P0 world."""
from __future__ import annotations

import json
import time

import rclpy

from m1a_contact_calibration_client import (
    BILATERAL_IK_SEED,
    CalibrationClient,
    classify_contacts,
    hand_pose,
    runtime_cube_pose,
)


def main() -> int:
    rclpy.init()
    client = CalibrationClient()
    try:
        if not client.wait_calibration_ready() or not client.apply_scene():
            print(json.dumps({"status": "BLOCKED", "reason": "ROS_OR_SCENE_UNAVAILABLE"}))
            return 2
        deadline = time.time() + 10.0
        while not client.latest and time.time() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        cube = runtime_cube_pose()
        if cube is None:
            print(json.dumps({"status": "BLOCKED", "reason": "RUNTIME_CUBE_POSE_UNAVAILABLE"}))
            return 2
        client.update_cube_scene(cube["xyz"])
        client.command_hand([0.04, 0.04])
        exception_set = client.set_target_touch_exception(True)
        approach = client.move_hand_pose(
            hand_pose(cube["xyz"], y_offset=-0.030), ik_seed=BILATERAL_IK_SEED
        ) if exception_set else {"executed": False}
        start = {name: len(events) for name, events in client.contacts.items()}
        close = client.command_hand([0.01, 0.01])
        client.contact_window(0.5)
        contacts = classify_contacts({name: client.contacts[name][start[name]:] for name in client.contacts})
        at_close = client.pad_evidence(cube["xyz"])
        cube_after_close = runtime_cube_pose()
        # A lift is attempted only after observed bilateral physical contact.
        lift = {"executed": False}
        if contacts["left_target"] and contacts["right_target"]:
            lift_pose = hand_pose(cube["xyz"], y_offset=-0.030)
            lift_pose.position.z += 0.10
            lift = client.move_hand_pose(lift_pose, ik_seed=BILATERAL_IK_SEED)
        client.contact_window(1.0)
        cube_after_lift = runtime_cube_pose()
        client.command_hand([0.04, 0.04])
        client.set_target_touch_exception(False)
        separation = at_close.get("gazebo_minimum_pad_cube_aabb_separation_m")
        lift_height = ((cube_after_lift or cube_after_close or cube)["xyz"][2] - cube["xyz"][2])
        if not approach.get("executed") or separation is None or separation > 0.03:
            failure = "APPROACH_ALIGNMENT_FAILURE"
        elif not (contacts["left_target"] and contacts["right_target"]):
            failure = "CONTACT_CLOSURE_FAILURE"
        elif lift_height < 0.05:
            failure = "HOLD_TRANSPORT_FAILURE"
        else:
            failure = "RELEASE_PLACEMENT_FAILURE"
        print(json.dumps({
            "status": "FRICTION_TRIAL_FAILED", "primary_failure_class": failure,
            "detachable_joint_absent": True, "configuration": {
                "id": "baseline", "finger_friction": "world_default", "object_friction": "world_default",
                "object_mass_kg": 0.08, "solver_step_s": 0.001, "gripper_profile_m": [0.04, 0.01],
                "approach_pose_source": "runtime_oracle_geometry_plus_collision_checked_ik",
            }, "cube_pose": cube, "approach": approach, "close": close,
            "contacts": contacts, "pad_evidence_at_close": at_close,
            "cube_pose_after_close": cube_after_close, "lift": lift,
            "cube_pose_after_lift": cube_after_lift, "lift_height_m": lift_height,
        }))
        return 0
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
