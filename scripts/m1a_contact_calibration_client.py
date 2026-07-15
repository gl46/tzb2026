#!/usr/bin/env python3
"""S0 oracle-geometry contact calibration through MoveIt and real controllers."""
from __future__ import annotations

import json
import math
import re
import subprocess
import time

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from geometry_msgs.msg import Pose, PoseStamped
from moveit_msgs.msg import CollisionObject, PlanningScene, RobotState
from moveit_msgs.srv import ApplyPlanningScene, GetPositionIK
from rclpy.action import ActionClient
from ros_gz_interfaces.msg import Contacts
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from m1a_moveit_execution_client import EvidenceClient, JOINTS, set_allowed_pair


HAND_JOINTS = ["panda_finger_joint1", "panda_finger_joint2"]
CONTACT_TOPICS = {
    "left": "/xh/supervision/panda_leftfinger_contacts",
    "right": "/xh/supervision/panda_rightfinger_contacts",
    "cube": "/xh/supervision/red_cube_contacts",
}
CUBE_SIZE_M = 0.05
PAD_SIZE_M = (0.12, 0.018, 0.035)
CALIBRATION_CUBE_XYZ = [0.17, 0.12, 0.755]
CALIBRATION_FIXTURE_XYZ = [0.17, 0.12, 0.59]
CALIBRATION_FIXTURE_SIZE_M = [0.03, 0.03, 0.28]


def quaternion_rotate(quaternion: list[float], point: tuple[float, float, float]) -> list[float]:
    x, y, z, w = quaternion
    px, py, pz = point
    tx, ty, tz = 2 * (y * pz - z * py), 2 * (z * px - x * pz), 2 * (x * py - y * px)
    return [
        px + w * tx + y * tz - z * ty,
        py + w * ty + z * tx - x * tz,
        pz + w * tz + x * ty - y * tx,
    ]


def aabb_separation(
    first_center: list[float], first_size: tuple[float, float, float],
    second_center: list[float], second_size: tuple[float, float, float],
) -> float:
    gaps = [
        max(abs(a - b) - (a_size + b_size) / 2.0, 0.0)
        for a, b, a_size, b_size in zip(first_center, second_center, first_size, second_size)
    ]
    return math.sqrt(sum(gap * gap for gap in gaps))


def runtime_cube_pose() -> dict | None:
    result = subprocess.run(
        ["gz", "model", "-m", "object_red_cube", "-p"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    match = re.search(
        r"Pose.*?:\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
        r"\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]",
        result.stdout,
        re.DOTALL,
    )
    if result.returncode != 0 or match is None:
        return None
    values = [float(value) for value in match.groups()]
    return {"xyz": values[:3], "rpy": values[3:], "source": "gz model runtime oracle"}


def calibration_initialization() -> dict:
    return {
        "status": "CALIBRATION_ONLY_INITIALIZATION",
        "source": "m1a_contact_calibration.sdf",
        "declared_cube_xyz": CALIBRATION_CUBE_XYZ,
        "runtime_pose_write": False,
    }


class CalibrationClient(EvidenceClient):
    def __init__(self) -> None:
        super().__init__()
        self.latest_hand: dict[str, float] = {}
        self.ik_client = self.create_client(GetPositionIK, "/compute_ik")
        self.last_ik_error: dict | None = None
        self.hand_client = ActionClient(
            self, FollowJointTrajectory, "/panda_hand_controller/follow_joint_trajectory"
        )
        self.contacts: dict[str, list[dict]] = {name: [] for name in CONTACT_TOPICS}
        for name, topic in CONTACT_TOPICS.items():
            self.create_subscription(Contacts, topic, lambda msg, channel=name: self.on_contact(channel, msg), 1000)

    def on_joint_state(self, message: JointState) -> None:
        super().on_joint_state(message)
        positions = dict(zip(message.name, message.position))
        if all(name in positions for name in HAND_JOINTS):
            self.latest_hand = {name: float(positions[name]) for name in HAND_JOINTS}

    def on_contact(self, channel: str, message: Contacts) -> None:
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        for contact in message.contacts:
            self.contacts[channel].append(
                {
                    "timestamp_s": stamp,
                    "collision1": contact.collision1.name,
                    "collision2": contact.collision2.name,
                    "depths_m": [float(depth) for depth in contact.depths],
                }
            )

    def wait_calibration_ready(self) -> bool:
        return (
            self.wait_ready()
            and self.ik_client.wait_for_service(timeout_sec=20.0)
            and self.hand_client.wait_for_server(timeout_sec=20.0)
        )

    def ik(
        self, pose: Pose, *, avoid_collisions: bool = True, timeout_s: float = 3.0
    ) -> list[float] | None:
        positions = [self.latest.get(name, math.nan) for name in JOINTS]
        if not all(math.isfinite(value) for value in positions):
            return None
        request = GetPositionIK.Request()
        ik = request.ik_request
        ik.group_name = "panda_arm"
        ik.ik_link_name = "panda_hand"
        ik.robot_state = RobotState(joint_state=JointState(name=JOINTS, position=positions))
        ik.avoid_collisions = avoid_collisions
        ik.pose_stamped = PoseStamped()
        ik.pose_stamped.header.frame_id = "world"
        ik.pose_stamped.pose = pose
        seconds = int(timeout_s)
        ik.timeout = Duration(sec=seconds, nanosec=int((timeout_s - seconds) * 1e9))
        future = self.ik_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=timeout_s + 2.0)
        result = future.result()
        if result is None or result.error_code.val != 1:
            self.last_ik_error = {
                "code": result.error_code.val if result is not None else None,
                "message": result.error_code.message if result is not None else "NO_RESPONSE",
            }
            return None
        self.last_ik_error = None
        solution = dict(zip(result.solution.joint_state.name, result.solution.joint_state.position))
        return [float(solution[name]) for name in JOINTS] if all(name in solution for name in JOINTS) else None

    def command_hand(self, positions: list[float], duration_s: float = 0.8) -> dict:
        goal = FollowJointTrajectory.Goal()
        goal.trajectory = JointTrajectory(joint_names=HAND_JOINTS)
        seconds = int(duration_s)
        nanoseconds = int((duration_s - seconds) * 1e9)
        goal.trajectory.points = [
            JointTrajectoryPoint(
                positions=positions,
                time_from_start=Duration(sec=seconds, nanosec=nanoseconds),
            )
        ]
        sent = self.hand_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, sent, timeout_sec=3.0)
        handle = sent.result()
        if handle is None or not handle.accepted:
            return {"accepted": False, "succeeded": False, "goal_uuid": None}
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=5.0)
        wrapped = result_future.result()
        succeeded = bool(wrapped and wrapped.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL)
        actual = [self.latest_hand.get(name, math.nan) for name in HAND_JOINTS]
        return {
            "accepted": True,
            "succeeded": succeeded,
            "goal_uuid": bytes(handle.goal_id.uuid).hex(),
            "observed_positions_m": actual,
            "max_position_error_m": max(
                (abs(expected - observed) for expected, observed in zip(positions, actual)),
                default=math.inf,
            ),
        }

    def update_cube_scene(self, cube_xyz: list[float]) -> bool:
        scene = PlanningScene(is_diff=True)
        item = CollisionObject()
        item.id = "object_red_cube"
        item.header.frame_id = "world"
        item.primitives = [
            SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[CUBE_SIZE_M] * 3)
        ]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = cube_xyz
        pose.orientation.w = 1.0
        item.primitive_poses = [pose]
        item.operation = CollisionObject.ADD
        scene.world.collision_objects = [item]
        return self.apply_scene_diff(scene)

    def apply_calibration_fixture(self) -> bool:
        scene = PlanningScene(is_diff=True)
        item = CollisionObject()
        item.id = "work_table_calibration_fixture"
        item.header.frame_id = "world"
        item.primitives = [
            SolidPrimitive(type=SolidPrimitive.BOX, dimensions=CALIBRATION_FIXTURE_SIZE_M)
        ]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = CALIBRATION_FIXTURE_XYZ
        pose.orientation.w = 1.0
        item.primitive_poses = [pose]
        item.operation = CollisionObject.ADD
        scene.world.collision_objects = [item]
        return self.apply_scene_diff(scene)

    def set_table_touch_exception(self, allowed: bool) -> bool:
        matrix = self.current_acm()
        if matrix is None:
            return False
        for finger in ("panda_leftfinger", "panda_rightfinger"):
            set_allowed_pair(matrix, finger, "work_table", allowed)
        scene = PlanningScene(is_diff=True)
        scene.allowed_collision_matrix = matrix
        return self.apply_scene_diff(scene)

    def apply_scene_diff(self, scene: PlanningScene) -> bool:
        future = self.scene_client.call_async(ApplyPlanningScene.Request(scene=scene))
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        return bool(future.result() and future.result().success)

    def move_hand_pose(self, pose: Pose) -> dict:
        solution = self.ik(pose)
        if solution is None:
            return {
                "ik_solved": False,
                "ik_error": self.last_ik_error,
                "planned": False,
                "executed": False,
            }
        trajectory = self.plan(solution)
        if trajectory is None:
            return {"ik_solved": True, "ik_solution": solution, "planned": False, "executed": False}
        names = list(trajectory.joint_trajectory.joint_names)
        final = dict(zip(names, trajectory.joint_trajectory.points[-1].positions))
        expected = [float(final[name]) for name in JOINTS]
        executed, goal_uuid, samples, controller_samples, settle_s, converged = self.execute(
            trajectory, expected
        )
        return {
            "ik_solved": True,
            "ik_solution": solution,
            "planned": True,
            "executed": executed,
            "converged": converged,
            "goal_uuid": goal_uuid,
            "joint_state_samples": len(samples),
            "controller_state_samples": len(controller_samples),
            "post_controller_settle_s": settle_s,
        }

    def pad_evidence(self, cube_xyz: list[float]) -> dict:
        positions = [self.latest.get(name, math.nan) for name in JOINTS]
        output: dict[str, dict | float | None] = {}
        separations = []
        for side, link in (("left", "panda_leftfinger"), ("right", "panda_rightfinger")):
            pose = self.fk_link(link, positions)
            if pose is None:
                output[side] = None
                continue
            translation = quaternion_rotate(pose[3:], (0.06, 0.0, 0.0))
            center = [pose[index] + translation[index] for index in range(3)]
            separation = aabb_separation(center, PAD_SIZE_M, cube_xyz, (CUBE_SIZE_M,) * 3)
            output[side] = {"link_pose": pose, "pad_center_world": center, "aabb_separation_m": separation}
            separations.append(separation)
        output["minimum_pad_cube_aabb_separation_m"] = min(separations) if separations else None
        return output

    def fk_link(self, link: str, positions: list[float]) -> list[float] | None:
        from moveit_msgs.srv import GetPositionFK

        request = GetPositionFK.Request()
        request.header.frame_id = "world"
        request.fk_link_names = [link]
        request.robot_state = RobotState(joint_state=JointState(name=JOINTS, position=positions))
        future = self.fk_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        result = future.result()
        if result is None or result.error_code.val != 1 or not result.pose_stamped:
            return None
        pose = result.pose_stamped[0].pose
        return [
            pose.position.x, pose.position.y, pose.position.z,
            pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w,
        ]

    def contact_window(self, duration_s: float) -> dict[str, list[dict]]:
        starts = {name: len(events) for name, events in self.contacts.items()}
        deadline = time.time() + duration_s
        while time.time() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
        return {name: self.contacts[name][starts[name]:] for name in self.contacts}


def hand_pose(cube_xyz: list[float], *, y_offset: float = 0.0) -> Pose:
    pose = Pose()
    pose.position.x = cube_xyz[0] - 0.120
    pose.position.y = cube_xyz[1] + y_offset
    pose.position.z = cube_xyz[2] - 0.055
    pose.orientation.w = 1.0
    return pose


def table_touch_pose(cube_xyz: list[float]) -> Pose:
    pose = Pose()
    pose.position.x = -0.25
    pose.position.y = -0.25
    pose.position.z = 0.562
    pose.orientation.y = math.sqrt(0.5)
    pose.orientation.w = math.sqrt(0.5)
    return pose


def classify_contacts(events: dict[str, list[dict]]) -> dict:
    pairs = {
        channel: sorted({(event["collision1"], event["collision2"]) for event in channel_events})
        for channel, channel_events in events.items()
    }

    def channel_has(channel: str, token: str) -> bool:
        return any(
            token in event["collision1"] or token in event["collision2"]
            for event in events[channel]
        )

    def channel_timestamps(channel: str, token: str | None = None) -> list[float]:
        return sorted(
            {
                event["timestamp_s"]
                for event in events[channel]
                if token is None or token in event["collision1"] or token in event["collision2"]
            }
        )

    rates = {}
    for channel in events:
        timestamps = channel_timestamps(channel)
        duration = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0
        rates[channel] = {
            "unique_timestamp_samples": len(timestamps),
            "duration_s": duration,
            "observed_rate_hz": (len(timestamps) - 1) / duration if duration > 0 else 0.0,
        }
    left_target_times = channel_timestamps("left", "object_red_cube")
    right_target_times = channel_timestamps("right", "object_red_cube")
    overlap = 0.0
    if left_target_times and right_target_times:
        overlap = max(
            0.0,
            min(left_target_times[-1], right_target_times[-1])
            - max(left_target_times[0], right_target_times[0]),
        )

    return {
        "left_target": channel_has("left", "object_red_cube"),
        "right_target": channel_has("right", "object_red_cube"),
        "left_table": channel_has("left", "work_table"),
        "right_table": channel_has("right", "work_table"),
        "cube_table": channel_has("cube", "work_table"),
        "raw_pairs": pairs,
        "event_counts": {channel: len(channel_events) for channel, channel_events in events.items()},
        "topic_rate_evidence": rates,
        "left_target_unique_samples": len(left_target_times),
        "right_target_unique_samples": len(right_target_times),
        "bilateral_overlap_s": overlap,
    }


def main() -> int:
    rclpy.init()
    client = CalibrationClient()
    trials: list[dict] = []
    try:
        if not client.wait_calibration_ready():
            print(json.dumps({"status": "CONTACT_TELEMETRY_BLOCKED", "reason": "ROS_ENDPOINTS_UNAVAILABLE"}))
            return 2
        deadline = time.time() + 10.0
        while not client.latest and time.time() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        if not client.latest or not client.apply_scene() or not client.apply_calibration_fixture():
            print(json.dumps({"status": "CONTACT_TELEMETRY_BLOCKED", "reason": "SCENE_OR_JOINT_STATE_UNAVAILABLE"}))
            return 2
        client.command_hand([0.04, 0.04])
        idle_events = client.contact_window(2.0)
        trials.append({"label": "idle", "expected": "none", "contacts": classify_contacts(idle_events)})

        specifications = (
            [(f"left_{index}", "left", 0.0, [0.030, 0.04]) for index in range(1, 4)]
            + [(f"right_{index}", "right", 0.0, [0.04, 0.030]) for index in range(1, 4)]
            + [(f"bilateral_{index}", "bilateral", 0.0, [0.030, 0.030]) for index in range(1, 4)]
        )
        for label, expected, y_offset, finger_target in specifications:
            initialization = calibration_initialization()
            cube = runtime_cube_pose()
            if cube is None:
                trials.append(
                    {
                        "label": label, "expected": expected,
                        "reason": "CALIBRATION_INITIALIZATION_OR_ORACLE_UNAVAILABLE",
                        "initialization": initialization,
                    }
                )
                continue
            client.update_cube_scene(cube["xyz"])
            client.command_hand([0.04, 0.04])
            start = {name: len(events) for name, events in client.contacts.items()}
            motion = client.move_hand_pose(hand_pose(cube["xyz"], y_offset=y_offset))
            hand_result = client.command_hand(finger_target)
            client.contact_window(0.45)
            events = {name: client.contacts[name][start[name]:] for name in client.contacts}
            cube_after = runtime_cube_pose()
            trials.append(
                {
                    "label": label,
                    "expected": expected,
                    "initialization": initialization,
                    "cube_pose": cube,
                    "cube_pose_after_action": cube_after,
                    "target_hand_pose": [
                        cube["xyz"][0] - 0.120, cube["xyz"][1] + y_offset,
                        cube["xyz"][2] - 0.055, 0.0, 0.0, 0.0, 1.0,
                    ],
                    "motion": motion,
                    "hand_command": {"positions_m": finger_target, **hand_result},
                    "pad_evidence": client.pad_evidence(cube["xyz"]),
                    "contacts": classify_contacts(events),
                }
            )
            client.command_hand([0.04, 0.04])

        client.command_hand([0.04, 0.04])
        for index in range(1, 3):
            initialization = calibration_initialization()
            cube = runtime_cube_pose()
            events = client.contact_window(0.45)
            cube_after = runtime_cube_pose()
            trials.append(
                {
                    "label": f"object_environment_{index}",
                    "expected": "cube_table_without_finger",
                    "initialization": initialization,
                    "cube_pose": cube,
                    "cube_pose_after_action": cube_after,
                    "pad_evidence": client.pad_evidence(cube["xyz"]) if cube else None,
                    "contacts": classify_contacts(events),
                }
            )

        for index in range(1, 3):
            cube = runtime_cube_pose()
            if cube is None:
                trials.append({"label": f"table_{index}", "expected": "finger_table", "reason": "RUNTIME_CUBE_POSE_UNAVAILABLE"})
                continue
            exception_set = client.set_table_touch_exception(True)
            start = {name: len(events) for name, events in client.contacts.items()}
            motion = client.move_hand_pose(table_touch_pose(cube["xyz"])) if exception_set else {
                "ik_solved": False, "planned": False, "executed": False
            }
            client.contact_window(0.45)
            events = {name: client.contacts[name][start[name]:] for name in client.contacts}
            trials.append(
                {
                    "label": f"table_{index}", "expected": "finger_table",
                    "cube_pose": cube, "motion": motion,
                    "calibration_only_allowed_collision_pairs": [
                        ["panda_leftfinger", "work_table"],
                        ["panda_rightfinger", "work_table"],
                    ],
                    "pad_evidence": client.pad_evidence(cube["xyz"]),
                    "contacts": classify_contacts(events),
                }
            )
            client.set_table_touch_exception(False)

        def passed(trial: dict) -> bool:
            contacts = trial.get("contacts", {})
            expected = trial["expected"]
            if expected == "left":
                return contacts.get("left_target") and not contacts.get("right_target")
            if expected == "right":
                return contacts.get("right_target") and not contacts.get("left_target")
            if expected == "bilateral":
                return bool(
                    contacts.get("left_target")
                    and contacts.get("right_target")
                    and contacts.get("bilateral_overlap_s", 0.0) >= 0.1
                    and contacts.get("left_target_unique_samples", 0) >= 3
                    and contacts.get("right_target_unique_samples", 0) >= 3
                )
            if expected == "finger_table":
                return contacts.get("left_table") or contacts.get("right_table")
            if expected == "cube_table_without_finger":
                return contacts.get("cube_table") and not contacts.get("left_target") and not contacts.get("right_target")
            return not contacts.get("left_target") and not contacts.get("right_target")

        for trial in trials:
            trial["passed"] = bool(passed(trial))
        positives = [trial for trial in trials if trial["expected"] in {"left", "right", "bilateral"}]
        status = "CONTACT_TELEMETRY_CALIBRATED" if len(trials) == 14 and all(trial["passed"] for trial in trials) else "CONTACT_TELEMETRY_PARTIAL"
        print(
            json.dumps(
                {
                    "status": status,
                    "reason": f"{sum(trial['passed'] for trial in trials)}/14 calibration windows passed; {sum(trial['passed'] for trial in positives)}/9 finger-target positive windows passed.",
                    "oracle_pose_source": "gz model runtime query before every motion trial",
                    "calibration_initialization": "CALIBRATION_ONLY_INITIALIZATION",
                    "contact_topics": CONTACT_TOPICS,
                    "trials": trials,
                }
            )
        )
        return 0
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
