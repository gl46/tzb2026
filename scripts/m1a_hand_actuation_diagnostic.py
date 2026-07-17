#!/usr/bin/env python3
"""Bounded, evidence-preserving diagnosis of the two Gazebo hand channels."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from control_msgs.msg import JointTolerance, JointTrajectoryControllerState
from rclpy.qos import QoSProfile
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from m1a_contact_calibration_client import (  # noqa: E402
    CalibrationClient,
    HAND_JOINTS,
    classify_contacts,
    runtime_link_pose,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORLD = "xh_p0_pick_place"
MODEL = "panda_controller"
GOAL_TOLERANCE_M = 0.001
SAMPLE_PERIOD_S = 0.20
RESULT_TIMEOUT_S = 5.0
FRESH_QOS = QoSProfile(depth=1)

PROBES = (
    ("open", [0.040, 0.040]),
    ("q1_close", [0.010, 0.040]),
    ("reopen_after_q1", [0.040, 0.040]),
    ("q2_close", [0.040, 0.010]),
    ("reopen_after_q2", [0.040, 0.040]),
    ("asymmetric_crosswire", [0.015, 0.035]),
)


def hand_positions(client: CalibrationClient) -> list[float]:
    return [client.diagnostic_hand.get(name, math.nan) for name in HAND_JOINTS]


def install_fresh_hand_observers(client: CalibrationClient) -> None:
    """Bypass the high-rate contact queue with depth-one state observers."""

    client.diagnostic_hand = {}
    client.diagnostic_controller_samples = []

    def on_joint_state(message: JointState) -> None:
        positions = dict(zip(message.name, message.position))
        if all(name in positions for name in HAND_JOINTS):
            client.diagnostic_hand = {name: float(positions[name]) for name in HAND_JOINTS}

    def on_controller_state(message: JointTrajectoryControllerState) -> None:
        reference = dict(zip(message.joint_names, message.reference.positions))
        feedback = dict(zip(message.joint_names, message.feedback.positions))
        output = dict(zip(message.joint_names, message.output.positions))
        if not all(name in reference and name in feedback for name in HAND_JOINTS):
            return
        client.diagnostic_controller_samples.append({
            "timestamp_s": message.header.stamp.sec + message.header.stamp.nanosec * 1e-9,
            "q_reference_m": [float(reference[name]) for name in HAND_JOINTS],
            "q_feedback_m": [float(feedback[name]) for name in HAND_JOINTS],
            "q_output_m": [float(output[name]) for name in HAND_JOINTS] if all(name in output for name in HAND_JOINTS) else None,
        })

    client.create_subscription(JointState, "/joint_states", on_joint_state, FRESH_QOS)
    client.create_subscription(
        JointTrajectoryControllerState,
        "/panda_hand_controller/controller_state",
        on_controller_state,
        FRESH_QOS,
    )


def world_snapshot(client: CalibrationClient, elapsed_s: float) -> dict:
    """Collect direct Gazebo link poses and ROS joint state in one record."""

    return {
        "elapsed_wall_s": elapsed_s,
        "joint_state_m": hand_positions(client),
        "leftfinger_world_xyz_rpy": reliable_link_pose("panda_leftfinger"),
        "rightfinger_world_xyz_rpy": reliable_link_pose("panda_rightfinger"),
    }


def reliable_link_pose(link: str) -> list[float] | None:
    """Retry the CLI oracle: transient transport misses are not physical motion."""

    for _ in range(3):
        try:
            pose = runtime_link_pose(link)
        except subprocess.TimeoutExpired:
            pose = None
        if pose is not None:
            return pose
    return None


def xyz_displacement(first: list[float] | None, last: list[float] | None) -> float | None:
    if first is None or last is None:
        return None
    return math.dist(first[:3], last[:3])


def maximum_link_displacement(samples: list[dict], key: str) -> float | None:
    poses = [sample.get(key) for sample in samples if sample.get(key) is not None]
    if len(poses) < 2:
        return None
    return max(math.dist(poses[0][:3], pose[:3]) for pose in poses[1:])


def controller_goal(
    client: CalibrationClient, label: str, positions: list[float], *, duration_s: float = 0.8,
) -> dict:
    """Run a hand command while sampling Gazebo link poses throughout it."""

    controller_start = len(client.diagnostic_controller_samples)
    contact_start = {name: len(events) for name, events in client.contacts.items()}
    before = world_snapshot(client, 0.0)
    goal = FollowJointTrajectory.Goal()
    goal.trajectory = JointTrajectory(joint_names=HAND_JOINTS)
    seconds = int(duration_s)
    goal.trajectory.points = [
        JointTrajectoryPoint(
            positions=positions,
            time_from_start=Duration(sec=seconds, nanosec=int((duration_s - seconds) * 1e9)),
        )
    ]
    goal.goal_tolerance = [
        JointTolerance(name=name, position=GOAL_TOLERANCE_M) for name in HAND_JOINTS
    ]
    sent = client.hand_client.send_goal_async(goal)
    rclpy.spin_until_future_complete(client, sent, timeout_sec=3.0)
    handle = sent.result()
    if handle is None or not handle.accepted:
        return {
            "label": label,
            "command_positions_m": positions,
            "accepted": False,
            "world_pose_samples": [before],
        }

    result_future = handle.get_result_async()
    started = time.monotonic()
    samples = [before]
    next_sample = SAMPLE_PERIOD_S
    deadline = started + RESULT_TIMEOUT_S
    while not result_future.done() and time.monotonic() < deadline:
        rclpy.spin_once(client, timeout_sec=0.02)
        elapsed = time.monotonic() - started
        if elapsed >= next_sample:
            samples.append(world_snapshot(client, elapsed))
            next_sample += SAMPLE_PERIOD_S
    rclpy.spin_once(client, timeout_sec=0.0)
    elapsed = time.monotonic() - started
    samples.append(world_snapshot(client, elapsed))
    wrapped = result_future.result() if result_future.done() else None
    controller_succeeded = bool(
        wrapped and wrapped.result.error_code == FollowJointTrajectory.Result.SUCCESSFUL
    )
    after = samples[-1]
    actual = after["joint_state_m"]
    max_error = max(
        (abs(expected - observed) for expected, observed in zip(positions, actual)),
        default=math.inf,
    )
    controller_samples = client.diagnostic_controller_samples[controller_start:]
    contacts = {
        name: events[contact_start[name]:] for name, events in client.contacts.items()
    }
    return {
        "label": label,
        "command_positions_m": positions,
        "accepted": True,
        "goal_uuid": bytes(handle.goal_id.uuid).hex(),
        "controller_result_succeeded": controller_succeeded,
        "endpoint_within_explicit_1mm_m": max_error <= GOAL_TOLERANCE_M,
        "max_endpoint_error_m": max_error,
        "controller_terminal_state": controller_samples[-1] if controller_samples else None,
        "controller_state_sample_count": len(controller_samples),
        "contact_observation": classify_contacts(contacts),
        "world_pose_samples": samples,
        "left_link_world_displacement_m": maximum_link_displacement(samples, "leftfinger_world_xyz_rpy"),
        "right_link_world_displacement_m": maximum_link_displacement(samples, "rightfinger_world_xyz_rpy"),
    }


def xml_joint_description(joint: ET.Element | None) -> dict | None:
    if joint is None:
        return None
    axis = joint.find("axis")
    limit = axis.find("limit") if axis is not None else None
    fields = {
        "type": joint.attrib.get("type"),
        "parent": joint.findtext("parent"),
        "child": joint.findtext("child"),
        "axis_xyz": axis.findtext("xyz") if axis is not None else None,
        "lower": limit.findtext("lower") if limit is not None else None,
        "upper": limit.findtext("upper") if limit is not None else None,
        "effort": limit.findtext("effort") if limit is not None else None,
        "velocity": limit.findtext("velocity") if limit is not None else None,
    }
    return fields


def model_joint_descriptions(root: ET.Element, model_name: str | None = None) -> dict[str, dict | None]:
    models = root.findall(".//model")
    model = next(
        (item for item in models if model_name is None or item.attrib.get("name") == model_name), root,
    )
    return {
        name: xml_joint_description(next((joint for joint in model.findall(".//joint") if joint.attrib.get("name") == name), None))
        for name in HAND_JOINTS
    }


def normalized_joint_description(description: dict | None) -> dict | None:
    """Ignore floating point print noise when comparing spawned SDF axis fields."""

    if description is None:
        return None

    def normalize(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return " ".join(f"{float(item):.9g}" for item in value.split())
        except ValueError:
            return value

    return {key: normalize(value) if key in {"axis_xyz", "lower", "upper", "effort", "velocity"} else value
            for key, value in description.items()}


def generated_world_sdf() -> str | None:
    result = subprocess.run(
        [
            "gz", "service", "-s", f"/world/{WORLD}/generate_world_sdf",
            "--reqtype", "gz.msgs.SdfGeneratorConfig", "--reptype", "gz.msgs.StringMsg",
            "--timeout", "25000", "--req",
            "global_entity_gen_config { expand_include_tags { data: true } resources_use_absolute_paths { data: true } }",
        ],
        check=False, capture_output=True, text=True, timeout=30,
    )
    line = next((line for line in result.stdout.splitlines() if line.startswith("data: ")), None)
    if result.returncode != 0 or line is None:
        return None
    encoded = line.removeprefix("data: ")
    try:
        return json.loads(encoded)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(encoded)
        except (SyntaxError, ValueError):
            return None


def sdf_evidence() -> dict:
    """Compare the installed conversion to the live spawned model without mutation."""

    installed_urdf = PROJECT_ROOT / "robot_ws/install/xh_sim/share/xh_sim/urdf/panda_controlled.urdf"
    source_urdf = PROJECT_ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
    source_conversion = subprocess.run(
        ["gz", "sdf", "-p", str(installed_urdf)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    spawned = generated_world_sdf()
    evidence: dict = {
        "installed_urdf_sha256": hashlib.sha256(installed_urdf.read_bytes()).hexdigest(),
        "source_urdf_sha256": hashlib.sha256(source_urdf.read_bytes()).hexdigest(),
        "source_conversion_available": source_conversion.returncode == 0,
        "spawned_world_sdf_available": spawned is not None,
    }
    if source_conversion.returncode != 0 or spawned is None:
        return evidence
    try:
        source_root = ET.fromstring(source_conversion.stdout)
        spawned_root = ET.fromstring(spawned)
    except ET.ParseError:
        evidence["xml_parse_failed"] = True
        return evidence
    source_joints = model_joint_descriptions(source_root)
    spawned_joints = model_joint_descriptions(spawned_root, MODEL)
    plugins = []
    for plugin in spawned_root.findall(".//plugin"):
        serialized = ET.tostring(plugin, encoding="unicode")
        plugins.append({
            "name": plugin.attrib.get("name"),
            "filename": plugin.attrib.get("filename"),
            "references_finger_link_or_joint": any(token in serialized for token in (*HAND_JOINTS, "panda_leftfinger", "panda_rightfinger")),
        })
    evidence.update({
        "spawned_world_sdf_sha256": hashlib.sha256(spawned.encode()).hexdigest(),
        "source_joint_blocks": source_joints,
        "spawned_joint_blocks": spawned_joints,
        "joint_block_semantic_match_after_numeric_tolerance": {
            name: normalized_joint_description(source_joints[name]) == normalized_joint_description(spawned_joints[name])
            for name in HAND_JOINTS
        },
        "spawned_model_plugins": plugins,
    })
    return evidence


def diagnosis(probes: list[dict]) -> dict:
    by_label = {item["label"]: item for item in probes}
    q1 = by_label.get("q1_close", {})
    crosswire = by_label.get("asymmetric_crosswire", {})
    return {
        "q1_close_joint_feedback_m": (q1.get("controller_terminal_state") or {}).get("q_feedback_m"),
        "q1_close_left_link_world_displacement_m": q1.get("left_link_world_displacement_m"),
        "q1_world_pose_shows_no_close": bool(
            (q1.get("left_link_world_displacement_m") or 0.0) <= 0.001
        ),
        "asymmetric_command_m": crosswire.get("command_positions_m"),
        "asymmetric_joint_feedback_m": (crosswire.get("controller_terminal_state") or {}).get("q_feedback_m"),
        "right_world_displacement_for_asymmetric_command_m": crosswire.get("right_link_world_displacement_m"),
        "right_world_pose_matches_0p005m_asymmetric_motion": bool(
            crosswire.get("right_link_world_displacement_m") is not None
            and abs(crosswire["right_link_world_displacement_m"] - 0.005) <= GOAL_TOLERANCE_M
        ),
    }


def main() -> int:
    rclpy.init()
    client = CalibrationClient()
    try:
        install_fresh_hand_observers(client)
        if not client.hand_client.wait_for_server(timeout_sec=20.0):
            print(json.dumps({"status": "HAND_ACTUATION_DIAGNOSTIC_BLOCKED", "reason": "HAND_ACTION_UNAVAILABLE"}))
            return 2
        deadline = time.monotonic() + 10.0
        while len(client.diagnostic_hand) != len(HAND_JOINTS) and time.monotonic() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        if len(client.diagnostic_hand) != len(HAND_JOINTS):
            print(json.dumps({"status": "HAND_ACTUATION_DIAGNOSTIC_BLOCKED", "reason": "HAND_JOINT_STATE_UNAVAILABLE"}))
            return 2
        started = datetime.now(timezone.utc).isoformat()
        sdf = sdf_evidence()
        probes = [controller_goal(client, label, positions) for label, positions in PROBES]
        print(json.dumps({
            "status": "HAND_ACTUATION_DIAGNOSTIC_COMPLETED",
            "diagnostic_completed": True,
            "started_at_utc": started,
            "scope": "APPROVED_OPTION_1_DIAGNOSTICS_NO_OBJECT_CONTACT_NO_PERSISTENT_MODEL_CHANGE",
            "goal_tolerance_m": GOAL_TOLERANCE_M,
            "sdf_evidence": sdf,
            "probes": probes,
            "conclusions": diagnosis(probes),
        }))
        return 0
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
