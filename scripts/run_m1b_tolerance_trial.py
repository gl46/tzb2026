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
import select
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.msg import CollisionObject, PlanningScene
from ros_gz_interfaces.msg import Contacts
from shape_msgs.msg import SolidPrimitive

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
# Measured on the collision-checked scene-1034 normal-cylinder approach.
# This is an IK numerical initializer only; MoveIt still validates the pose,
# plans the full trajectory, and controller feedback still decides convergence.
M1B_NORMAL_SIDE_IK_SEED = [
    2.8972995179371477, -0.36830496587838346, 2.7341791043013672,
    -2.7829882206873315, 1.4459771370327215, 2.997318074330887,
    -1.286336046330572,
]
M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M = 0.220
M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M = 0.065


def _m1b_normal_side_pose(centre_world_m: list[float], *, hand_z_offset_m: float) -> Pose:
    """Return one side-grasp hand pose; only the vertical phase may vary."""
    value = Pose()
    value.position.x = centre_world_m[0] - 0.080
    # The high precontact phase removes the old approach-graze failure mode,
    # so final descent is now centred on the public centre estimate.  A
    # closing-axis bias would turn a nominal cylindrical grasp into unilateral
    # contact and must not be silently treated as self-centring.
    value.position.y = centre_world_m[1]
    value.position.z = centre_world_m[2] + hand_z_offset_m
    value.orientation.x = 1.0
    value.orientation.w = 0.0
    return value


def m1b_normal_side_precontact(client: CalibrationClient, centre_world_m: list[float]) -> dict[str, object]:
    """M1B's fixed public normal-cylinder side-grasp primitive.

    The 12 cm finger boards run along world X and close along world Y.  Its
    pregrasp and final poses are both collision-checked through the same
    MoveIt/controller path used in runtime; only ``centre_world_m`` differs in
    this calibration invocation.
    """
    # The original +120 mm nominal clearance still contacted a 90 mm cylinder
    # in the physical simulator through the extended finger board.  +220 mm
    # is the bounded non-contact phase; it completes before a close command,
    # so accidental approach contact can never authorize a grasp.  The
    # carried-over motion gate is the action
    # controller's terminal result (in particular, it must not abort), not an
    # extra post-action joint-error threshold: the latter is diagnostic
    # evidence and varies with controller-state delivery timing.
    final = {"executed": False}
    attempts = 0
    while attempts < 3 and not final.get("executed"):
        final = client.move_hand_pose(
            _m1b_normal_side_pose(centre_world_m, hand_z_offset_m=M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M),
            ik_seed=M1B_NORMAL_SIDE_IK_SEED,
        )
        attempts += 1
    return {
        "executed": bool(final.get("executed")),
        "converged": bool(final.get("converged")), "final": final, "attempts": attempts,
        "geometry": {"finger_board_axis_world": [1.0, 0.0, 0.0], "closing_axis_world": [0.0, 1.0, 0.0], "final_x_offset_m": -0.080, "final_y_offset_m": 0.0, "precontact_hand_z_offset_m": M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M, "contact_hand_z_offset_m": M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M, "ik_seed_source": "measured_scene1034_collision_checked_branch", "path_source": "MoveIt collision-checked trajectory from reset home"},
    }


def m1b_normal_side_contact_descend(client: CalibrationClient, centre_world_m: list[float], *, ik_seed: list[float] | None) -> dict[str, object]:
    """Execute the contact-bearing final descent after close has been issued."""
    return client.move_hand_pose(_m1b_normal_side_pose(centre_world_m, hand_z_offset_m=M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M), ik_seed=ik_seed)


def apply_calibration_cylinder_scene(client: CalibrationClient, labels: list[dict[str, object]]) -> bool:
    """Add every supervised cylinder as a collision object during calibration.

    This initialization-only scene prevents the planner from taking an arm or
    finger trajectory through neighbouring physical cylinders.  It is not an
    online policy input: production creates the equivalent obstacles from
    public perception tracks before planning.
    """
    scene = PlanningScene(is_diff=True)
    for label in labels:
        item = CollisionObject()
        item.id = str(label["actual_sim_entity_id"])
        item.header.frame_id = "world"
        item.primitives = [SolidPrimitive(type=SolidPrimitive.CYLINDER, dimensions=[0.09, 0.025])]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = (float(value) for value in label["position_3d_world"])
        pose.orientation.w = 1.0
        item.primitive_poses = [pose]
        item.operation = CollisionObject.ADD
        scene.world.collision_objects.append(item)
    return client.apply_scene_diff(scene)


def attach_and_observe(topic: str, state_topic: str) -> dict[str, object]:
    """Subscribe before publish so the one-shot DetachableJoint state is evidence."""
    monitor = subprocess.Popen(["gz", "topic", "-e", "-t", state_topic], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines: list[str] = []
    try:
        # DetachableJoint state is a one-shot Gazebo transport publication;
        # establish the monitor subscription before issuing attach so success
        # requires an observed state transition rather than a blind publish.
        time.sleep(0.40)
        command = subprocess.run(
            # DetachableJoint consumes an Empty request.  Supplying an
            # invented field can make Gazebo accept a publish command without
            # delivering the state transition, so the calibration path must
            # use the same wire payload as the production attach primitive.
            ["gz", "topic", "-t", topic, "-m", "gz.msgs.Empty", "-p", ""],
            check=False, capture_output=True, text=True, timeout=3.0,
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and monitor.stdout is not None:
            ready, _, _ = select.select([monitor.stdout], [], [], 0.05)
            if not ready:
                continue
            line = monitor.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())
            if "attached" in line:
                break
    finally:
        monitor.terminate()
        try:
            monitor.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            monitor.kill()
            monitor.wait(timeout=1.0)
    return {
        "sent": command.returncode == 0, "topic": topic,
        "command_stdout": command.stdout.strip(), "command_stderr": command.stderr.strip(),
        "state_topic": state_topic, "state_confirmed": any("attached" in line for line in lines),
        "state_lines": lines,
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
        contact_descend = {"executed": False, "reason": "MOVEIT_UNAVAILABLE"}
        contact_start_index = len(raw)
        if ready:
            cylinder_scene_applied = apply_calibration_cylinder_scene(client, labels)
            target_entity = str(normal[args.object_slot - 1]["actual_sim_entity_id"])
            # Keep the target collision-checked through the entire transit to
            # high precontact.  Enabling finger/target contact early lets a
            # planner legally side-swipe the free cylinder before close,
            # which both moves the calibration target and makes stale approach
            # contacts look tempting.  Only the deliberately contact-bearing
            # descent receives this narrow exception.
            target_touch_exception_applied = False
            open_hand = client.command_hand([0.04, 0.04])
            approach = m1b_normal_side_precontact(client, target) if cylinder_scene_applied else {"executed": False, "reason": "CALIBRATION_COLLISION_SCENE_UNAVAILABLE"}
            # A controller action can report success while the physical arm
            # was deflected by an unmodelled/free-cylinder contact.  Do not
            # close or enter the contact-bearing descent from that state:
            # production motion acceptance requires both execution and the
            # bounded terminal convergence evidence.
            approach_motion_accepted = bool(approach.get("executed") and approach.get("converged"))
            if approach_motion_accepted and open_hand.get("succeeded"):
                target_touch_exception_applied = client.set_target_touch_exception(True, target_id=target_entity)
            contact_descend = (
                m1b_normal_side_contact_descend(client, target, ik_seed=approach.get("final", {}).get("ik_solution"))
                if target_touch_exception_applied else {"executed": False, "reason": "TOUCH_EXCEPTION_GATE_REJECTED"}
            )
            # Descend while open so the 50 mm cylinder enters between both
            # pads; only then issue the 20 mm close.  The evidence window
            # begins immediately before that close, excluding all approach
            # contact telemetry from attach authorization.
            contact_start_index = len(raw)
            if contact_descend.get("executed") and contact_descend.get("converged"):
                close = client.command_hand([0.01, 0.01])
            if close.get("succeeded"):
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline:
                    rclpy.spin_once(client, timeout_sec=0.02)
        # Contact events only become attach evidence after a successfully
        # commanded close.  Otherwise background contacts remain diagnostic
        # raw telemetry and cannot be mislabelled as a contact window.
        post_close_raw = raw[contact_start_index:] if ready and close.get("succeeded") else []
        feedback, internal = broker_from_window(post_close_raw)
        motion_gate_passed = bool(
            open_hand.get("succeeded") and approach.get("executed") and approach.get("converged")
            and close.get("succeeded") and contact_descend.get("executed") and contact_descend.get("converged")
        )
        attach = {"sent": False, "state_confirmed": False, "reason": "BILATERAL_GATE_REJECTED"}
        if feedback.grasp_success and not motion_gate_passed:
            attach["reason"] = "MOTION_OR_HAND_GATE_REJECTED"
        if feedback.grasp_success and motion_gate_passed and internal["attach_topic"] and internal["actual_sim_entity_id"]:
            entity = str(internal["actual_sim_entity_id"])
            attach = attach_and_observe(str(internal["attach_topic"]), f"/xh/m1b/{entity}/grasp_state")
        payload = {
            "schema_version": "M1BToleranceTrialEvidenceV1",
            "provenance": "CALIBRATION_ONLY_INITIALIZATION",
            "trial": trial,
            "supervision_initialization": {"orientation_state": "normal", "object_slot": args.object_slot, "truth_center_used_only_for_initial_target_pose": truth_center},
            "offset_vector_m": [target[index] - truth_center[index] for index in range(3)],
            "production_grasp_primitive": "m1b_normal_side_precontact + physical_hand + m1b_normal_side_contact_descend + m1b_internal_bilateral_broker",
            "ready": ready, "calibration_collision_scene_applied": cylinder_scene_applied if ready else False, "target_touch_exception_applied": target_touch_exception_applied if ready else False, "motion_gate_requires_terminal_convergence": True, "open_hand": open_hand, "approach": approach, "close": close, "contact_descend": contact_descend,
            "raw_contact_samples": [{"timestamp_s": item.timestamp_s, "finger": item.finger, "collision_pairs": list(item.collision_pairs)} for item in raw],
            "post_close_contact_samples": [{"timestamp_s": item.timestamp_s, "finger": item.finger, "collision_pairs": list(item.collision_pairs)} for item in post_close_raw],
            "cylinder_side_contact_samples": cylinder_contact_samples,
            "gate": {"grasp_success": feedback.grasp_success, "tactile_state": feedback.tactile_state, "reobservation_required": feedback.reobservation_required, "motion_gate_passed": motion_gate_passed, "internal_actuation_record": internal},
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
