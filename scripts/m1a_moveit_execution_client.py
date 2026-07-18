#!/usr/bin/env python3
"""Bounded M1A MoveIt plan/execute/FK evidence client for node2."""
from __future__ import annotations

import json
import math
import time

import rclpy
from control_msgs.msg import JointTrajectoryControllerState
from geometry_msgs.msg import Pose
from moveit_msgs.action import ExecuteTrajectory
from moveit_msgs.msg import (
    AllowedCollisionEntry,
    AllowedCollisionMatrix,
    CollisionObject,
    Constraints,
    JointConstraint,
    PlanningScene,
    PlanningSceneComponents,
    RobotState,
)
from moveit_msgs.srv import ApplyPlanningScene, GetMotionPlan, GetPlanningScene, GetPositionFK
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive


JOINTS = [f"panda_joint{index}" for index in range(1, 8)]
VELOCITY_LIMITS = [2.3925, 2.3925, 2.3925, 2.3925, 2.8710, 2.8710, 2.8973]
TARGETS = [
    ("pregrasp", [0.12, -0.50, 0.10, -1.20, 0.05, 0.90, -0.05]),
    ("lift_or_transport", [0.20, -0.60, 0.15, -1.40, 0.10, 1.10, -0.10]),
    ("preplace", [0.16, -0.55, 0.12, -1.30, 0.075, 1.00, -0.075]),
]
ADJACENT_SELF_PAIRS = [
    ("panda_link0", "panda_link1"),
    ("panda_link1", "panda_link2"),
    ("panda_link2", "panda_link3"),
    ("panda_link3", "panda_link4"),
    ("panda_link4", "panda_link5"),
    ("panda_link5", "panda_link6"),
    ("panda_link6", "panda_link7"),
    ("panda_link7", "panda_link8"),
    ("panda_link8", "panda_hand"),
    ("panda_hand", "panda_leftfinger"),
    ("panda_hand", "panda_rightfinger"),
]
REQUIRED_CHECKED_PAIRS = [
    ("panda_leftfinger", "object_red_cube"),
    ("panda_rightfinger", "object_red_cube"),
    ("panda_link1", "work_table"),
    ("panda_link7", "work_table"),
    ("panda_link8", "work_table"),
    ("panda_hand", "work_table"),
]


def set_allowed_pair(matrix: AllowedCollisionMatrix, first: str, second: str, allowed: bool) -> None:
    """Set one symmetric ACM pair without discarding the SRDF-derived matrix."""
    names = list(matrix.entry_names)
    rows = [list(entry.enabled) for entry in matrix.entry_values]
    while len(rows) < len(names):
        rows.append([])
    for row in rows:
        row.extend([False] * (len(names) - len(row)))
    for name in (first, second):
        if name not in names:
            names.append(name)
            for row in rows:
                row.append(False)
            rows.append([False] * len(names))
    first_index, second_index = names.index(first), names.index(second)
    rows[first_index][second_index] = allowed
    rows[second_index][first_index] = allowed
    matrix.entry_names = names
    matrix.entry_values = [AllowedCollisionEntry(enabled=row) for row in rows]


def pair_is_allowed(matrix: AllowedCollisionMatrix, first: str, second: str) -> bool:
    if first in matrix.entry_names and second in matrix.entry_names:
        row = matrix.entry_names.index(first)
        column = matrix.entry_names.index(second)
        if row < len(matrix.entry_values) and column < len(matrix.entry_values[row].enabled):
            return bool(matrix.entry_values[row].enabled[column])
    if first in matrix.default_entry_names:
        return bool(matrix.default_entry_values[matrix.default_entry_names.index(first)])
    if second in matrix.default_entry_names:
        return bool(matrix.default_entry_values[matrix.default_entry_names.index(second)])
    return False


class EvidenceClient(Node):
    def __init__(self) -> None:
        super().__init__("m1a_moveit_execution_client")
        self.samples: list[dict] = []
        self.controller_samples: list[dict] = []
        self.latest: dict[str, float] = {}
        self.create_subscription(JointState, "/joint_states", self.on_joint_state, 1000)
        self.create_subscription(
            JointTrajectoryControllerState,
            "/panda_arm_controller/controller_state",
            self.on_controller_state,
            1000,
        )
        self.plan_client = self.create_client(GetMotionPlan, "/plan_kinematic_path")
        self.scene_client = self.create_client(ApplyPlanningScene, "/apply_planning_scene")
        self.scene_get_client = self.create_client(GetPlanningScene, "/get_planning_scene")
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

    def on_controller_state(self, message: JointTrajectoryControllerState) -> None:
        reference = dict(zip(message.joint_names, message.reference.positions))
        feedback = dict(zip(message.joint_names, message.feedback.positions))
        if not all(name in reference and name in feedback for name in JOINTS):
            return
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        desired = [float(reference[name]) for name in JOINTS]
        actual = [float(feedback[name]) for name in JOINTS]
        self.controller_samples.append(
            {
                "timestamp_s": stamp,
                "q_des": desired,
                "q_act": actual,
                "absolute_error": [abs(d - a) for d, a in zip(desired, actual)],
            }
        )

    def wait_ready(self) -> bool:
        services = [self.plan_client, self.scene_client, self.scene_get_client, self.fk_client]
        return all(client.wait_for_service(timeout_sec=20.0) for client in services) and self.execute_client.wait_for_server(timeout_sec=20.0)

    def current_acm(self) -> AllowedCollisionMatrix | None:
        request = GetPlanningScene.Request()
        request.components = PlanningSceneComponents(
            components=PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
        )
        future = self.scene_get_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        result = future.result()
        return result.scene.allowed_collision_matrix if result is not None else None

    def apply_scene(self) -> bool:
        matrix = self.current_acm()
        if matrix is None:
            return False
        if not all(pair_is_allowed(matrix, *pair) for pair in ADJACENT_SELF_PAIRS):
            self.get_logger().error("SRDF adjacent self-collision exceptions are absent from the current ACM")
            return False
        set_allowed_pair(matrix, "panda_link0", "work_table", True)
        if any(pair_is_allowed(matrix, *pair) for pair in REQUIRED_CHECKED_PAIRS):
            self.get_logger().error("A required robot/world collision pair is disabled in the current ACM")
            return False
        scene = PlanningScene()
        scene.is_diff = True
        for object_id, size, xyz in (
            ("work_table", [1.2, 0.8, 0.10], [0.0, 0.0, 0.40]),
            ("bin_a", [0.30, 0.30, 0.10], [0.217366447885, -0.249990627453, 0.50]),
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
        # Use the same live robot-state sample for planning that the execution
        # side will shortly validate.  Leaving this empty delegates to
        # MoveIt's monitored-state cache, which can lag `/joint_states` across
        # a paused-world reset and produces a trajectory rejected at execution
        # start for a state that has already changed in Gazebo.
        start_positions = [self.latest.get(name, math.nan) for name in JOINTS]
        if all(math.isfinite(value) for value in start_positions):
            motion.start_state.joint_state = JointState(name=JOINTS, position=start_positions)
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

    def execute(self, trajectory, expected: list[float]):
        start_index = len(self.samples)
        controller_start_index = len(self.controller_samples)
        goal = ExecuteTrajectory.Goal(trajectory=trajectory)
        sent = self.execute_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, sent, timeout_sec=10.0)
        handle = sent.result()
        if handle is None or not handle.accepted:
            return False, None, [], [], 0.0, False
        result_future = handle.get_result_async()
        # A collision-checked detour can legitimately exceed the historical
        # fixed 30 s wait.  Timing out the client while the controller keeps
        # moving is unsafe: callers may plan a second trajectory against a
        # stale start state.  Bound the wait from the approved trajectory's
        # own final time plus a finite transport/controller margin instead.
        final_time = trajectory.joint_trajectory.points[-1].time_from_start
        trajectory_duration_s = final_time.sec + final_time.nanosec * 1e-9
        # Gazebo's controller loop can complete noticeably later than the
        # time parameterization when it is sharing a physics/render workload.
        # Keep the action client alive long enough to receive that terminal
        # result; otherwise a real completed motion is falsely recorded as a
        # timeout and its next trial starts from an unknown arm state.
        result_timeout_s = min(120.0, max(60.0, trajectory_duration_s + 30.0))
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=result_timeout_s)
        wrapped = result_future.result()
        result = wrapped.result if wrapped else None
        controller_succeeded = bool(result and result.error_code.val == 1)
        controller_completed_at = time.time()
        consecutive_converged = 0
        settle_deadline = controller_completed_at + 3.0
        while controller_succeeded and time.time() < settle_deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
            actual = [self.latest.get(joint, math.nan) for joint in JOINTS]
            converged = all(math.isfinite(value) for value in actual) and max(
                abs(actual_value - expected_value)
                for actual_value, expected_value in zip(actual, expected)
            ) <= 0.01
            consecutive_converged = consecutive_converged + 1 if converged else 0
            if consecutive_converged >= 5:
                break
        return (
            controller_succeeded,
            bytes(handle.goal_id.uuid).hex(),
            self.samples[start_index:],
            self.controller_samples[controller_start_index:],
            time.time() - controller_completed_at,
            consecutive_converged >= 5,
        )


def segment_evidence(client: EvidenceClient, trial: int, name: str, target: list[float]) -> dict:
    planned_at = time.time()
    trajectory = client.plan(target)
    if trajectory is None:
        return {"trial": trial, "segment": name, "planned": False, "success": False, "reason": "PLAN_FAILED"}
    planned_joint_names = list(trajectory.joint_trajectory.joint_names)
    planned_final_positions = list(trajectory.joint_trajectory.points[-1].positions)
    planned_by_name = dict(zip(planned_joint_names, planned_final_positions))
    if not all(joint in planned_by_name for joint in JOINTS):
        return {
            "trial": trial,
            "segment": name,
            "planned": True,
            "success": False,
            "reason": "PLANNED_JOINT_SET_MISMATCH",
            "planned_joint_names": planned_joint_names,
        }
    expected = [planned_by_name[joint] for joint in JOINTS]
    expected_fk = client.fk(expected)
    started = time.time()
    executed, goal_uuid, samples, controller_samples, settle_duration, settled = client.execute(
        trajectory, expected
    )
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
    max_tracking_error = max(
        (max(sample["absolute_error"]) for sample in controller_samples),
        default=math.inf,
    )
    ee_error = math.dist(expected_fk[:3], actual_fk[:3]) if expected_fk and actual_fk else None
    return {
        "trial": trial, "segment": name, "planned": True, "planning_started_wall": planned_at,
        "planned_joint_names": planned_joint_names,
        "planned_final_positions_in_trajectory_order": planned_final_positions,
        "dispatched": goal_uuid is not None, "goal_uuid": goal_uuid, "controller_result": "SUCCEEDED" if executed else "FAILED",
        "duration_s": completed - started, "expected_final_joints": expected, "observed_final_joints": actual,
        "post_controller_settle_s": settle_duration, "post_controller_converged": settled,
        "per_joint_final_error": errors, "max_final_joint_error_rad": max(errors),
        "expected_ee_pose": expected_fk, "observed_ee_pose": actual_fk, "ee_position_error_m": ee_error,
        "joint_state_sample_count": len(samples), "timestamps_monotonic": monotonic,
        "controller_state_sample_count": len(controller_samples),
        "max_tracking_error_rad": max_tracking_error,
        "max_adjacent_joint_jump_rad": max_jump, "max_velocity_limit_ratio": max_velocity_ratio,
        "samples": samples, "controller_samples": controller_samples,
        "success": bool(executed and settled and len(samples) >= 20 and monotonic
                                     and max_tracking_error <= 0.05 and max(errors) <= 0.05
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
