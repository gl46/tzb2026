#!/usr/bin/env python3
"""One real S3 contact-gated constrained pick/place episode.

This client never uses a Gazebo pose write.  The sole Gazebo control outside
ROS actions is the DetachableJoint attach/detach topic, and attach is sent only
after every required contact-gate condition has passed.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import rclpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xh_agent.grasp.contact_gate import ContactGateInput, evaluate_contact_gate  # noqa: E402
from xh_agent.grasp.contact_telemetry import ContactEvent, bilateral_contact_window  # noqa: E402
from xh_agent.grasp.release_gate import ReleaseEvidence, evaluate_release  # noqa: E402
from m1a_contact_calibration_client import CalibrationClient, classify_contacts, runtime_cube_pose, runtime_link_pose  # noqa: E402
from m1a_friction_trial_client import collision_checked_orientation_approach, pose_message  # noqa: E402
from m1a_moveit_execution_client import JOINTS  # noqa: E402


ATTACH_TOPIC = "/xh/p0/red_cube/attach"
DETACH_TOPIC = "/xh/p0/red_cube/detach"
GRASP_STATE_TOPIC = "/xh/p0/red_cube/grasp_state"
BIN_CENTER_XYZ_M = [0.217366447885, -0.249990627453, 0.45]
BIN_HALF_INTERIOR_M = 0.12
BIN_CUBE_CENTER_Z_RANGE_M = (0.474, 0.535)


def distance(first: list[float] | None, second: list[float] | None) -> float | None:
    if first is None or second is None:
        return None
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def cube_in_bin(cube_xyz: list[float] | None) -> bool:
    return bool(
        cube_xyz
        and abs(cube_xyz[0] - BIN_CENTER_XYZ_M[0]) <= BIN_HALF_INTERIOR_M
        and abs(cube_xyz[1] - BIN_CENTER_XYZ_M[1]) <= BIN_HALF_INTERIOR_M
        and BIN_CUBE_CENTER_Z_RANGE_M[0] <= cube_xyz[2] <= BIN_CUBE_CENTER_Z_RANGE_M[1]
    )


def constraint_command(topic: str, expected_state: str) -> dict:
    """Send a DetachableJoint command and observe its actual state publication."""

    monitor = subprocess.Popen(
        ["gz", "topic", "-e", "-t", GRASP_STATE_TOPIC],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(0.10)
    sent_at = time.monotonic()
    command = subprocess.run(
        ["gz", "topic", "-t", topic, "-m", "gz.msgs.Empty", "-p", "unused: true"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3.0,
    )
    lines: list[str] = []
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if monitor.stdout is None:
            break
        ready, _, _ = select.select([monitor.stdout], [], [], 0.05)
        if not ready:
            continue
        line = monitor.stdout.readline()
        if not line:
            break
        lines.append(line.rstrip())
        if expected_state in line:
            break
    monitor.terminate()
    try:
        monitor.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        monitor.kill()
        monitor.wait(timeout=1.0)
    observed_at = time.monotonic()
    return {
        "topic": topic,
        "command_returncode": command.returncode,
        "command_stdout": command.stdout.strip(),
        "command_stderr": command.stderr.strip(),
        "sent_monotonic_s": sent_at,
        "state_observed_monotonic_s": observed_at if any(expected_state in line for line in lines) else None,
        "expected_state": expected_state,
        "state_lines": lines,
        "state_confirmed": any(expected_state in line for line in lines),
    }


def target_events(contacts: dict[str, list[dict]]) -> list[ContactEvent]:
    output: list[ContactEvent] = []
    for finger, channel in (("left", "left"), ("right", "right")):
        for event in contacts.get(channel, []):
            target = "red_cube" if "object_red_cube" in (event["collision1"] + event["collision2"]) else "other"
            output.append(
                ContactEvent(
                    float(event["timestamp_s"]), finger, target,
                    (event["collision1"], event["collision2"]),
                )
            )
    return sorted(output, key=lambda item: (item.timestamp_s, item.finger))


def speed_evidence(
    client: CalibrationClient, duration_s: float, *, hand_xyz_m: list[float] | None,
    after_sim_timestamp_s: float | None,
) -> dict:
    """Measure a post-close relative-speed window from dynamic pose telemetry.

    Dynamic ``Pose_V`` output is change-driven once the cube has settled.  The
    evidence is therefore the final 100 ms (or longer) of the already-recorded
    post-close contact-observation interval, rather than a wall-clock wait for
    a stationary object to publish a new pose.  No arm command is in flight
    during that interval, so a single FK sample represents the hand throughout.
    """

    samples: list[dict] = []
    if hand_xyz_m is None:
        return {
            "window_s": duration_s, "samples": [], "mean_mps": math.inf,
            "peak_mps": math.inf, "valid": False, "query_failures": 0,
            "reason": "HAND_FK_UNAVAILABLE",
        }
    post_close = [
        sample for sample in client.dynamic_cube_poses
        if after_sim_timestamp_s is None or sample["timestamp_s"] >= after_sim_timestamp_s
    ]
    if post_close:
        evidence_end_s = post_close[-1]["timestamp_s"]
        minimum_s = evidence_end_s - duration_s
        first_in_window = next(
            (index for index, sample in enumerate(post_close)
             if sample["timestamp_s"] >= minimum_s),
            len(post_close),
        )
        # Pose_V is normally published at about 17 Hz.  Include its immediate
        # predecessor when the first in-window sample is 1--59 ms after the
        # lower bound; otherwise an actually continuous window would be
        # shortened to 86 ms simply by sampling phase.
        post_close = post_close[max(0, first_in_window - 1):]
    for sample in post_close:
        if samples and sample["timestamp_s"] == samples[-1]["timestamp_s"]:
            # Pose_V can carry multiple target aliases per sim tick. One exact
            # target sample per timestamp is sufficient for a velocity series.
            continue
        samples.append({**sample, "hand_xyz_m": hand_xyz_m})
    speeds: list[float] = []
    for earlier, later in zip(samples, samples[1:]):
        delta_t = later["timestamp_s"] - earlier["timestamp_s"]
        if delta_t <= 0:
            continue
        relative_delta = [
            (cube_later - cube_earlier) - (hand_later - hand_earlier)
            for cube_earlier, cube_later, hand_earlier, hand_later in zip(
                earlier["xyz_m"], later["xyz_m"],
                earlier["hand_xyz_m"], later["hand_xyz_m"],
            )
        ]
        speeds.append(math.sqrt(sum(value * value for value in relative_delta)) / delta_t)
    sim_span_s = (
        samples[-1]["timestamp_s"] - samples[0]["timestamp_s"]
        if len(samples) >= 2 else 0.0
    )
    return {
        "window_s": duration_s,
        "samples": samples,
        "mean_mps": sum(speeds) / len(speeds) if speeds else math.inf,
        "peak_mps": max(speeds) if speeds else math.inf,
        "valid": bool(speeds) and sim_span_s >= duration_s,
        "sim_span_s": sim_span_s,
        "query_failures": 0,
        "timestamp_source": "Gazebo /clock paired with Pose_V dynamic_pose bridge",
    }


def settle_cube(client: CalibrationClient, *, pre_settle_s: float, settle_s: float) -> dict:
    deadline = time.monotonic() + pre_settle_s
    while time.monotonic() < deadline:
        rclpy.spin_once(client, timeout_sec=0.02)
    samples: list[dict] = []
    deadline = time.monotonic() + settle_s
    while time.monotonic() < deadline:
        rclpy.spin_once(client, timeout_sec=0.02)
        cube = runtime_cube_pose()
        if cube is not None:
            samples.append({"wall_monotonic_s": time.monotonic(), "xyz_m": cube["xyz"]})
        time.sleep(0.04)
    displacements = [
        distance(first["xyz_m"], later["xyz_m"])
        for first, later in zip(samples, samples[1:])
    ]
    final = samples[-1]["xyz_m"] if samples else None
    return {
        "pre_settle_s": pre_settle_s,
        "settle_s": settle_s,
        "samples": samples,
        "final_cube_xyz_m": final,
        "maximum_adjacent_displacement_m": max((value for value in displacements if value is not None), default=math.inf),
        "object_in_bin": cube_in_bin(final),
    }


def failure_class(*, approach: dict, gate_passed: bool, transport: dict, release_passed: bool) -> str:
    if not approach.get("executed"):
        return "APPROACH_ALIGNMENT_FAILURE"
    if not gate_passed:
        return "CONTACT_CLOSURE_FAILURE"
    if not transport.get("executed"):
        return "HOLD_TRANSPORT_FAILURE"
    if not release_passed:
        return "RELEASE_PLACEMENT_FAILURE"
    return "NONE"


def main() -> int:
    configuration = json.loads(os.environ["M1A_S3_CONFIGURATION_JSON"])
    protocol = configuration["grasp_orientation_families"]
    episode_id = configuration["episode_id"]
    rclpy.init()
    client = CalibrationClient()
    attached = False
    try:
        if not client.wait_calibration_ready() or not client.apply_scene():
            print(json.dumps({"status": "S3_RUNTIME_BLOCKED", "episode_id": episode_id, "reason": "ROS_OR_SCENE_UNAVAILABLE"}))
            return 2
        deadline = time.monotonic() + 10.0
        while not client.latest and time.monotonic() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        # DetachableJoint can retain its creation-time relation unless every
        # reset explicitly requests detachment.  This is episode
        # initialization, before the task oracle pose is read; it is never
        # eligible to count as a task-time release.
        initialization_detach = constraint_command(DETACH_TOPIC, "detached")
        time.sleep(0.10)
        cube = runtime_cube_pose()
        if cube is None or not client.update_cube_scene(cube["xyz"]):
            print(json.dumps({"status": "S3_RUNTIME_BLOCKED", "episode_id": episode_id, "reason": "RUNTIME_CUBE_POSE_OR_SCENE_UNAVAILABLE"}))
            return 2
        initial_joint_positions = [client.latest.get(name, math.nan) for name in JOINTS]
        initial_hand_pose = client.fk_link("panda_hand", initial_joint_positions)
        opened_before = client.command_hand([0.04, 0.04])
        # Bind the dynamic stream before the approach so the report can
        # distinguish approach displacement from close-induced displacement.
        client.set_dynamic_target_reference(cube["xyz"])
        exception_set = client.set_target_touch_exception(True)
        approach = collision_checked_orientation_approach(
            client, cube["xyz"], protocol,
            preferred_candidate_id=configuration.get("preferred_candidate_id"),
        ) if exception_set else {"executed": False, "reason": "TARGET_TOUCH_EXCEPTION_UNAVAILABLE"}
        pre_close_dynamic = client.dynamic_cube_poses[-1] if client.dynamic_cube_poses else None
        close_started = time.monotonic()
        close_target_m = float(configuration.get("close_command_per_finger_m", 0.010))
        approach_ready = bool(approach.get("executed") and approach.get("converged"))
        close = client.command_hand([close_target_m, close_target_m]) if approach_ready else {
            "accepted": False,
            "succeeded": False,
            "observed_positions_m": [],
            "reason": "APPROACH_CONTROLLER_DID_NOT_CONVERGE",
        }
        close_completed = time.monotonic()
        close_completed_sim_s = client.latest_sim_clock_s
        contacts_window = client.contact_window(0.25)
        contacts = classify_contacts(contacts_window)
        semantic_events = target_events(contacts_window)
        bilateral_valid, bilateral_reasons, bilateral_duration, bilateral_samples = bilateral_contact_window(
            semantic_events, target_id="red_cube"
        )
        post_close_dynamic = [
            sample for sample in client.dynamic_cube_poses
            if close_completed_sim_s is None or sample["timestamp_s"] >= close_completed_sim_s
        ]
        cube_after_close = (
            {
                "xyz": post_close_dynamic[-1]["xyz_m"],
                "timestamp_sim_s": post_close_dynamic[-1]["timestamp_s"],
                "source": post_close_dynamic[-1]["source"],
            }
            if post_close_dynamic else None
        )
        current_cube_xyz = cube_after_close["xyz"] if cube_after_close else None
        corridor = (
            client.gripper_frame_corridor_evidence(
                current_cube_xyz,
                maximum_transverse_error_m=float(protocol["gripper_frame_corridor_max_transverse_error_m"]),
                finger_center_line_anchor_m=approach.get("selected_finger_center_line_anchor_m"),
            )
            if current_cube_xyz is not None else {
                "coordinate_frame": "panda_hand",
                "target_in_grasp_corridor": False,
                "reason": "POST_CLOSE_DYNAMIC_TARGET_POSE_UNAVAILABLE",
            }
        )
        hand_for_speed = corridor.get("hand_pose_world_xyzw")
        speed = speed_evidence(
            client, 0.10,
            hand_xyz_m=list(hand_for_speed[:3]) if isinstance(hand_for_speed, list) else None,
            after_sim_timestamp_s=close_completed_sim_s,
        )
        finger_prohibited = any(
            "work_table" in (event["collision1"] + event["collision2"])
            or "bin_a" in (event["collision1"] + event["collision2"])
            for side in ("left", "right") for event in contacts_window.get(side, [])
        )
        close_age = time.monotonic() - close_completed
        width = sum(close.get("observed_positions_m", []))
        timestamps = [event.timestamp_s for event in semantic_events]
        gate_input = ContactGateInput(
            target_id="red_cube",
            expected_target_id="red_cube",
            bilateral_contact_valid=bilateral_valid,
            gripper_width_m=width,
            object_width_estimate_m=0.05,
            target_in_grasp_corridor=bool(corridor.get("target_in_grasp_corridor")),
            relative_linear_speed_mean_mps=float(speed["mean_mps"]),
            relative_linear_speed_peak_mps=float(speed["peak_mps"]),
            seconds_since_close_command=close_age,
            already_attached=False,
            prohibited_collision=finger_prohibited,
            controller_aborted=not approach_ready or not bool(close.get("succeeded")),
            valid_sim_timestamps=(
                bool(timestamps)
                and timestamps == sorted(timestamps)
                and bool(speed.get("valid"))
            ),
        )
        gate_passed, gate_reasons = evaluate_contact_gate(gate_input)
        gate = {
            "passed": gate_passed,
            "reasons": list(gate_reasons),
            "input": {
                "target_id": gate_input.target_id,
                "bilateral_contact_valid": bilateral_valid,
                "bilateral_reasons": list(bilateral_reasons),
                "bilateral_duration_s": bilateral_duration,
                "bilateral_samples": bilateral_samples,
                "gripper_width_m": width,
                "target_in_grasp_corridor": corridor.get("target_in_grasp_corridor"),
                "relative_speed": speed,
                "close_command_started_monotonic_s": close_started,
                "close_command_completed_monotonic_s": close_completed,
                "seconds_since_close_command": close_age,
                "prohibited_finger_contact": finger_prohibited,
                "valid_sim_timestamps": gate_input.valid_sim_timestamps,
            },
        }
        attach = {"sent": False, "state_confirmed": False}
        planning_attachment = {"applied": False, "reason": "GATE_REJECTED"}
        attached_cube_table_exception = False
        attached_cube_table_exception_restored = False
        lift = {"executed": False}
        transport = {"executed": False}
        lower = {"executed": False}
        release = {"passed": False, "reasons": ["GATE_REJECTED"], "evidence": {}}
        if gate_passed:
            attach = {"sent": True, **constraint_command(ATTACH_TOPIC, "attached")}
            attached = bool(attach["state_confirmed"])
            cube_after_attach = runtime_cube_pose()
            if attached and cube_after_attach is not None:
                planning_attachment = client.attach_cube_scene(cube_after_attach["xyz"])
            selected = approach.get("selected_hand_pose_world_xyzw")
            if attached and planning_attachment.get("applied") and selected:
                lift_pose = pose_message(tuple(selected[:3]), tuple(selected[3:]))
                lift_pose.position.z += 0.12
                attached_cube_table_exception = client.set_attached_cube_table_exception(True)
                lift = client.move_hand_pose(lift_pose) if attached_cube_table_exception else {
                    "executed": False, "reason": "ATTACHED_CUBE_TABLE_EXCEPTION_UNAVAILABLE"
                }
                attached_cube_table_exception_restored = client.set_attached_cube_table_exception(False)
                runtime_hand = runtime_link_pose("panda_hand")
                hand_pose_source = "gazebo_runtime_link_pose"
                if runtime_hand is None:
                    positions = [client.latest.get(name, float("nan")) for name in JOINTS]
                    runtime_hand = client.fk_link("panda_hand", positions)
                    hand_pose_source = "moveit_fk_joint_feedback_fallback"
                hand_to_cube = (
                    [cube["xyz"][index] - runtime_hand[index] for index in range(3)]
                    if runtime_hand is not None else None
                )
                preplace_pose = pose_message(tuple(selected[:3]), tuple(selected[3:]))
                if hand_to_cube is None:
                    transport = {
                        "executed": False,
                        "reason": "POST_LIFT_HAND_POSE_UNAVAILABLE",
                        "hand_pose_source": hand_pose_source,
                    }
                else:
                    preplace_pose.position.x = BIN_CENTER_XYZ_M[0] - hand_to_cube[0]
                    preplace_pose.position.y = BIN_CENTER_XYZ_M[1] - hand_to_cube[1]
                    preplace_pose.position.z = 0.70 - hand_to_cube[2]
                    transport = client.move_hand_pose(preplace_pose) if lift.get("executed") else {"executed": False, "reason": "LIFT_NOT_EXECUTED"}
                place_pose = pose_message(tuple(selected[:3]), tuple(selected[3:]))
                if hand_to_cube is not None:
                    place_pose.position.x = preplace_pose.position.x
                    place_pose.position.y = preplace_pose.position.y
                    place_pose.position.z = 0.60 - hand_to_cube[2]
                lower = client.move_hand_pose(place_pose) if transport.get("executed") else {"executed": False, "reason": "TRANSPORT_NOT_EXECUTED"}
                release_pose_before = runtime_link_pose("panda_hand")
                # The DetachableJoint holds the cube rigidly to link7; opening
                # before detaching can therefore time out on finger contact.
                # Goal § release defines success by explicit detach, retreat,
                # and in-bin settling, so detach first and then open.
                detach = constraint_command(DETACH_TOPIC, "detached") if lower.get("executed") else {"state_confirmed": False}
                open_started = time.monotonic()
                open_hand = client.command_hand([0.04, 0.04]) if detach.get("state_confirmed") else {"succeeded": False, "observed_positions_m": []}
                attached = attached and not bool(detach.get("state_confirmed"))
                cube_after_detach = runtime_cube_pose()
                planning_detach = client.detach_cube_scene(cube_after_detach["xyz"]) if detach.get("state_confirmed") and cube_after_detach else {"applied": False}
                retreat = {"executed": False}
                if lower.get("executed") and detach.get("state_confirmed") and selected:
                    retreat_pose = pose_message(
                        (place_pose.position.x, place_pose.position.y, place_pose.position.z),
                        tuple(selected[3:]),
                    )
                    retreat_pose.position.z += 0.15
                    retreat = client.move_hand_pose(retreat_pose)
                hand_after_retreat = runtime_link_pose("panda_hand")
                settle = settle_cube(client, pre_settle_s=0.50, settle_s=1.00)
                hand_delta = distance(release_pose_before[:3] if release_pose_before else None, hand_after_retreat[:3] if hand_after_retreat else None)
                cube_delta = distance(cube_after_detach["xyz"] if cube_after_detach else None, settle.get("final_cube_xyz_m"))
                follows = bool(
                    hand_delta is not None and cube_delta is not None and hand_delta >= 0.10 and abs(hand_delta - cube_delta) < 0.02
                )
                detach_after_open = 0.0 if detach.get("state_confirmed") else None
                evidence = ReleaseEvidence(
                    explicit_open_command=True,
                    hand_controller_succeeded=bool(open_hand.get("succeeded")),
                    gripper_width_m=sum(open_hand.get("observed_positions_m", [])),
                    detach_after_open_s=detach_after_open,
                    follows_end_effector_after_detach=follows,
                    object_in_bin=bool(settle.get("object_in_bin")),
                    bin_settle_s=float(settle.get("settle_s", 0.0)),
                    bin_displacement_m=float(settle.get("maximum_adjacent_displacement_m", math.inf)),
                    cleanup_triggered_detach=False,
                    direct_object_pose_write=False,
                )
                release_passed, release_reasons = evaluate_release(evidence)
                release = {
                    "passed": release_passed,
                    "reasons": list(release_reasons),
                    "evidence": {
                        "open_hand": open_hand,
                        "detach": detach,
                        "planning_detach": planning_detach,
                        "retreat": retreat,
                        "release_hand_delta_m": hand_delta,
                        "cube_delta_after_detach_m": cube_delta,
                        "settle": settle,
                        "detach_after_open_s": detach_after_open,
                        "detach_before_open": bool(detach.get("state_confirmed")),
                    },
                }
        client.set_target_touch_exception(False)
        transport_completed = bool(transport.get("executed") and lower.get("executed"))
        success = bool(gate_passed and attach.get("state_confirmed") and lift.get("executed") and transport_completed and release["passed"])
        final_joint_positions = [client.latest.get(name, math.nan) for name in JOINTS]
        final_hand_pose = client.fk_link("panda_hand", final_joint_positions)
        final_cube = runtime_cube_pose()
        print(json.dumps({
            "status": "CONTACT_GATED_PICK_PLACE_VERIFIED" if success else "CONTACT_GATED_PICK_PLACE_FAILED",
            "episode_id": episode_id,
            "configuration": configuration,
            "episode_initialization": {
                "detachable_joint_detach": initialization_detach,
                "label": "RESET_DETACH_BEFORE_RUNTIME_ORACLE_READ",
            },
            "initial_cube_pose": cube,
            "cube_pose_before_close": (
                {
                    "xyz": pre_close_dynamic["xyz_m"],
                    "timestamp_sim_s": pre_close_dynamic["timestamp_s"],
                    "source": pre_close_dynamic["source"],
                }
                if pre_close_dynamic else None
            ),
            "cube_pose_after_close": cube_after_close,
            "initial_joint_positions_rad": initial_joint_positions,
            "initial_hand_pose_world_xyzw": initial_hand_pose,
            "final_joint_positions_rad": final_joint_positions,
            "final_hand_pose_world_xyzw": final_hand_pose,
            "final_cube_pose": final_cube,
            "opened_before": opened_before,
            "approach": approach,
            "close": close,
            "contacts": contacts,
            "contact_events": [event.__dict__ for event in semantic_events],
            "corridor": corridor,
            "gate": gate,
            "attach": {
                **attach,
                "event_id": f"{episode_id}-attach" if attach.get("sent") else None,
                "timestamp_sim": max(timestamps) if timestamps else None,
                "target_id": "red_cube",
                "constraint_id": "gazebo_detachable_joint:panda_link7:object_red_cube" if attach.get("state_confirmed") else None,
            },
            "planning_attachment": planning_attachment,
            "attached_cube_table_exception": attached_cube_table_exception,
            "attached_cube_table_exception_restored": attached_cube_table_exception_restored,
            "lift": lift,
            "transport": transport,
            "lower": lower,
            "release": release,
            "detachable_joint_used": bool(attach.get("state_confirmed")),
            "detachable_joint_attach_request_sent": bool(attach.get("sent")),
            "direct_object_pose_write": False,
            "primary_failure_class": failure_class(
                approach=approach, gate_passed=gate_passed,
                transport={"executed": transport_completed}, release_passed=bool(release["passed"]),
            ),
        }))
        return 0
    finally:
        if attached:
            constraint_command(DETACH_TOPIC, "detached")
        if rclpy.ok():
            client.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
