#!/usr/bin/env python3
"""S0 oracle-geometry contact calibration through MoveIt and real controllers."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTolerance, JointTrajectoryControllerState
from geometry_msgs.msg import Pose, PoseArray, PoseStamped
from moveit_msgs.msg import AttachedCollisionObject, CollisionObject, PlanningScene, PlanningSceneComponents, RobotState, RobotTrajectory
from moveit_msgs.srv import ApplyPlanningScene, GetPlanningScene, GetPositionIK
from rclpy.action import ActionClient
from ros_gz_interfaces.msg import Contacts
from sensor_msgs.msg import JointState
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import String
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from rosgraph_msgs.msg import Clock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xh_agent.grasp.orientation_families import gripper_frame_corridor  # noqa: E402

from m1a_moveit_execution_client import EvidenceClient, JOINTS, TARGETS, set_allowed_pair  # noqa: E402


HAND_JOINTS = ["panda_finger_joint1", "panda_finger_joint2"]
# PANDA_MIMIC_Q2_MASTER is the pre-authorized ADR-0008 fallback selected only
# after the recorded q1-master close probe held a 30 mm physical error.
PHYSICAL_HAND_JOINT = "panda_finger_joint2"
PHYSICAL_HAND_CONTROLLER = "/panda_hand_physical_controller/controller_state"
CONTACT_TOPICS = {
    "left": "/xh/supervision/panda_leftfinger_contacts",
    "right": "/xh/supervision/panda_rightfinger_contacts",
    "cube": "/xh/supervision/red_cube_contacts",
    "cube_bilateral": "/xh/supervision/red_cube_bilateral_contacts",
    # A dynamic, geometry-identical red cube resting on the production table.
    # The grasp target remains static so independent finger windows cannot
    # disturb one another; this companion proves target-type/table contacts.
    "cube_environment": "/xh/supervision/red_cube_environment_contacts",
}
CUBE_SIZE_M = 0.05
# ADR-0016 pre-authorized fallback: the pads are now the primitive-approximated
# copy of the official franka finger.stl.  The S0 AABB evidence tracks the
# distal contact pad ("tapered_tip_collision"), whose face lies exactly on the
# finger-link y=0 plane; the recessed proximal body is excluded because it sits
# 2.5 mm behind that face and cannot make the S0 contact.
PAD_SIZE_M = (0.021, 0.0208, 0.0538)
# Signed per-side plate-box centres in each finger-link frame.  The grasp
# element is a full-length plate (the proven old-hand contact element was a
# plate; a 17.8 mm block measured zero bullet contact response even at
# 4.5 mm modelled overlap).  Its face is modelled 6.5 mm proud of the link
# y=0 plane (measured shallow-penetration dead-band compensation for free
# dynamic targets); the public inner-gap mapping remains 2q - 0.006.
PAD_CENTER_IN_FINGER_M = {
    "left": (0.0, 0.0039, 0.0269),
    "right": (0.0, -0.0039, 0.0269),
}
FINGER_LENGTH_M = 0.1122
FINGER_ROOT_Z_M = 0.1032
PLANNING_SCENE_WORLD_OBJECT_PADDING_M = 0.0
CALIBRATION_CUBE_XYZ = [0.17, 0.12, 0.755]
CALIBRATION_FIXTURE_XYZ = [0.17, 0.12, 0.59]
CALIBRATION_FIXTURE_SIZE_M = [0.01, 0.01, 0.28]
CONTACT_RETREAT_HEIGHT_M = 0.220
HAND_POST_GOAL_OBSERVATION_SLACK_M = 0.0001
# Hand action-client waits.  The result wait must scale with the commanded
# trajectory rather than assume a wall-clock bound: this simulator shares its
# GPU, so a 1.2 s close can take materially longer in wall-clock time.
HAND_GOAL_ACCEPT_TIMEOUT_S = 5.0
HAND_RESULT_TIMEOUT_FLOOR_S = 15.0
HAND_RESULT_TIMEOUT_MARGIN_S = 15.0
# Post-goal observation: require this many joint-state deliveries after the
# action result before judging position error, bounded by a deadline.  These
# make the snapshot current; they do not widen the 1 mm goal tolerance.
HAND_POST_GOAL_FRESH_SAMPLES = 3
HAND_POST_GOAL_SETTLE_TIMEOUT_S = 2.0
# The nominal side-contact pose placed the finger pad exactly tangent to
# the cube's west face.  The full S0 run recorded 0.30--0.94 mm FK / Gazebo
# AABB gaps for otherwise executed right and bilateral trials, so the fixture
# needs a measured 2 mm finger-only overlap margin.  This is calibration-only:
# the high fixture and the allowed collision pairs remain unchanged.
CALIBRATION_FINGER_TARGET_INSET_M = 0.002
# The free target must be centred by symmetric jaw closure, not by a long
# side-push from the hand.  Keep only a 1 mm final approach from a non-contact
# pre-close pose; the corresponding before/after poses are recorded below.
BILATERAL_PRECONTACT_CLEARANCE_M = 0.001
BILATERAL_FINAL_FINGER_INSET_M = 0.0
# The 25 mm-per-finger final command closes to a 50 mm inner gap on the 50 mm
# S0 cube.  Use the fully open 40 mm state for the vertical terminal descent
# so neither pad clips a sidewall before closure.
BILATERAL_PRECONTACT_FINGER_M = 0.040
BILATERAL_PRECONTACT_VERTICAL_STANDOFF_M = 0.050
# The franka-copy palm spans hand-frame x +/-0.0317, so at the bilateral pose
# it overlaps the backstop column (x 0.1975..0.2075, top z 0.805) by 4 mm in
# x.  The backstop is physical-only (not a planning-scene object), so a pose
# whose palm bottom descends below its top stalls the arm on a sensorless
# contact.  Palm bottom = cube_z + 0.1032 - inset + offset - 0.066; a 20 mm
# offset keeps it at 0.8104 (5.4 mm above the backstop) while 16 mm of the
# 17.8 mm pad still overlaps the cube sidewall.
BILATERAL_CONTACT_VERTICAL_OFFSET_M = 0.020
BILATERAL_STEADY_WIDTH_RANGE_M = (0.045, 0.070)
# The public finger-contact topics observe both named collision elements.
# With the table top at z=0.450 m, the franka-copy pad spans local +Z
# 0.0944--0.1122 from the hand.  Rx(pi) maps that axis down, so a 0.550 m
# hand origin presses the distal pad end into the tabletop.
TABLE_TOUCH_HAND_Z_M = 0.550
TABLE_TOUCH_PRECONTACT_STANDOFF_M = 0.100


def calibration_bilateral_branch_seed() -> list[float]:
    """Select the collision-validated elbow-up IK branch for the free cube.

    This is only a numerical IK initial value, not a seven-joint action: the
    requested end-effector pose remains derived from the runtime oracle cube
    pose on every label.  Without a branch selector, equivalent Panda hand
    poses can sweep the physical free cube differently before jaw closure.
    """
    return [
        0.7951233744998444, -0.7951787069080972, -1.0790437437304568,
        -2.617706356985651, -0.7753497125747142, 2.023731606765663,
        1.0679453240091286,
    ]
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
    return runtime_model_pose("object_red_cube")


def runtime_bilateral_cube_pose() -> dict | None:
    return runtime_model_pose("object_red_cube_bilateral")


def runtime_link_pose(link: str) -> list[float] | None:
    pose = runtime_model_pose("panda_controller", link=link)
    if pose is None:
        return None
    return [*pose["xyz"], *pose["rpy"]]


def runtime_model_pose(model: str, *, link: str | None = None) -> dict | None:
    # gz model remains subscribed after printing a state. Bound the query
    # externally and parse its first response even when timeout returns 124.
    command = ["timeout", "1.5", "gz", "model", "-m", model]
    if link is None:
        command.append("-p")
    else:
        command.extend(["-l", link])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )
    match = re.search(
        r"^\s*- Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*"
        r"\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
        r"\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]",
        result.stdout,
        re.MULTILINE,
    )
    if match is None:
        return None
    values = [float(value) for value in match.groups()]
    return {
        "xyz": values[:3],
        "rpy": values[3:],
        "source": f"gz model runtime oracle ({model}{'/' + link if link else ''})",
    }


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
        self.hand_state_seq = 0
        self.ik_client = self.create_client(GetPositionIK, "/compute_ik")
        self.last_ik_error: dict | None = None
        self.hand_client = ActionClient(
            self, FollowJointTrajectory, "/panda_hand_controller/follow_joint_trajectory"
        )
        self.contacts: dict[str, list[dict]] = {name: [] for name in CONTACT_TOPICS}
        self.hand_controller_samples: list[dict] = []
        self.adapter_decisions: list[dict] = []
        self.dynamic_cube_poses: list[dict] = []
        self.dynamic_target_reference_xyz: list[float] | None = None
        self.latest_sim_clock_s: float | None = None
        for name, topic in CONTACT_TOPICS.items():
            self.create_subscription(Contacts, topic, lambda msg, channel=name: self.on_contact(channel, msg), 1000)
        self.create_subscription(Clock, "/clock", self.on_clock, 1000)
        self.create_subscription(PoseArray, "/xh/supervision/dynamic_pose", self.on_dynamic_pose, 1000)
        self.create_subscription(
            JointTrajectoryControllerState,
            PHYSICAL_HAND_CONTROLLER,
            self.on_hand_controller_state,
            1000,
        )
        self.create_subscription(
            String,
            "/panda_hand_controller/adapter_decision",
            self.on_hand_adapter_decision,
            1000,
        )

    def on_joint_state(self, message: JointState) -> None:
        super().on_joint_state(message)
        positions = dict(zip(message.name, message.position))
        if all(name in positions for name in HAND_JOINTS):
            self.latest_hand = {name: float(positions[name]) for name in HAND_JOINTS}
            # Counts deliveries, not spins.  command_hand needs to know its
            # post-goal snapshot actually post-dates the action result rather
            # than assuming a fixed number of spins was long enough.
            self.hand_state_seq += 1

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

    def on_clock(self, message: Clock) -> None:
        self.latest_sim_clock_s = message.clock.sec + message.clock.nanosec * 1e-9

    def on_hand_controller_state(self, message: JointTrajectoryControllerState) -> None:
        reference = dict(zip(message.joint_names, message.reference.positions))
        feedback = dict(zip(message.joint_names, message.feedback.positions))
        output = dict(zip(message.joint_names, message.output.positions))
        if PHYSICAL_HAND_JOINT not in reference or PHYSICAL_HAND_JOINT not in feedback:
            return
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        self.hand_controller_samples.append({
            "timestamp_s": stamp,
            "physical_joint": PHYSICAL_HAND_JOINT,
            "physical_reference_m": float(reference[PHYSICAL_HAND_JOINT]),
            "physical_feedback_m": float(feedback[PHYSICAL_HAND_JOINT]),
            "physical_error_m": float(reference[PHYSICAL_HAND_JOINT] - feedback[PHYSICAL_HAND_JOINT]),
            "physical_output_m": (
                float(output[PHYSICAL_HAND_JOINT])
                if PHYSICAL_HAND_JOINT in output else None
            ),
        })

    def on_hand_adapter_decision(self, message: String) -> None:
        try:
            decision = json.loads(message.data)
        except json.JSONDecodeError:
            decision = {"outcome": "UNPARSEABLE", "raw": message.data}
        self.adapter_decisions.append(decision)

    def set_dynamic_target_reference(self, cube_xyz: list[float]) -> None:
        """Bind PoseArray target selection to a runtime-oracle S3 target pose."""

        self.dynamic_target_reference_xyz = list(cube_xyz)
        self.dynamic_cube_poses.clear()

    def on_dynamic_pose(self, message: PoseArray) -> None:
        """Store the target pose nearest to the runtime-oracle target reference.

        ``Pose_V`` conversion to ``PoseArray`` does not retain Gazebo entity
        names. S3 therefore binds the target once from allowed simulator
        supervision at reset, then records the nearest dynamic entry with the
        bridged simulation clock and explicit provenance.
        """

        if self.dynamic_target_reference_xyz is None or self.latest_sim_clock_s is None or not message.poses:
            return
        candidate = min(
            message.poses,
            key=lambda pose: sum(
                (coordinate - reference) ** 2
                for coordinate, reference in zip(
                    (pose.position.x, pose.position.y, pose.position.z),
                    self.dynamic_target_reference_xyz,
                )
            ),
        )
        self.dynamic_cube_poses.append({
            "timestamp_s": self.latest_sim_clock_s,
            "xyz_m": [candidate.position.x, candidate.position.y, candidate.position.z],
            "pose_count": len(message.poses),
            "source": "/xh/supervision/dynamic_pose (Pose_V→PoseArray nearest runtime-oracle target)",
        })

    def wait_calibration_ready(self) -> bool:
        return (
            self.wait_ready()
            and self.ik_client.wait_for_service(timeout_sec=20.0)
            and self.hand_client.wait_for_server(timeout_sec=20.0)
        )

    def ik(
        self, pose: Pose, *, avoid_collisions: bool = True, timeout_s: float = 3.0,
        seed: list[float] | None = None, ik_link: str = "panda_hand",
        hand_positions: list[float] | None = None,
    ) -> list[float] | None:
        positions = seed or [self.latest.get(name, math.nan) for name in JOINTS]
        if not all(math.isfinite(value) for value in positions):
            return None
        hand_values = hand_positions or [self.latest_hand.get(name, math.nan) for name in HAND_JOINTS]
        if not all(math.isfinite(value) for value in hand_values):
            return None
        request = GetPositionIK.Request()
        ik = request.ik_request
        ik.group_name = "panda_arm"
        ik.ik_link_name = ik_link
        # The bilateral fixture is intentionally close to the pads.  Supplying
        # their measured opening prevents IK from silently evaluating the
        # default closed-finger state instead of the physical state it will
        # actually plan from.
        ik.robot_state = RobotState(
            joint_state=JointState(name=JOINTS + HAND_JOINTS, position=positions + hand_values)
        )
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

    def command_hand(
        self, positions: list[float], duration_s: float = 0.8, *, goal_tolerance_m: float = 0.001,
    ) -> dict:
        """Command both pads and require millimetre-scale endpoint evidence.

        The controller's default trajectory tolerance is wide enough to call a
        7 mm finger error successful.  That is incompatible with the S3
        contact-width gate, so the action goal and the post-action evidence
        share the same explicit 1 mm tolerance.
        """

        controller_start = len(self.hand_controller_samples)
        adapter_start = len(self.adapter_decisions)
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
        goal.goal_tolerance = [
            JointTolerance(name=name, position=goal_tolerance_m)
            for name in HAND_JOINTS
        ]
        sent = self.hand_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, sent, timeout_sec=HAND_GOAL_ACCEPT_TIMEOUT_S)
        handle = sent.result()
        if handle is None or not handle.accepted:
            return {"accepted": False, "succeeded": False, "goal_uuid": None}
        result_future = handle.get_result_async()
        # Scale the result wait with the commanded trajectory, exactly as the
        # arm path does.  A fixed 5 s wait is a wall-clock assumption, and this
        # simulator shares its GPU: a measured campaign trial reported
        # NO_ACTION_RESULT with the fingers still mid-travel at 0.0220 m of a
        # 0.017 m command, i.e. the client abandoned a trajectory that was
        # still executing and a live grasp was recorded as a close failure.
        result_timeout_s = min(60.0, max(HAND_RESULT_TIMEOUT_FLOOR_S, duration_s + HAND_RESULT_TIMEOUT_MARGIN_S))
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=result_timeout_s)
        wrapped = result_future.result()
        controller_succeeded = bool(
            wrapped and wrapped.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
        )
        # The post-goal snapshot must post-date the action result.  A fixed
        # three spins is a wall-clock assumption of exactly the kind already
        # removed from the result wait above, one step further down, and it
        # misreports staleness as a physical failure: the ADR-0009 bullet audit
        # recorded max_position_error_m 0.00713 m with the controller returning
        # SUCCEEDED against its own 1 mm tolerance, mimic tracking error
        # 1.1e-08 m, and the very next read of the same joints at 0.039999 m of
        # a 0.04 m command.  Two S3 release steps failed the same way.
        #
        # Wait for genuinely fresh deliveries instead, bounded.  The 1 mm
        # action contract and its 0.1 mm sampling slack are unchanged: if the
        # fingers really are short when the deadline expires, this still fails.
        seq_at_result = self.hand_state_seq
        settle_deadline = time.monotonic() + HAND_POST_GOAL_SETTLE_TIMEOUT_S
        actual = [self.latest_hand.get(name, math.nan) for name in HAND_JOINTS]
        max_position_error_m = math.inf
        while time.monotonic() < settle_deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
            if self.hand_state_seq - seq_at_result < HAND_POST_GOAL_FRESH_SAMPLES:
                continue
            actual = [self.latest_hand.get(name, math.nan) for name in HAND_JOINTS]
            max_position_error_m = max(
                (abs(expected - observed) for expected, observed in zip(positions, actual)),
                default=math.inf,
            )
            if max_position_error_m <= goal_tolerance_m + HAND_POST_GOAL_OBSERVATION_SLACK_M:
                break
        if math.isinf(max_position_error_m):
            actual = [self.latest_hand.get(name, math.nan) for name in HAND_JOINTS]
            max_position_error_m = max(
                (abs(expected - observed) for expected, observed in zip(positions, actual)),
                default=math.inf,
            )
        controller_samples = self.hand_controller_samples[controller_start:]
        target_reference_seen = any(
            abs(sample["physical_reference_m"] - positions[HAND_JOINTS.index(PHYSICAL_HAND_JOINT)]) <= 1e-9
            for sample in controller_samples
        )
        mimic_tracking_error_m = abs(actual[0] - actual[1])
        return {
            "accepted": True,
            # The controller evaluates its 1 mm goal tolerance at goal
            # completion; joint-state delivery can lag that instant by one
            # simulation tick.  Preserve the 1 mm action contract while
            # allowing a bounded 0.1 mm observation-sampling slack.
            "succeeded": bool(
                controller_succeeded
                and max_position_error_m <= goal_tolerance_m + HAND_POST_GOAL_OBSERVATION_SLACK_M
                and mimic_tracking_error_m <= goal_tolerance_m + HAND_POST_GOAL_OBSERVATION_SLACK_M
            ),
            "controller_result_succeeded": controller_succeeded,
            "controller_result_error_code": (
                wrapped.result.error_code if wrapped is not None else None
            ),
            "controller_result_error_string": (
                wrapped.result.error_string if wrapped is not None else "NO_ACTION_RESULT"
            ),
            "goal_uuid": bytes(handle.goal_id.uuid).hex(),
            "observed_positions_m": actual,
            "goal_tolerance_m": goal_tolerance_m,
            "post_goal_observation_slack_m": HAND_POST_GOAL_OBSERVATION_SLACK_M,
            "max_position_error_m": max_position_error_m,
            "mimic_tracking_error_m": mimic_tracking_error_m,
            "physical_controller_state_topic": PHYSICAL_HAND_CONTROLLER,
            "controller_state_sample_count": len(controller_samples),
            "controller_target_reference_seen": target_reference_seen,
            "controller_terminal_state": controller_samples[-1] if controller_samples else None,
            "adapter_decisions": self.adapter_decisions[adapter_start:],
        }

    def update_cube_scene(self, cube_xyz: list[float], *, target_id: str = "object_red_cube") -> bool:
        scene = PlanningScene(is_diff=True)
        item = CollisionObject()
        item.id = target_id
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

    def attach_cube_scene(self, cube_xyz: list[float]) -> dict:
        """Represent Gazebo's gated constraint as a MoveIt carried object.

        The runtime constraint attaches to ``panda_link7``.  Keeping the same
        link and the measured relative transform in MoveIt prevents transport
        planning from silently discarding the carried cube after attachment.
        """

        positions = [self.latest.get(name, math.nan) for name in JOINTS]
        link = self.fk_link("panda_link7", positions)
        if link is None:
            return {"applied": False, "reason": "PANDA_LINK7_FK_UNAVAILABLE"}
        relative_xyz = quaternion_rotate(
            [-link[3], -link[4], -link[5], link[6]],
            tuple(cube - origin for cube, origin in zip(cube_xyz, link[:3])),
        )
        # MoveIt rejects a single diff that removes a world object and adds an
        # AttachedCollisionObject carrying the same ID.  Commit the removal
        # first, then attach in a second transaction; this mirrors the
        # physical DetachableJoint state transition and leaves evidence for
        # either failure rather than silently skipping the lift.
        remove_scene = PlanningScene(is_diff=True)
        remove = CollisionObject()
        remove.id = "object_red_cube"
        remove.header.frame_id = "world"
        remove.operation = CollisionObject.REMOVE
        remove_scene.world.collision_objects = [remove]
        world_removed = self.apply_scene_diff(remove_scene)
        if not world_removed:
            return {
                "applied": False,
                "reason": "MOVEIT_WORLD_CUBE_REMOVE_REJECTED",
                "parent_link": "panda_link7",
                "relative_cube_xyz_m": list(relative_xyz),
            }
        scene = PlanningScene(is_diff=True)
        attached = AttachedCollisionObject()
        attached.link_name = "panda_link7"
        attached.touch_links = ["panda_link7", "panda_link8", "panda_hand", "panda_leftfinger", "panda_rightfinger"]
        attached.object.id = "object_red_cube"
        attached.object.header.frame_id = "panda_link7"
        attached.object.primitives = [
            SolidPrimitive(type=SolidPrimitive.BOX, dimensions=[CUBE_SIZE_M] * 3)
        ]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = relative_xyz
        pose.orientation.w = 1.0
        attached.object.primitive_poses = [pose]
        attached.object.operation = CollisionObject.ADD
        scene.robot_state.is_diff = True
        scene.robot_state.attached_collision_objects = [attached]
        applied = self.apply_scene_diff(scene)
        return {
            "applied": applied,
            "world_removed": world_removed,
            "parent_link": "panda_link7",
            "relative_cube_xyz_m": list(relative_xyz),
            "representation": "MOVEIT_ATTACHED_COLLISION_OBJECT",
        }

    def detach_cube_scene(self, cube_xyz: list[float]) -> dict:
        """Remove the carried-object representation and restore the world cube."""

        scene = PlanningScene(is_diff=True)
        attached = AttachedCollisionObject()
        attached.object.id = "object_red_cube"
        attached.object.operation = CollisionObject.REMOVE
        scene.robot_state.is_diff = True
        scene.robot_state.attached_collision_objects = [attached]
        removed = self.apply_scene_diff(scene)
        restored = self.update_cube_scene(cube_xyz) if removed else False
        return {
            "applied": bool(removed and restored),
            "removed_attached_object": removed,
            "restored_world_object": restored,
            "runtime_cube_xyz_m": cube_xyz,
        }

    def apply_calibration_fixture(self) -> bool:
        return self.apply_fixture(
            "work_table_calibration_fixture", CALIBRATION_FIXTURE_XYZ, CALIBRATION_FIXTURE_SIZE_M
        )

    def apply_fixture(self, fixture_id: str, xyz: list[float], size: list[float]) -> bool:
        scene = PlanningScene(is_diff=True)
        item = CollisionObject()
        item.id = fixture_id
        item.header.frame_id = "world"
        item.primitives = [
            SolidPrimitive(type=SolidPrimitive.BOX, dimensions=size)
        ]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = xyz
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

    def set_attached_cube_table_exception(self, allowed: bool) -> bool:
        """Permit the physical table-contact state only while lifting attach."""
        matrix = self.current_acm()
        if matrix is None:
            return False
        set_allowed_pair(matrix, "object_red_cube", "work_table", allowed)
        scene = PlanningScene(is_diff=True)
        scene.allowed_collision_matrix = matrix
        return self.apply_scene_diff(scene)

    def set_target_touch_exception(self, allowed: bool, *, target_id: str = "object_red_cube") -> bool:
        matrix = self.current_acm()
        if matrix is None:
            return False
        for finger in ("panda_leftfinger", "panda_rightfinger"):
            set_allowed_pair(matrix, finger, target_id, allowed)
        scene = PlanningScene(is_diff=True)
        scene.allowed_collision_matrix = matrix
        return self.apply_scene_diff(scene)

    def apply_scene_diff(self, scene: PlanningScene) -> bool:
        future = self.scene_client.call_async(ApplyPlanningScene.Request(scene=scene))
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        return bool(future.result() and future.result().success)

    def table_collision_evidence(self, *, maximum_padding_m: float) -> dict:
        """Read the exact MoveIt table primitive before a table-clearance IK.

        ``CollisionObject`` primitives do not carry a padding field.  The
        applied world object is therefore exact geometry; any non-zero object
        padding would have to be introduced outside this planning-scene payload
        and is not configured by this launch.
        """

        request = GetPlanningScene.Request()
        request.components = PlanningSceneComponents(
            components=PlanningSceneComponents.WORLD_OBJECT_GEOMETRY
        )
        future = self.scene_get_client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        result = future.result()
        table = next(
            (
                item for item in (result.scene.world.collision_objects if result is not None else [])
                if item.id == "work_table"
            ),
            None,
        )
        primitive = table.primitives[0] if table and table.primitives else None
        # MoveIt stores an object's root pose separately from each primitive's
        # local pose.  ``apply_scene`` supplies the table centre as the object
        # root and an identity primitive pose, so both are required here.
        object_pose = table.pose if table is not None else None
        primitive_pose = table.primitive_poses[0] if table and table.primitive_poses else None
        dimensions = list(primitive.dimensions) if primitive is not None else []
        center = (
            [
                object_pose.position.x + primitive_pose.position.x,
                object_pose.position.y + primitive_pose.position.y,
                object_pose.position.z + primitive_pose.position.z,
            ]
            if object_pose is not None and primitive_pose is not None else None
        )
        exact_primitive = bool(
            primitive is not None
            and primitive.type == SolidPrimitive.BOX
            and len(dimensions) == 3
            and all(abs(value - expected) <= 1e-9 for value, expected in zip(dimensions, (1.2, 0.8, 0.10)))
            and center is not None
            and all(abs(value - expected) <= 1e-9 for value, expected in zip(center, (0.0, 0.0, 0.40)))
        )
        return {
            "scene_object_id": "work_table",
            "scene_primitive_dimensions_m": dimensions,
            "scene_object_root_xyz_m": (
                [object_pose.position.x, object_pose.position.y, object_pose.position.z]
                if object_pose is not None else None
            ),
            "scene_primitive_local_xyz_m": (
                [primitive_pose.position.x, primitive_pose.position.y, primitive_pose.position.z]
                if primitive_pose is not None else None
            ),
            "scene_primitive_center_xyz_m": center,
            "scene_table_top_z_m": 0.45 if exact_primitive else None,
            "planning_scene_world_object_padding_m": PLANNING_SCENE_WORLD_OBJECT_PADDING_M,
            "padding_representation": "MoveIt CollisionObject primitive geometry has no object-padding field",
            "maximum_permitted_padding_m": maximum_padding_m,
            "exact_table_primitive_verified": exact_primitive,
            "padding_within_tip_clearance": (
                exact_primitive and PLANNING_SCENE_WORLD_OBJECT_PADDING_M <= maximum_padding_m
            ),
        }

    def move_hand_pose(
        self, pose: Pose, *, ik_seed: list[float] | None = None, ik_link: str = "panda_hand"
    ) -> dict:
        solution = self.ik(pose, seed=ik_seed, ik_link=ik_link)
        if solution is None:
            return {
                "ik_solved": False,
                "ik_error": self.last_ik_error,
                "planned": False,
                "executed": False,
            }
        trajectory = None
        plan_attempts = 0
        # OMPL has occasional nondeterministic plan rejection despite a stable
        # IK target. Retry the same collision-checked request up to five times
        # and record the actual count rather than reusing an old trajectory.
        while trajectory is None and plan_attempts < 5:
            trajectory = self.plan(solution)
            plan_attempts += 1
        if trajectory is None:
            return {
                "ik_solved": True, "ik_solution": solution, "plan_attempts": plan_attempts,
                "planned": False, "executed": False,
            }
        names = list(trajectory.joint_trajectory.joint_names)
        final = dict(zip(names, trajectory.joint_trajectory.points[-1].positions))
        expected = [float(final[name]) for name in JOINTS]
        executed, goal_uuid, samples, controller_samples, settle_s, converged = self.execute(
            trajectory, expected
        )
        observed = [self.latest.get(name, math.nan) for name in JOINTS]
        final_errors = [abs(actual - target) for actual, target in zip(observed, expected)]
        return {
            "ik_solved": True,
            "ik_solution": solution,
            "ik_seed_source": "bilateral_validated_seed" if ik_seed else "current_joint_state",
            "ik_link": ik_link,
            "plan_attempts": plan_attempts,
            "planned": True,
            "executed": executed,
            "converged": converged,
            "goal_uuid": goal_uuid,
            "joint_state_samples": len(samples),
            "controller_state_samples": len(controller_samples),
            "post_controller_settle_s": settle_s,
            "expected_final_joints": expected,
            "observed_final_joints": observed,
            "per_joint_final_error_rad": final_errors,
            "max_final_joint_error_rad": max(final_errors),
        }

    def move_hand_cartesian(
        self, pose: Pose, *, duration_s: float = 3.0, max_step_m: float = 0.005,
        max_joint_step_rad: float = 0.35, ik_link: str = "panda_hand",
        ik_seed: list[float] | None = None,
    ) -> dict:
        """Plan and execute a straight tool-frame segment to one pose.

        The ADR-0016 final descent must stay a vertical tool-axis translation.
        An OMPL joint-space plan may legally bow sideways between the same two
        endpoints, and with the finger/target ACM exception enabled such a bow
        was measured displacing the free calibration target by 10--18 mm
        before the close (ADR-0016 campaign raws 000/027/044).  The MoveIt
        cartesian service reports only a completed fraction with no failure
        cause, so this client walks the segment itself: one collision-aware
        IK per max_step_m, each seeded from the previous solution, recording
        the exact failing waypoint and IK error, plus a per-step
        joint-continuity guard that rejects IK branch jumps instead of
        silently truncating the path.
        """
        positions = [self.latest.get(name, math.nan) for name in JOINTS]
        hand_positions = [self.latest_hand.get(name, math.nan) for name in HAND_JOINTS]
        if not all(math.isfinite(value) for value in positions + hand_positions):
            return {"planned": False, "executed": False, "reason": "JOINT_STATE_UNAVAILABLE"}
        start_pose = self.fk_link(ik_link, positions)
        if start_pose is None:
            return {"planned": False, "executed": False, "reason": "START_FK_UNAVAILABLE"}
        target_xyz = [pose.position.x, pose.position.y, pose.position.z]
        segment = [target - start for target, start in zip(target_xyz, start_pose[:3])]
        length_m = math.sqrt(sum(value ** 2 for value in segment))
        steps = max(2, math.ceil(length_m / max_step_m))
        waypoints: list[list[float]] = []
        # A staged Cartesian primitive may intentionally issue multiple short
        # controller actions.  Preserve the verified branch across actions
        # when the caller supplies its prior planned endpoint; otherwise a
        # solver can select an unrelated valid branch at a waypoint boundary.
        seed = list(ik_seed) if ik_seed is not None else positions
        for index in range(1, steps + 1):
            ratio = index / steps
            waypoint = Pose()
            waypoint.position.x = start_pose[0] + segment[0] * ratio
            waypoint.position.y = start_pose[1] + segment[1] * ratio
            waypoint.position.z = start_pose[2] + segment[2] * ratio
            waypoint.orientation = pose.orientation
            solution = self.ik(waypoint, seed=seed, ik_link=ik_link)
            if solution is None:
                return {
                    "planned": False, "executed": False,
                    "reason": "CARTESIAN_WAYPOINT_IK_REJECTED",
                    "failed_waypoint_index": index, "waypoint_count": steps,
                    "fraction": (index - 1) / steps,
                    "failed_waypoint_z_m": waypoint.position.z,
                    "ik_error": self.last_ik_error,
                }
            joint_step = max(abs(current - previous) for current, previous in zip(solution, seed))
            if joint_step > max_joint_step_rad:
                return {
                    "planned": False, "executed": False,
                    "reason": "CARTESIAN_JOINT_JUMP_REJECTED",
                    "failed_waypoint_index": index, "waypoint_count": steps,
                    "fraction": (index - 1) / steps,
                    "max_observed_joint_step_rad": joint_step,
                    "max_joint_step_rad": max_joint_step_rad,
                }
            waypoints.append(solution)
            seed = solution
        trajectory = RobotTrajectory()
        trajectory.joint_trajectory.joint_names = list(JOINTS)
        points = [JointTrajectoryPoint(positions=list(positions), time_from_start=Duration(sec=0, nanosec=0))]
        for index, solution in enumerate(waypoints, start=1):
            seconds = duration_s * index / steps
            points.append(JointTrajectoryPoint(
                positions=list(solution),
                time_from_start=Duration(sec=int(seconds), nanosec=int((seconds - int(seconds)) * 1e9)),
            ))
        trajectory.joint_trajectory.points = points
        expected = list(waypoints[-1])
        executed, goal_uuid, samples, controller_samples, settle_s, converged = self.execute(
            trajectory, expected
        )
        observed = [self.latest.get(name, math.nan) for name in JOINTS]
        final_errors = [abs(actual - target) for actual, target in zip(observed, expected)]
        return {
            "planned": True, "cartesian": True, "fraction": 1.0,
            "planning_method": "SEEDED_PER_WAYPOINT_COLLISION_AWARE_IK",
            "ik_seed_source": "caller_previous_cartesian_endpoint" if ik_seed is not None else "current_joint_state",
            "max_step_m": max_step_m, "duration_s": duration_s, "point_count": len(points),
            "executed": executed, "converged": converged, "goal_uuid": goal_uuid,
            "joint_state_samples": len(samples),
            "controller_state_samples": len(controller_samples),
            "post_controller_settle_s": settle_s,
            "expected_final_joints": expected, "observed_final_joints": observed,
            "per_joint_final_error_rad": final_errors,
            "max_final_joint_error_rad": max(final_errors),
        }

    def move_joint_target(self, target: list[float]) -> dict:
        """Plan and execute a collision-checked retreat through MoveIt."""
        trajectory = self.plan(target)
        plan_attempts = 1
        if trajectory is None:
            trajectory = self.plan(target)
            plan_attempts += 1
        if trajectory is None:
            return {"planned": False, "executed": False, "plan_attempts": plan_attempts}
        names = list(trajectory.joint_trajectory.joint_names)
        final = dict(zip(names, trajectory.joint_trajectory.points[-1].positions))
        expected = [float(final[name]) for name in JOINTS]
        executed, goal_uuid, samples, controller_samples, settle_s, converged = self.execute(
            trajectory, expected
        )
        return {
            "planned": True,
            "plan_attempts": plan_attempts,
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
            translation = quaternion_rotate(pose[3:], PAD_CENTER_IN_FINGER_M[side])
            center = [pose[index] + translation[index] for index in range(3)]
            separation = aabb_separation(center, PAD_SIZE_M, cube_xyz, (CUBE_SIZE_M,) * 3)
            output[side] = {"link_pose": pose, "pad_center_world": center, "aabb_separation_m": separation}
            separations.append(separation)
        output["minimum_pad_cube_aabb_separation_m"] = min(separations) if separations else None
        simulator: dict[str, dict | float | None] = {}
        simulator_separations = []
        for side, link in (("left", "panda_leftfinger"), ("right", "panda_rightfinger")):
            pose = runtime_link_pose(link)
            if pose is None:
                simulator[side] = None
                continue
            roll, pitch, yaw = pose[3:]
            cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
            cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
            cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
            quaternion = [sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy,
                          cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]
            translation = quaternion_rotate(quaternion, PAD_CENTER_IN_FINGER_M[side])
            center = [pose[index] + translation[index] for index in range(3)]
            separation = aabb_separation(center, PAD_SIZE_M, cube_xyz, (CUBE_SIZE_M,) * 3)
            simulator[side] = {
                "link_pose_world_xyz_rpy": pose,
                "pad_center_world": center,
                "aabb_separation_m": separation,
            }
            simulator_separations.append(separation)
        output["gazebo_link_pose_evidence"] = simulator
        output["gazebo_minimum_pad_cube_aabb_separation_m"] = (
            min(simulator_separations) if simulator_separations else None
        )
        return output

    def gripper_frame_corridor_evidence(
        self, cube_xyz: list[float], *, maximum_transverse_error_m: float,
        finger_center_line_anchor_m: list[float] | None = None,
    ) -> dict:
        """Produce S3 corridor evidence in the hand frame, not world axes."""

        positions = [self.latest.get(name, math.nan) for name in JOINTS]
        if not all(math.isfinite(value) for value in positions):
            return {
                "coordinate_frame": "panda_hand",
                "target_in_grasp_corridor": False,
                "reason": "JOINT_STATE_UNAVAILABLE",
            }
        hand = self.fk_link("panda_hand", positions)
        if hand is None:
            return {
                "coordinate_frame": "panda_hand",
                "target_in_grasp_corridor": False,
                "reason": "HAND_FK_UNAVAILABLE",
            }
        evidence = gripper_frame_corridor(
            hand[:3], hand[3:], cube_xyz, threshold_m=maximum_transverse_error_m,
            finger_center_line_anchor_m=finger_center_line_anchor_m,
        )
        evidence["hand_pose_world_xyzw"] = hand
        return evidence

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


def hand_pose(
    cube_xyz: list[float], *, y_offset: float = 0.0,
    finger_target_inset_m: float = CALIBRATION_FINGER_TARGET_INSET_M,
    vertical_standoff_m: float = 0.0,
    contact_vertical_offset_m: float = 0.0,
) -> Pose:
    """Runtime-oracle inline-pad contact pose, derived from ADR-0016 geometry."""
    pose = Pose()
    # With RPY [pi, 0, 0], the inline main pad is vertical and centred 10 cm
    # below the hand.  Its 8 cm height spans the cube's sidewall while its
    # local +/-Y closure faces provide the individual/bilateral S0 contacts.
    # The named-pad offset places the selected open finger 2 mm into that
    # sidewall; no privileged online input is involved.
    pose.position.x = cube_xyz[0]
    pose.position.y = cube_xyz[1] + y_offset
    pose.position.z = (
        cube_xyz[2] + FINGER_ROOT_Z_M - finger_target_inset_m
        + vertical_standoff_m + contact_vertical_offset_m
    )
    # RPY [pi, 0, 0] directs local +Z (the inline tool/finger axis) downward.
    pose.orientation.x = 1.0
    pose.orientation.w = 0.0
    return pose


def calibration_retreat_pose(cube_xyz: list[float], *, y_offset: float) -> Pose:
    """Lift from the runtime target before restoring normal ACM checks."""
    pose = Pose()
    pose.position.x = cube_xyz[0]
    pose.position.y = cube_xyz[1] + y_offset
    pose.position.z = cube_xyz[2] + CONTACT_RETREAT_HEIGHT_M
    pose.orientation.x = 1.0
    pose.orientation.w = 0.0
    return pose


def pose_vector(pose: Pose) -> list[float]:
    return [
        pose.position.x, pose.position.y, pose.position.z,
        pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w,
    ]


def table_touch_pose(cube_xyz: list[float]) -> Pose:
    pose = Pose()
    pose.position.x = -0.25
    pose.position.y = -0.25
    pose.position.z = TABLE_TOUCH_HAND_Z_M
    pose.orientation.x = 1.0
    pose.orientation.w = 0.0
    return pose


def table_touch_precontact_pose(cube_xyz: list[float]) -> Pose:
    """Collision-free start for the S0 finger--table sensor condition."""

    pose = table_touch_pose(cube_xyz)
    pose.position.z += TABLE_TOUCH_PRECONTACT_STANDOFF_M
    return pose


def classify_contacts(events: dict[str, list[dict]], *, target_model: str = "object_red_cube") -> dict:
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
    left_target_times = channel_timestamps("left", target_model)
    right_target_times = channel_timestamps("right", target_model)
    cube_channel = "cube_bilateral" if target_model == "object_red_cube_bilateral" else "cube"
    cube_target_times = channel_timestamps(cube_channel, target_model)
    overlap = 0.0
    if left_target_times and right_target_times:
        overlap = max(
            0.0,
            min(left_target_times[-1], right_target_times[-1])
            - max(left_target_times[0], right_target_times[0]),
        )

    return {
        "target_model": target_model,
        "left_target": channel_has("left", target_model),
        "right_target": channel_has("right", target_model),
        "target_cube_events": len(cube_target_times),
        "left_table": channel_has("left", "work_table"),
        "right_table": channel_has("right", "work_table"),
        "cube_table": channel_has("cube", "work_table"),
        "cube_environment_table": channel_has("cube_environment", "work_table"),
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
            # The franka-copy pads keep ADR-0008's pose-induced, fixed-aperture
            # labels; each collision face sits 6.5 mm proud of its finger-link
            # y=0 plane.  Static S0 targets have no dead band, so the named-pad
            # inset stays 2 mm of the modelled skin:
            # |offset| = (q - 0.0065) - (cube_half - inset) = 0.0335 - 0.023.
            # The free bilateral cube needs the measured dynamic-pair overlap:
            # 27 mm per finger targets the skin 4.5 mm inside each sidewall
            # while the achieved steady width stays inside the public window.
            [(f"left_{index}", "left", 0.0105, [0.040, 0.040]) for index in range(1, 4)]
            + [(f"right_{index}", "right", -0.0105, [0.040, 0.040]) for index in range(1, 4)]
            + [(f"bilateral_{index}", "bilateral", 0.0, [0.027, 0.027]) for index in range(1, 4)]
        )
        scope = os.environ.get("M1A_CALIBRATION_SCOPE", "full")
        selected_label = os.environ.get("M1A_CALIBRATION_LABEL", "")
        if scope == "nonbilateral":
            specifications = [item for item in specifications if item[1] != "bilateral"]
        elif scope == "bilateral":
            repetition = int(os.environ.get("M1A_CALIBRATION_REPETITION", "1"))
            specifications = [item for item in specifications if item[0] == f"bilateral_{repetition}"]
        elif scope == "one":
            specifications = [item for item in specifications if item[0] == selected_label]
        elif scope != "full":
            raise ValueError(f"unsupported M1A_CALIBRATION_SCOPE: {scope}")
        for label, expected, y_offset, finger_target in specifications:
            initialization = calibration_initialization()
            target_model = "object_red_cube_bilateral" if expected == "bilateral" else "object_red_cube"
            cube = runtime_bilateral_cube_pose() if expected == "bilateral" else runtime_cube_pose()
            if cube is None:
                trials.append(
                    {
                        "label": label, "expected": expected,
                        "reason": "CALIBRATION_INITIALIZATION_OR_ORACLE_UNAVAILABLE",
                        "initialization": initialization,
                    }
                )
                continue
            client.update_cube_scene(cube["xyz"], target_id=target_model)
            exception_set = client.set_target_touch_exception(True, target_id=target_model)
            target_pose = hand_pose(cube["xyz"], y_offset=y_offset)
            if expected in {"left", "right"}:
                # Keep the symmetric aperture fixed across the entire named-pad
                # contact window.  Motion causes the label; the following
                # action result records the physical command and mimic state.
                hand_result = client.command_hand(finger_target)
                motion = client.move_hand_pose(target_pose) if exception_set else {
                    "ik_solved": False, "planned": False, "executed": False
                }
            else:
                # Do not push the free cube with an open hand.  First stop
                # 1 mm short, pre-close without contact to the expected
                # 68 mm total width, then make the short contact approach.
                # The final 10 mm/side command must settle in the 45--70 mm
                # total physical width window while both pads remain in touch.
                precontact_pose = hand_pose(
                    cube["xyz"], y_offset=y_offset,
                    finger_target_inset_m=-BILATERAL_PRECONTACT_CLEARANCE_M,
                    vertical_standoff_m=BILATERAL_PRECONTACT_VERTICAL_STANDOFF_M,
                    contact_vertical_offset_m=BILATERAL_CONTACT_VERTICAL_OFFSET_M,
                )
                target_pose = hand_pose(
                    cube["xyz"], y_offset=y_offset,
                    finger_target_inset_m=BILATERAL_FINAL_FINGER_INSET_M,
                    contact_vertical_offset_m=BILATERAL_CONTACT_VERTICAL_OFFSET_M,
                )
                precontact_motion = client.move_hand_pose(
                    precontact_pose, ik_seed=calibration_bilateral_branch_seed()
                ) if exception_set else {
                    "ik_solved": False, "planned": False, "executed": False
                }
                cube_after_precontact = runtime_bilateral_cube_pose()
                precontact_ready = (
                    precontact_motion.get("executed") is True
                    and precontact_motion.get("converged") is True
                )
                precontact_close = client.command_hand([BILATERAL_PRECONTACT_FINGER_M] * 2) if precontact_ready else {
                    "accepted": False,
                    "succeeded": False,
                    "controller_result_succeeded": False,
                    "controller_result_error_string": "PRECONTACT_NOT_CONVERGED",
                    "observed_positions_m": [],
                }
                motion = client.move_hand_pose(target_pose) if (
                    precontact_ready and precontact_close.get("succeeded") is True
                ) else {
                    "ik_solved": False, "planned": False, "executed": False
                }
                cube_before_close = runtime_bilateral_cube_pose()
                contact_ready = motion.get("executed") is True and motion.get("converged") is True
                hand_result = client.command_hand(finger_target) if contact_ready else {
                    "accepted": False,
                    "succeeded": False,
                    "controller_result_succeeded": False,
                    "controller_result_error_string": "BILATERAL_CONTACT_POSE_NOT_CONVERGED",
                    "observed_positions_m": [],
                }
            # S0 labels a settled contact condition.  Do not include transient
            # contacts while a non-selected pad crosses the target during the
            # collision-checked arm trajectory; begin the evidence window only
            # after the final pose and hand command have converged.
            start = {name: len(events) for name, events in client.contacts.items()}
            client.contact_window(0.45)
            events = {name: client.contacts[name][start[name]:] for name in client.contacts}
            cube_after = runtime_bilateral_cube_pose() if expected == "bilateral" else runtime_cube_pose()
            pad_at_close = client.pad_evidence(cube["xyz"])
            # Leave the target before restoring its normal collision policy.
            # Without this retreat the next independent condition starts from
            # physical penetration, making a failed plan look like a sensor fault.
            client.command_hand([0.04, 0.04])
            retreat_pose = calibration_retreat_pose(cube["xyz"], y_offset=y_offset)
            retreat = client.move_hand_pose(retreat_pose) if exception_set else {
                "planned": False, "executed": False
            }
            target_exception_restored = client.set_target_touch_exception(False, target_id=target_model)
            exception_restored = target_exception_restored
            trials.append(
                {
                    "label": label,
                    "expected": expected,
                    "target_model": target_model,
                    "target_physics": "FREE_DYNAMIC_SELF_CENTERING" if expected == "bilateral" else "STATIC_SINGLE_PAD_CALIBRATION",
                    "initialization": initialization,
                    "calibration_finger_target_inset_m": CALIBRATION_FINGER_TARGET_INSET_M,
                    "cube_pose": cube,
                    "cube_pose_after_action": cube_after,
                    "target_hand_pose": pose_vector(target_pose),
                    "precontact_motion": precontact_motion if expected == "bilateral" else None,
                    "precontact_hand_command": precontact_close if expected == "bilateral" else None,
                    "cube_pose_after_precontact": cube_after_precontact if expected == "bilateral" else None,
                    "cube_pose_before_close": cube_before_close if expected == "bilateral" else None,
                    "motion": motion,
                    "retreat": retreat,
                    "retreat_hand_pose": pose_vector(retreat_pose),
                    "hand_command": {"positions_m": finger_target, **hand_result},
                    "bilateral_steady_gripper_width_m": (
                        sum(hand_result.get("observed_positions_m", [])) if expected == "bilateral" else None
                    ),
                    "hand_command_semantics": (
                        "POSE_INDUCED_FIXED_SYMMETRIC_APERTURE"
                        if expected in {"left", "right"}
                        else "SYMMETRIC_MIMIC_CLOSE"
                    ),
                    "calibration_only_allowed_collision_pairs": [
                        ["panda_leftfinger", target_model],
                        ["panda_rightfinger", target_model],
                    ],
                    "target_touch_exception_restored": exception_restored,
                    "pad_evidence": pad_at_close,
                    "contacts": classify_contacts(events, target_model=target_model),
                }
            )

        client.command_hand([0.04, 0.04])
        environment_indices = (
            range(1, 3) if scope not in {"bilateral", "one"}
            else ([int(selected_label.rsplit("_", 1)[1])] if selected_label.startswith("object_environment_") else [])
        )
        for index in environment_indices:
            initialization = calibration_initialization()
            cube = runtime_cube_pose()
            events = client.contact_window(0.45)
            cube_after = runtime_cube_pose()
            trials.append(
                {
                    "label": f"object_environment_{index}",
                    "expected": "target_equivalent_table_without_finger",
                    "initialization": initialization,
                    "cube_pose": cube,
                    "cube_pose_after_action": cube_after,
                    "pad_evidence": client.pad_evidence(cube["xyz"]) if cube else None,
                    "contacts": classify_contacts(events),
                }
            )

        table_indices = (
            range(1, 3) if scope not in {"bilateral", "one"}
            else ([int(selected_label.rsplit("_", 1)[1])] if selected_label.startswith("table_") else [])
        )
        for index in table_indices:
            cube = runtime_cube_pose()
            if cube is None:
                trials.append({"label": f"table_{index}", "expected": "finger_table", "reason": "RUNTIME_CUBE_POSE_UNAVAILABLE"})
                continue
            # Arrive above the table with ordinary collision checking, then
            # make the only permitted finger--table interaction as a seeded,
            # straight vertical descent. A direct OMPL path to the embedded
            # endpoint can stall on a branch-dependent table collision before
            # either finger reaches the sensor condition.
            precontact = client.move_hand_pose(table_touch_precontact_pose(cube["xyz"]))
            exception_set = client.set_table_touch_exception(True)
            motion = client.move_hand_cartesian(table_touch_pose(cube["xyz"])) if (
                exception_set and precontact.get("executed") and precontact.get("converged")
            ) else {
                "planned": False, "executed": False,
                "reason": "TABLE_PRECONTACT_OR_EXCEPTION_UNAVAILABLE",
            }
            start = {name: len(events) for name, events in client.contacts.items()}
            client.contact_window(0.45)
            events = {name: client.contacts[name][start[name]:] for name in client.contacts}
            table_contact_pad_evidence = client.pad_evidence(cube["xyz"])
            client.command_hand([0.04, 0.04])
            retreat = client.move_joint_target(TARGETS[0][1]) if exception_set else {
                "planned": False, "executed": False
            }
            trials.append(
                {
                    "label": f"table_{index}", "expected": "finger_table",
                    "cube_pose": cube, "precontact_motion": precontact, "motion": motion, "retreat": retreat,
                    "table_precontact_hand_pose": pose_vector(table_touch_precontact_pose(cube["xyz"])),
                    "table_contact_hand_pose": pose_vector(table_touch_pose(cube["xyz"])),
                    "table_contact_pad_evidence": table_contact_pad_evidence,
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
            # In a one-condition process the simulator is torn down after the
            # evidence window, so a failed retreat cannot contaminate another
            # trial.  It remains recorded, but is not a false negative.
            cleanup_valid = scope == "one" or bool(trial.get("retreat", {}).get("executed"))
            if expected == "left":
                return bool(
                    trial.get("motion", {}).get("executed")
                    and cleanup_valid
                    and trial.get("target_touch_exception_restored")
                    and contacts.get("left_target")
                    and not contacts.get("right_target")
                )
            if expected == "right":
                return bool(
                    trial.get("motion", {}).get("executed")
                    and cleanup_valid
                    and trial.get("target_touch_exception_restored")
                    and contacts.get("right_target")
                    and not contacts.get("left_target")
                )
            if expected == "bilateral":
                width = trial.get("bilateral_steady_gripper_width_m")
                return bool(
                    trial.get("motion", {}).get("executed")
                    and cleanup_valid
                    and trial.get("target_touch_exception_restored")
                    and contacts.get("left_target")
                    and contacts.get("right_target")
                    and contacts.get("target_cube_events", 0) > 0
                    and contacts.get("bilateral_overlap_s", 0.0) >= 0.1
                    and contacts.get("left_target_unique_samples", 0) >= 3
                    and contacts.get("right_target_unique_samples", 0) >= 3
                    and width is not None
                    and BILATERAL_STEADY_WIDTH_RANGE_M[0] <= width <= BILATERAL_STEADY_WIDTH_RANGE_M[1]
                )
            if expected == "finger_table":
                return contacts.get("left_table") or contacts.get("right_table")
            if expected == "target_equivalent_table_without_finger":
                return (
                    contacts.get("cube_environment_table")
                    and not contacts.get("left_target")
                    and not contacts.get("right_target")
                )
            return not contacts.get("left_target") and not contacts.get("right_target")

        for trial in trials:
            trial["passed"] = bool(passed(trial))
        positives = [trial for trial in trials if trial["expected"] in {"left", "right", "bilateral"}]
        condition_trials = [trial for trial in trials if trial["label"] != "idle"]
        status = "CONTACT_TELEMETRY_CALIBRATED" if len(condition_trials) == 13 and all(trial["passed"] for trial in trials) else "CONTACT_TELEMETRY_PARTIAL"
        print(
            json.dumps(
                {
                    "status": status,
                    "reason": f"{sum(trial['passed'] for trial in condition_trials)}/13 approved conditions passed; {sum(trial['passed'] for trial in positives)}/9 finger-target positive windows passed.",
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
