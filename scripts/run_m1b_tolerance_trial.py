#!/usr/bin/env python3
"""Run one reset-isolated, calibration-only M1B tolerance trial.

The centre supplied here is privileged supervision and is confined to the
initial target-pose calculation.  Contact selection and the optional attach
request use only the M1B actuation-internal bridges, exactly as the production
primitive does.  An outer runner is responsible for the mandatory full reset
and for assigning three distinct scene/object slots to each grid point.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import Pose
from ros_gz_interfaces.msg import Contacts

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from m1a_contact_calibration_client import CalibrationClient  # noqa: E402
from xh_agent.grasp.m1b_contact_window import M1BContactSampleV1, broker_from_window  # noqa: E402


RAW_CONTACT_TOPICS = {
    "left": "/xh/actuation_internal/m1b/panda_leftfinger_contacts",
    "right": "/xh/actuation_internal/m1b/panda_rightfinger_contacts",
}
CYLINDER_CONTACT_TOPICS = [
    f"/xh/actuation_internal/m1b/cylinder_{index:02d}_contacts"
    for index in range(1, 13)
]


def m1b_normal_side_approach(client: CalibrationClient, centre_world_m: list[float]) -> dict[str, object]:
    """M1B's fixed public normal-cylinder side-grasp primitive.

    The 12 cm finger boards run along world X and close along world Y.  Its
    pregrasp and final poses are both collision-checked through the same
    MoveIt/controller path used in runtime; only ``centre_world_m`` differs in
    this calibration invocation.
    """
    def pose(x_offset_m: float) -> Pose:
        value = Pose()
        value.position.x = centre_world_m[0] + x_offset_m
        value.position.y = centre_world_m[1]
        value.position.z = centre_world_m[2] + 0.055
        value.orientation.x = 1.0
        value.orientation.w = 0.0
        return value
    # The planner itself supplies the collision-checked path from the reset
    # home pose.  A prior fixed -245 mm staging point placed the hand behind
    # the Panda base for the leftmost legal cylinders, so it was not a valid
    # universal pregrasp.  Do not turn that unreachable waypoint into a
    # geometry gate; the actual grasp pose stays the fixed production side
    # primitive and its full MoveIt trajectory remains recorded below.
    # This 80 mm board-axis offset and 65 mm hand-height offset are the
    # collision-checked normal-cylinder geometry.  They were selected by a
    # real MoveIt IK audit on the industrial world; the older -145/55 mm pose
    # puts the hand into the base/table envelope for legal left-side scenes.
    def final_pose() -> Pose:
        value = pose(-0.080)
        value.position.z = centre_world_m[2] + 0.065
        return value
    final = client.move_hand_pose(final_pose())
    return {
        "executed": bool(final.get("executed") and final.get("converged")),
        "converged": bool(final.get("converged")), "final": final,
        "geometry": {"finger_board_axis_world": [1.0, 0.0, 0.0], "closing_axis_world": [0.0, 1.0, 0.0], "final_x_offset_m": -0.080, "final_hand_z_offset_m": 0.065, "path_source": "MoveIt collision-checked trajectory from reset home"},
    }


def attach_and_observe(topic: str, state_topic: str) -> dict[str, object]:
    command = subprocess.run(
        ["gz", "topic", "-t", topic, "-m", "gz.msgs.Empty", "-p", "unused: true"],
        check=False, capture_output=True, text=True, timeout=3.0,
    )
    observed = subprocess.run(
        ["timeout", "2", "gz", "topic", "-e", "-t", state_topic],
        check=False, capture_output=True, text=True, timeout=3.0,
    )
    return {
        "sent": command.returncode == 0, "topic": topic,
        "command_stdout": command.stdout.strip(), "command_stderr": command.stderr.strip(),
        "state_topic": state_topic, "state_confirmed": "attached" in observed.stdout,
        "state_lines": observed.stdout.splitlines(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", required=True, type=Path, help="One record from the immutable worklist")
    parser.add_argument("--supervision", required=True, type=Path)
    parser.add_argument("--object-slot", required=True, type=int, help="1-based normal-object slot, calibration only")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    trial = json.loads(args.trial.read_text(encoding="utf-8"))
    if trial.get("provenance") != "CALIBRATION_ONLY_INITIALIZATION":
        raise SystemExit("trial is not calibration-only")
    axis = str(trial["axis"])
    if axis not in {"x", "y", "z"}:
        raise SystemExit("trial axis must be x, y, or z")
    labels = json.loads(args.supervision.read_text(encoding="utf-8"))["simulator_supervision"]["objects"]
    normal = [label for label in labels if label["orientation_state"] == "normal"]
    if not 1 <= args.object_slot <= len(normal):
        raise SystemExit(f"object slot must be in [1, {len(normal)}]")
    truth_center = [float(value) for value in normal[args.object_slot - 1]["position_3d_world"]]
    target = list(truth_center)
    target["xyz".index(axis)] += float(trial["offset_m"])
    rclpy.init()
    client = CalibrationClient()
    raw: list[M1BContactSampleV1] = []
    cylinder_contact_samples = 0
    def on_contact(message: Contacts, finger: str) -> None:
        timestamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        pairs = tuple((contact.collision1.name, contact.collision2.name) for contact in message.contacts)
        raw.append(M1BContactSampleV1(timestamp, finger, pairs))
    for finger, topic in RAW_CONTACT_TOPICS.items():
        client.create_subscription(Contacts, topic, lambda message, finger=finger: on_contact(message, finger), 1000)
    def on_cylinder_contact(message: Contacts) -> None:
        """Recover finger events from the independently measured cylinder side.

        This remains inside the actuator broker.  The callback never receives
        a task target or supervision identifier; it classifies only the two
        physical finger collision names present in each contact pair.
        """
        nonlocal cylinder_contact_samples
        timestamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        pairs = tuple((contact.collision1.name, contact.collision2.name) for contact in message.contacts)
        for finger, marker in (("left", "panda_leftfinger"), ("right", "panda_rightfinger")):
            finger_pairs = tuple(pair for pair in pairs if any(marker in side for side in pair))
            if finger_pairs:
                raw.append(M1BContactSampleV1(timestamp, finger, finger_pairs))
                cylinder_contact_samples += 1
    for topic in CYLINDER_CONTACT_TOPICS:
        client.create_subscription(Contacts, topic, on_cylinder_contact, 1000)
    try:
        ready = client.wait_calibration_ready() and client.apply_scene()
        approach = {"executed": False, "reason": "MOVEIT_UNAVAILABLE"}
        open_hand = {"succeeded": False}
        close = {"succeeded": False}
        if ready:
            client.update_cube_scene(target, target_id="m1b_calibration_target")
            client.set_target_touch_exception(True, target_id="m1b_calibration_target")
            open_hand = client.command_hand([0.04, 0.04])
            approach = m1b_normal_side_approach(client, target)
            if approach.get("executed") and approach.get("converged"):
                close = client.command_hand([0.01, 0.01])
            deadline = time.monotonic() + 0.35
            while time.monotonic() < deadline:
                rclpy.spin_once(client, timeout_sec=0.02)
        feedback, internal = broker_from_window(raw)
        attach = {"sent": False, "state_confirmed": False, "reason": "BILATERAL_GATE_REJECTED"}
        if feedback.grasp_success and internal["attach_topic"] and internal["actual_sim_entity_id"]:
            entity = str(internal["actual_sim_entity_id"])
            attach = attach_and_observe(str(internal["attach_topic"]), f"/xh/m1b/{entity}/grasp_state")
        payload = {
            "schema_version": "M1BToleranceTrialEvidenceV1",
            "provenance": "CALIBRATION_ONLY_INITIALIZATION",
            "trial": trial,
            "supervision_initialization": {"orientation_state": "normal", "object_slot": args.object_slot, "truth_center_used_only_for_initial_target_pose": truth_center},
            "offset_vector_m": [target[index] - truth_center[index] for index in range(3)],
            "production_grasp_primitive": "m1b_normal_side_approach + physical_hand + m1b_internal_bilateral_broker",
            "ready": ready, "open_hand": open_hand, "approach": approach, "close": close,
            "raw_contact_samples": [{"timestamp_s": item.timestamp_s, "finger": item.finger, "collision_pairs": list(item.collision_pairs)} for item in raw],
            "cylinder_side_contact_samples": cylinder_contact_samples,
            "gate": {"grasp_success": feedback.grasp_success, "tactile_state": feedback.tactile_state, "reobservation_required": feedback.reobservation_required, "internal_actuation_record": internal},
            "attach": attach,
            "bilateral_same_entity_contact": feedback.grasp_success,
            "online_truth_access": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"bilateral_same_entity_contact": feedback.grasp_success, "raw_samples": len(raw), "ready": ready}))
        return 0 if ready else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
