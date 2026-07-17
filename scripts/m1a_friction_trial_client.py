#!/usr/bin/env python3
"""One bounded, unconstrained S2 friction-grasp trial in the dynamic P0 world."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import rclpy
from geometry_msgs.msg import Pose

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xh_agent.grasp.orientation_families import candidate_is_eligible, candidate_pose  # noqa: E402
from m1a_contact_calibration_client import CalibrationClient, classify_contacts, runtime_cube_pose  # noqa: E402


def pose_message(position_xyz_m: tuple[float, float, float], orientation_xyzw: tuple[float, float, float, float]) -> Pose:
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = position_xyz_m
    pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w = orientation_xyzw
    return pose


def distance(first: list[float] | None, second: list[float] | None) -> float | None:
    if first is None or second is None:
        return None
    return sum((a - b) ** 2 for a, b in zip(first, second)) ** 0.5


def configuration_from_environment() -> dict:
    raw = os.environ.get("M1A_S2_CONFIGURATION_JSON")
    if raw is None:
        return {
            "id": "unconfigured",
            "object_mass_kg": None,
            "changed_parameter_family": "unknown",
            "finger_friction": "unknown",
            "object_friction": "unknown",
            "contact_stiffness_damping": "unknown",
            "solver_step_s": None,
            "gripper_profile_m": [0.04, 0.01],
            "grasp_orientation_families": {},
        }
    return json.loads(raw)


def collision_checked_orientation_approach(
    client: CalibrationClient, cube_xyz: list[float], protocol: dict,
    *, preferred_candidate_id: str | None,
) -> dict:
    """Try candidates in fixed order, retaining every collision-checked IK result."""

    table_top_z_m = float(protocol["table_top_z_m"])
    clearance_m = float(protocol["fingertip_table_clearance_m"])
    pregrasp_standoff_m = float(protocol["pregrasp_standoff_m"])
    table = client.table_collision_evidence(
        maximum_padding_m=float(protocol["maximum_planning_scene_table_padding_m"])
    )
    if not table["padding_within_tip_clearance"]:
        return {
            "executed": False,
            "reason": "PLANNING_SCENE_TABLE_PADDING_OR_GEOMETRY_UNVERIFIED",
            "planning_scene_table_evidence": table,
            "candidate_evaluations": [],
        }

    evaluations: list[dict] = []
    viable: list[tuple[dict, object, list[float]]] = []
    for candidate in protocol["candidates"]:
        eligible, ineligible_reason = candidate_is_eligible(
            cube_xyz, candidate, table_top_z_m=table_top_z_m
        )
        if not eligible:
            evaluations.append(
                {
                    "candidate_id": candidate["id"],
                    "family": candidate["family"],
                    "eligible": False,
                    "ik_attempted": False,
                    "reason": ineligible_reason,
                }
            )
            continue
        target = candidate_pose(
            cube_xyz,
            candidate,
            table_top_z_m=table_top_z_m,
            fingertip_table_clearance_m=clearance_m,
        )
        pose = pose_message(target.position_xyz_m, target.orientation_xyzw)
        solution = client.ik(pose, avoid_collisions=True)
        precheck = {
            "candidate_id": target.candidate_id,
            "family": target.family,
            "eligible": True,
            "ik_attempted": True,
            "collision_checked_ik_solved": solution is not None,
            "collision_checked_ik_error": client.last_ik_error,
            "hand_pose_world_xyzw": [*target.position_xyz_m, *target.orientation_xyzw],
            "finger_axis_world": list(target.finger_axis_world),
            "closing_axis_world": list(target.closing_axis_world),
            "fingertip_lowest_z_m": target.fingertip_lowest_z_m,
            "target_center_gripper_frame_m": list(target.target_center_gripper_frame_m),
            "pregrasp_standoff_m": pregrasp_standoff_m,
            "pregrasp_hand_pose_world_xyzw": [
                *(
                    coordinate - pregrasp_standoff_m * axis
                    for coordinate, axis in zip(target.position_xyz_m, target.finger_axis_world)
                ),
                *target.orientation_xyzw,
            ],
        }
        if solution is None:
            evaluations.append(precheck)
            continue
        viable.append((precheck, target, solution))
        evaluations.append(precheck)
    ordered_viable = sorted(
        viable,
        key=lambda item: item[0]["candidate_id"] != preferred_candidate_id,
    )
    for precheck, target, solution in ordered_viable:
        pregrasp = pose_message(
            tuple(
                coordinate - pregrasp_standoff_m * axis
                for coordinate, axis in zip(target.position_xyz_m, target.finger_axis_world)
            ),
            target.orientation_xyzw,
        )
        pregrasp_motion = client.move_hand_pose(pregrasp, ik_seed=solution)
        precheck["pregrasp_motion"] = pregrasp_motion
        if not (pregrasp_motion.get("executed") and pregrasp_motion.get("converged")):
            # A dispatched but unverified motion can perturb the dynamic cube.
            # End this reset episode rather than trying another pose in an
            # already changed physical scene.
            if pregrasp_motion.get("executed"):
                return {
                    "executed": False,
                    "converged": False,
                    "reason": "PREGRASP_CONTROLLER_DID_NOT_CONVERGE",
                    "selected_candidate_id": target.candidate_id,
                    "preferred_candidate_id": preferred_candidate_id,
                    "planning_scene_table_evidence": table,
                    "candidate_evaluations": evaluations,
                }
            continue
        pose = pose_message(target.position_xyz_m, target.orientation_xyzw)
        motion = client.move_hand_pose(pose, ik_seed=pregrasp_motion.get("ik_solution"))
        precheck["motion"] = motion
        # A FollowJointTrajectory result alone is not physical approach
        # evidence. A non-converged descent is a reset boundary: the hand may
        # already have contacted the target, so a later candidate must not use
        # that altered scene as its start state.
        if motion.get("executed") and motion.get("converged"):
            return {
                **motion,
                "selected_candidate_id": target.candidate_id,
                "preferred_candidate_id": preferred_candidate_id,
                "selected_family": target.family,
                "selected_hand_pose_world_xyzw": [*target.position_xyz_m, *target.orientation_xyzw],
                "selected_finger_center_line_anchor_m": list(target.target_center_gripper_frame_m),
                "planning_scene_table_evidence": table,
                "candidate_evaluations": evaluations,
            }
        if motion.get("executed"):
            return {
                "executed": False,
                "converged": False,
                "reason": "APPROACH_CONTROLLER_DID_NOT_CONVERGE",
                "selected_candidate_id": target.candidate_id,
                "preferred_candidate_id": preferred_candidate_id,
                "planning_scene_table_evidence": table,
                "candidate_evaluations": evaluations,
            }
    return {
        "executed": False,
        "reason": "ALL_ORIENTATION_FAMILY_CANDIDATES_REJECTED",
        "preferred_candidate_id": preferred_candidate_id,
        "planning_scene_table_evidence": table,
        "candidate_evaluations": evaluations,
    }


def main() -> int:
    rclpy.init()
    client = CalibrationClient()
    try:
        configuration = configuration_from_environment()
        protocol = configuration.get("grasp_orientation_families", {})
        if not protocol:
            print(json.dumps({"status": "BLOCKED", "reason": "ORIENTATION_FAMILY_PROTOCOL_UNAVAILABLE"}))
            return 2
        if not client.wait_calibration_ready() or not client.apply_scene():
            print(json.dumps({"status": "BLOCKED", "reason": "ROS_OR_SCENE_UNAVAILABLE"}))
            return 2
        deadline = time.time() + 10.0
        while not client.latest and time.time() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        cube = runtime_cube_pose()
        if cube is None:
            print(json.dumps({"status": "BLOCKED", "reason": "RUNTIME_CUBE_POSE_UNAVAILABLE"}))
            return 2
        client.update_cube_scene(cube["xyz"])
        client.command_hand([0.04, 0.04])
        exception_set = client.set_target_touch_exception(True)
        approach = (
            collision_checked_orientation_approach(
                client, cube["xyz"], protocol,
                preferred_candidate_id=configuration.get("preferred_candidate_id"),
            )
            if exception_set else {"executed": False, "reason": "TARGET_TOUCH_EXCEPTION_UNAVAILABLE"}
        )
        start = {name: len(events) for name, events in client.contacts.items()}
        close = client.command_hand([0.01, 0.01])
        client.contact_window(0.5)
        contacts = classify_contacts({name: client.contacts[name][start[name]:] for name in client.contacts})
        at_close = client.pad_evidence(cube["xyz"])
        corridor = client.gripper_frame_corridor_evidence(
            cube["xyz"],
            maximum_transverse_error_m=float(protocol["gripper_frame_corridor_max_transverse_error_m"]),
            finger_center_line_anchor_m=approach.get("selected_finger_center_line_anchor_m"),
        )
        cube_after_close = runtime_cube_pose()
        # A lift is attempted only after observed bilateral physical contact.
        lift = {"executed": False}
        selected_pose = approach.get("selected_hand_pose_world_xyzw")
        if contacts["left_target"] and contacts["right_target"] and selected_pose:
            lift_pose = pose_message(
                tuple(selected_pose[:3]), tuple(selected_pose[3:])
            )
            lift_pose.position.z += 0.10
            lift = client.move_hand_pose(lift_pose)
        client.contact_window(1.0)
        cube_after_lift = runtime_cube_pose()
        client.command_hand([0.04, 0.04])
        client.set_target_touch_exception(False)
        separation = at_close.get("gazebo_minimum_pad_cube_aabb_separation_m")
        lift_height = ((cube_after_lift or cube_after_close or cube)["xyz"][2] - cube["xyz"][2])
        contact_timeline = {name: client.contacts[name][start[name]:][-120:] for name in client.contacts}
        cube_displacement_after_close = distance(cube_after_close and cube_after_close["xyz"], cube["xyz"])
        cube_displacement_after_lift = distance(cube_after_lift and cube_after_lift["xyz"], cube["xyz"])
        if not approach.get("executed") or separation is None or separation > 0.03:
            failure = "APPROACH_ALIGNMENT_FAILURE"
            diagnostic_subclass = "NO_REACH"
        elif not (contacts["left_target"] and contacts["right_target"]):
            failure = "CONTACT_CLOSURE_FAILURE"
            diagnostic_subclass = "NO_CONTACT"
        elif lift_height < 0.05:
            failure = "HOLD_TRANSPORT_FAILURE"
            diagnostic_subclass = "CONTACT_NO_LIFT"
        else:
            # This bounded S2 runner has not yet completed an explicit bin
            # transport/release; it cannot label a lift alone as a grasp pass.
            failure = "RELEASE_PLACEMENT_FAILURE"
            diagnostic_subclass = "LIFT_SLIP_OR_UNVERIFIED_RELEASE"
        print(json.dumps({
            "status": "FRICTION_TRIAL_FAILED", "primary_failure_class": failure,
            "diagnostic_subclass": diagnostic_subclass,
            "detachable_joint_used": False,
            "detachable_joint_attach_request_sent": False,
            "configuration": {
                **configuration,
                "world_sha256": os.environ.get("M1A_S2_WORLD_SHA256"),
                "approach_pose_source": "RUNTIME_ORACLE_TO_COLLISION_CHECKED_ORIENTATION_FAMILY",
            },
            "cube_pose": cube,
            "approach": approach,
            "close": close,
            "contacts": contacts,
            "pad_evidence_at_close": at_close,
            "gripper_frame_corridor_evidence": corridor,
            "contact_timeline": contact_timeline,
            "closed_gripper_width_m": sum(close.get("observed_positions_m", [])),
            "minimum_pad_cube_aabb_separation_m": separation,
            "cube_pose_after_close": cube_after_close,
            "lift": lift,
            "cube_pose_after_lift": cube_after_lift,
            "lift_height_m": lift_height,
            "cube_displacement_after_close_m": cube_displacement_after_close,
            "cube_displacement_after_lift_m": cube_displacement_after_lift,
        }))
        return 0
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
