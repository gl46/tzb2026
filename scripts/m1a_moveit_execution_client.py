#!/usr/bin/env python3
"""Bounded M1A MoveIt plan/execute/FK evidence client for node2."""
from __future__ import annotations

import json
import math
import time

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.action import ExecuteTrajectory
from moveit_msgs.msg import (
    AllowedCollisionEntry,
    AllowedCollisionMatrix,
    CollisionObject,
    Constraints,
    JointConstraint,
    PlanningScene,
    RobotState,
)
from moveit_msgs.srv import ApplyPlanningScene, GetMotionPlan, GetPositionFK
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive


JOINTS = [f"panda_joint{index}" for index in range(1, 8)]
VELOCITY_LIMITS = [2.3925, 2.3925, 2.3925, 2.3925, 2.8710, 2.8710, 2.8973]
TARGETS = [
    ("pregrasp", [0.12, -0.50, 0.10, -1.20, 0.05, 0.90, -0.05]),
    ("lift_or_transport", [0.20, -0.60, 0.15, -1.40, 0.10, 1.10, -0.10]),
    ("preplace_or_home", [0.00, -0.50, 0.00, -1.50, 0.00, 1.00, 0.00]),
]


class EvidenceClient(Node):
    def __init__(self) -> None:
        super().__init__("m1a_moveit_execution_client")
        self.samples: list[dict] = []
        self.latest: dict[str, float] = {}
        self.create_subscription(JointState, "/joint_states", self.on_joint_state, 1000)
        self.plan_client = self.create_client(GetMotionPlan, "/plan_kinematic_path")
        self.scene_client = self.create_client(ApplyPlanningScene, "/apply_planning_scene")
        self.fk_client = self.create_client(GetPositionFK, "/compute_fk")
        self.execute_client = ActionClient(self, ExecuteTrajectory, "/execute_trajectory")

    def on_joint_state(self, message: JointState) -> None:
        positions = dict(zip(message.name, message.position))
        if not all(name in positions for name in JOINTS):
            return
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        values = [float(positions[name]) for name in JOINTS]
        self.latest = dict(zip(JOINTS, values))
        self.samples.append({"timestamp_s": stamp, "positions": values})

    def wait_ready(self) -> bool:
        services = [self.plan_client, self.scene_client, self.fk_client]
        return all(client.wait_for_service(timeout_sec=20.0) for client in services) and self.execute_client.wait_for_server(timeout_sec=20.0)

    def apply_scene(self) -> bool:
        scene = PlanningScene()
        scene.is_diff = True
        for object_id, size, xyz in (
            ("work_table", [1.2, 0.8, 0.10], [0.0, 0.0, 0.40]),
            ("bin_a", [0.40, 0.40, 0.10], [0.51, -0.06, 0.50]),
            ("object_red_cube", [0.05, 0.05, 0.05], [0.22, 0.12, 0.475]),
        ):
            item = CollisionObject()
            item.id = object_id
            item.header.frame_id = "world"
            primitive = SolidPrimitive(type=SolidPrimitive.BOX, dimensions=size)
            pose = Pose()
            pose.position.x, pose.position.y, pose.position.z = xyz
            pose.orientation.w = 1.0
            item.primitives = [primitive]
            item.primitive_poses = [pose]
            item.operation = CollisionObject.ADD
            scene.world.collision_objects.append(item)
        matrix = AllowedCollisionMatrix()
        matrix.entry_names = ["panda_link0", "work_table"]
        matrix.entry_values = [
            AllowedCollisionEntry(enabled=[False, True]),
            AllowedCollisionEntry(enabled=[True, False]),
        ]
        scene.allowed_collision_matrix = matrix
        request = ApplyPlanningScene.Request(scene=scene)
        future = self.scene_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        return bool(future.result() and future.result().success)

    def fk(self, positions: list[float]) -> list[float] | None:
        request = GetPositionFK.Request()
        request.header.frame_id = "world"
        request.fk_link_names = ["panda_hand"]
        request.robot_state = RobotState(joint_state=JointState(name=JOINTS, position=positions))
        future = self.fk_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        result = future.result()
        if result is None or result.error_code.val != 1 or not result.pose_stamped:
            return None
        pose = result.pose_stamped[0].pose
        return [pose.position.x, pose.position.y, pose.position.z,
                pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w]

    def plan(self, target: list[float]):
        request = GetMotionPlan.Request()
        motion = request.motion_plan_request
        motion.group_name = "panda_arm"
        motion.num_planning_attempts = 3
        motion.allowed_planning_time = 5.0
        motion.max_velocity_scaling_factor = 0.2
        motion.max_acceleration_scaling_factor = 0.2
        motion.start_state.is_diff = True
        constraint = Constraints(name="m1a_joint_target")
        constraint.joint_constraints = [
            JointConstraint(joint_name=name, position=value, tolerance_above=0.001,
                            tolerance_below=0.001, weight=1.0)
            for name, value in zip(JOINTS, target)
        ]
        motion.goal_constraints = [constraint]
        future = self.plan_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        result = future.result()
        if result is None or result.motion_plan_response.error_code.val != 1:
            return None
        return result.motion_plan_response.trajectory

    def execute(self, trajectory):
        start_index = len(self.samples)
        goal = ExecuteTrajectory.Goal(trajectory=trajectory)
        sent = self.execute_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, sent, timeout_sec=10.0)
        handle = sent.result()
        if handle is None or not handle.accepted:
            return False, None, []
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=30.0)
        wrapped = result_future.result()
        result = wrapped.result if wrapped else None
        return bool(result and result.error_code.val == 1), str(handle.goal_id.uuid.hex()), self.samples[start_index:]


def segment_evidence(client: EvidenceClient, trial: int, name: str, target: list[float]) -> dict:
    planned_at = time.time()
    trajectory = client.plan(target)
    if trajectory is None:
        return {"trial": trial, "segment": name, "planned": False, "success": False, "reason": "PLAN_FAILED"}
    expected = list(trajectory.joint_trajectory.points[-1].positions)
    expected_fk = client.fk(expected)
    started = time.time()
    executed, goal_uuid, samples = client.execute(trajectory)
    completed = time.time()
    actual = [client.latest.get(joint, math.nan) for joint in JOINTS]
    actual_fk = client.fk(actual) if all(math.isfinite(value) for value in actual) else None
    errors = [abs(a - b) for a, b in zip(actual, expected)]
    monotonic = all(b["timestamp_s"] > a["timestamp_s"] for a, b in zip(samples, samples[1:]))
    max_jump = max((abs(b["positions"][j] - a["positions"][j])
                    for a, b in zip(samples, samples[1:])
                    for j in range(7) if b["timestamp_s"] - a["timestamp_s"] <= 0.1), default=0.0)
    max_velocity_ratio = max((abs(b["positions"][j] - a["positions"][j]) /
                              (b["timestamp_s"] - a["timestamp_s"]) / VELOCITY_LIMITS[j]
                              for a, b in zip(samples, samples[1:]) for j in range(7)
                              if b["timestamp_s"] > a["timestamp_s"]), default=0.0)
    ee_error = math.dist(expected_fk[:3], actual_fk[:3]) if expected_fk and actual_fk else None
    return {
        "trial": trial, "segment": name, "planned": True, "planning_started_wall": planned_at,
        "dispatched": goal_uuid is not None, "goal_uuid": goal_uuid, "controller_result": "SUCCEEDED" if executed else "FAILED",
        "duration_s": completed - started, "expected_final_joints": expected, "observed_final_joints": actual,
        "per_joint_final_error": errors, "max_final_joint_error_rad": max(errors),
        "expected_ee_pose": expected_fk, "observed_ee_pose": actual_fk, "ee_position_error_m": ee_error,
        "joint_state_sample_count": len(samples), "timestamps_monotonic": monotonic,
        "max_adjacent_joint_jump_rad": max_jump, "max_velocity_limit_ratio": max_velocity_ratio,
        "samples": samples, "success": bool(executed and len(samples) >= 20 and monotonic and max(errors) <= 0.05
                                     and ee_error is not None and ee_error <= 0.02 and max_jump <= 0.08
                                     and max_velocity_ratio <= 1.5 and completed - started >= 0.25),
    }


def main() -> int:
    rclpy.init()
    client = EvidenceClient()
    try:
        if not client.wait_ready():
            print(json.dumps({"status": "BLOCKED", "reason": "MOVEIT_ENDPOINTS_UNAVAILABLE"}))
            return 2
        deadline = time.time() + 10.0
        while not client.latest and time.time() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        if not client.latest or not client.apply_scene():
            print(json.dumps({"status": "BLOCKED", "reason": "JOINT_STATE_OR_SCENE_UNAVAILABLE"}))
            return 2
        evidence = [segment_evidence(client, trial, name, target)
                    for trial in range(1, 11) for name, target in TARGETS]
        successful_trials = sum(all(item.get("success") for item in evidence if item["trial"] == trial)
                                for trial in range(1, 11))
        print(json.dumps({"status": "VERIFIED_MOVEIT_EXECUTION" if successful_trials >= 9 else "PARTIAL_EXECUTION_VERIFIED",
                          "successful_trials": successful_trials, "required_trials": 10,
                          "scene_objects": ["work_table", "bin_a", "object_red_cube"], "segments": evidence}))
        return 0
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
