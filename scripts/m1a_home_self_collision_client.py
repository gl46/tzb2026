#!/usr/bin/env python3
"""Check the approved Panda model's home state in MoveIt's active collision model."""
from __future__ import annotations

import json
import time

import rclpy
from moveit_msgs.msg import RobotState
from moveit_msgs.srv import GetStateValidity
from sensor_msgs.msg import JointState


ARM_JOINTS = [f"panda_joint{index}" for index in range(1, 8)]
# Must exactly match the ``home`` group state in m1a_panda.srdf.  This neutral
# tucked posture was selected by a no-motion ``check_state_validity`` probe
# after the official-origin primitive correction; it is not a collision
# exception or a commanded move.
HOME_ARM_POSITIONS = [0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0]
FINGER_JOINTS = ["panda_finger_joint1", "panda_finger_joint2"]


def main() -> int:
    rclpy.init()
    node = rclpy.create_node("m1a_home_self_collision_client")
    started = time.time()
    try:
        client = node.create_client(GetStateValidity, "/check_state_validity")
        if not client.wait_for_service(timeout_sec=30.0):
            print(json.dumps({
                "status": "HOME_SELF_COLLISION_BLOCKED_SERVICE_UNAVAILABLE",
                "duration_s": time.time() - started,
            }))
            return 2
        request = GetStateValidity.Request()
        request.group_name = "panda_arm"
        request.robot_state = RobotState(
            joint_state=JointState(
                name=[*ARM_JOINTS, *FINGER_JOINTS],
                position=[*HOME_ARM_POSITIONS, 0.02, 0.02],
            )
        )
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=15.0)
        response = future.result()
        if response is None:
            print(json.dumps({
                "status": "HOME_SELF_COLLISION_BLOCKED_NO_RESPONSE",
                "duration_s": time.time() - started,
            }))
            return 2
        contacts = [
            {
                "body_1": contact.contact_body_1,
                "body_2": contact.contact_body_2,
            }
            for contact in response.contacts
        ]
        print(json.dumps({
            "status": "HOME_SELF_COLLISION_VERIFIED" if response.valid else "HOME_SELF_COLLISION_INVALID",
            "valid": bool(response.valid),
            "group": request.group_name,
            "arm_joint_positions_rad": HOME_ARM_POSITIONS,
            "finger_joint_positions_m": [0.02, 0.02],
            "contacts": contacts,
            "duration_s": time.time() - started,
            "method": "MOVEIT_CHECK_STATE_VALIDITY_NO_MOTION_COMMAND",
        }))
        return 0 if response.valid else 3
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
