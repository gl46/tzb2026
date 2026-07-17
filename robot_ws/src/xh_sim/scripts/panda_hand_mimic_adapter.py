#!/usr/bin/env python3
"""Fail-closed two-name Panda hand action compatibility boundary.

The public endpoint retains the pre-ADR-0008 two-finger action protocol while
the physical controller owns only the selected master joint. Its peer is
constrained in the simulator by the SDF mimic relation generated from the
URDF. This node intentionally has
no Gazebo transport or model-pose API: it can only forward a validated
trajectory to the physical trajectory controller.
"""
from __future__ import annotations

import json
import math
import threading
import time

import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


PUBLIC_ACTION = "/panda_hand_controller/follow_joint_trajectory"
PHYSICAL_ACTION = "/panda_hand_physical_controller/follow_joint_trajectory"
PUBLIC_JOINTS = ("panda_finger_joint1", "panda_finger_joint2")
# PANDA_MIMIC_Q2_MASTER: ADR-0008's pre-authorized fallback after the q1
# master no-contact close probe returned a persistent 30 mm error.
PHYSICAL_JOINT = "panda_finger_joint2"
MAX_ASYMMETRY_M = 0.001
LOWER_LIMIT_M = 0.0
UPPER_LIMIT_M = 0.04
STARTUP_HOLD_TOPIC = "/xh/panda_hand_startup_hold/status"
STARTUP_HOLD_TARGET_M = 0.02


class PandaHandMimicAdapter(rclpy.node.Node):
    """Translate exactly-one symmetric two-name action to the selected master."""

    def __init__(self) -> None:
        super().__init__("panda_hand_mimic_adapter")
        self._group = ReentrantCallbackGroup()
        self._physical_client = ActionClient(
            self, FollowJointTrajectory, PHYSICAL_ACTION, callback_group=self._group
        )
        self._decisions = self.create_publisher(String, "/panda_hand_controller/adapter_decision", 100)
        self._startup_status = self.create_publisher(
            String, STARTUP_HOLD_TOPIC,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                       reliability=ReliabilityPolicy.RELIABLE),
        )
        self._server = ActionServer(
            self,
            FollowJointTrajectory,
            PUBLIC_ACTION,
            execute_callback=self.execute,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self._group,
        )
        threading.Thread(target=self._run_startup_hold, daemon=True).start()

    def _run_startup_hold(self) -> None:
        """Seed only q2's documented open initialization before GATE2 samples."""
        if not self._physical_client.wait_for_server(timeout_sec=15.0):
            self._startup_status.publish(String(data="STARTUP_HOLD_FAILED:PHYSICAL_CONTROLLER_UNAVAILABLE"))
            return
        goal = FollowJointTrajectory.Goal()
        goal.trajectory = JointTrajectory(joint_names=[PHYSICAL_JOINT])
        goal.trajectory.points = [JointTrajectoryPoint(
            positions=[STARTUP_HOLD_TARGET_M], time_from_start=Duration(sec=1)
        )]
        sent = self._physical_client.send_goal_async(goal)
        if not _wait_future(sent, timeout_s=5.0) or sent.result() is None or not sent.result().accepted:
            self._startup_status.publish(String(data="STARTUP_HOLD_FAILED:GOAL_REJECTED"))
            return
        completed = sent.result().get_result_async()
        if not _wait_future(completed, timeout_s=10.0) or completed.result() is None or completed.result().result.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            self._startup_status.publish(String(data="STARTUP_HOLD_FAILED:GOAL_RESULT"))
            return
        self._startup_status.publish(String(data="STARTUP_HOLD_SUCCEEDED:q2=0.020m"))

    def goal_callback(self, _request: FollowJointTrajectory.Goal) -> GoalResponse:
        # Accept in order to return a standard FollowJointTrajectory result
        # with INVALID_GOAL. Validation and the guarantee of no physical
        # emission happen in execute before the private action is touched.
        return GoalResponse.ACCEPT

    @staticmethod
    def cancel_callback(_handle: object) -> CancelResponse:
        return CancelResponse.ACCEPT

    def decision(self, *, outcome: str, reason: str, physical_target_m: float | None = None) -> None:
        payload: dict[str, object] = {
            "outcome": outcome,
            "reason": reason,
            "physical_action": PHYSICAL_ACTION,
            "physical_command_emitted": outcome == "FORWARDED",
            "timestamp_monotonic_s": time.monotonic(),
        }
        if physical_target_m is not None:
            payload["physical_master_joint"] = PHYSICAL_JOINT
            payload["physical_target_m"] = physical_target_m
        self._decisions.publish(String(data=json.dumps(payload, sort_keys=True)))

    @staticmethod
    def _invalid_reason(goal: FollowJointTrajectory.Goal) -> str | None:
        trajectory = goal.trajectory
        if tuple(trajectory.joint_names) != PUBLIC_JOINTS:
            return "MALFORMED_PUBLIC_JOINT_ORDER_OR_SET"
        if len(trajectory.points) != 1:
            return "MULTI_POINT_TRAJECTORY_UNDEFINED"
        point = trajectory.points[0]
        if len(point.positions) != len(PUBLIC_JOINTS):
            return "MALFORMED_PUBLIC_POSITION_VECTOR"
        if point.time_from_start.sec < 0 or (
            point.time_from_start.sec == 0 and point.time_from_start.nanosec <= 0
        ):
            return "NONPOSITIVE_TRAJECTORY_DURATION"
        q1_m, q2_m = (float(value) for value in point.positions)
        if not all(math.isfinite(value) for value in (q1_m, q2_m)):
            return "NONFINITE_POSITION"
        if any(value < LOWER_LIMIT_M or value > UPPER_LIMIT_M for value in (q1_m, q2_m)):
            return "FINGER_LIMIT_VIOLATION"
        if abs(q1_m - q2_m) > MAX_ASYMMETRY_M:
            return "ASYMMETRIC_MIMIC_COMMAND_REJECTED"
        return None

    def _result_invalid(self, handle: object, reason: str) -> FollowJointTrajectory.Result:
        self.decision(outcome="REJECTED", reason=reason)
        handle.abort()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.INVALID_GOAL
        result.error_string = reason
        return result

    def execute(self, handle: object) -> FollowJointTrajectory.Result:
        goal = handle.request
        reason = self._invalid_reason(goal)
        if reason is not None:
            return self._result_invalid(handle, reason)
        if not self._physical_client.wait_for_server(timeout_sec=5.0):
            return self._result_invalid(handle, "PHYSICAL_HAND_CONTROLLER_UNAVAILABLE")

        point = goal.trajectory.points[0]
        physical_index = PUBLIC_JOINTS.index(PHYSICAL_JOINT)
        physical_target_m = float(point.positions[physical_index])
        physical_goal = FollowJointTrajectory.Goal()
        physical_goal.trajectory = JointTrajectory(joint_names=[PHYSICAL_JOINT])
        physical_goal.trajectory.points = [
            JointTrajectoryPoint(
                positions=[physical_target_m], time_from_start=Duration(
                    sec=point.time_from_start.sec,
                    nanosec=point.time_from_start.nanosec,
                )
            )
        ]
        physical_goal.goal_tolerance = [
            tolerance for tolerance in goal.goal_tolerance if tolerance.name == PHYSICAL_JOINT
        ]
        self.decision(
            outcome="FORWARDED",
            reason="SYMMETRIC_MIMIC_COMMAND",
            physical_target_m=physical_target_m,
        )
        sent = self._physical_client.send_goal_async(physical_goal)
        if not _wait_future(sent, timeout_s=5.0):
            return self._result_invalid(handle, "PHYSICAL_HAND_GOAL_SEND_TIMEOUT")
        physical_handle = sent.result()
        if physical_handle is None or not physical_handle.accepted:
            return self._result_invalid(handle, "PHYSICAL_HAND_GOAL_REJECTED")
        completed = physical_handle.get_result_async()
        if not _wait_future(completed, timeout_s=10.0):
            physical_handle.cancel_goal_async()
            return self._result_invalid(handle, "PHYSICAL_HAND_GOAL_TIMEOUT")
        wrapped = completed.result()
        result = FollowJointTrajectory.Result()
        if wrapped is not None and wrapped.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL:
            handle.succeed()
            result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
            result.error_string = "SYMMETRIC_MIMIC_COMMAND_FORWARDED"
            return result
        handle.abort()
        result.error_code = wrapped.result.error_code if wrapped is not None else FollowJointTrajectory.Result.INVALID_GOAL
        result.error_string = (
            "PHYSICAL_HAND_CONTROLLER_FAILED:"
            + (wrapped.result.error_string if wrapped is not None else "NO_RESULT")
        )
        return result


def _wait_future(future: object, *, timeout_s: float) -> bool:
    """Wait while the multi-threaded executor services action callbacks."""

    deadline = time.monotonic() + timeout_s
    while not future.done() and time.monotonic() < deadline:
        time.sleep(0.01)
    return bool(future.done())


def main() -> int:
    rclpy.init()
    node = PandaHandMimicAdapter()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
