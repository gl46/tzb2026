#!/usr/bin/env python3
"""Lift a broker-attached M1B cylinder using only its public RGB-D track.

This production primitive deliberately has no simulator entity argument.  The
broker has already made the physical attach decision; this step mirrors the
selected public collision proxy onto the wrist, executes a collision-checked
vertical 100 mm lift, and leaves the physical attachment intact for a fresh
public re-observation.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import rclpy
from geometry_msgs.msg import Pose
from moveit_msgs.msg import AttachedCollisionObject, CollisionObject, PlanningScene
from shape_msgs.msg import SolidPrimitive

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from m1a_contact_calibration_client import CalibrationClient, quaternion_rotate  # noqa: E402
from m1a_moveit_execution_client import JOINTS, set_allowed_pair  # noqa: E402
from run_m1b_tolerance_trial import apply_public_cylinder_scene, public_collision_id, public_tracks_from_evidence  # noqa: E402
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1  # noqa: E402
from xh_agent.runtime.m1b_center_correction import M1BPublicGeometryXYCorrectionV1, M1BTableSupportedCylinderCenterV1  # noqa: E402


M1B_CYLINDER_LENGTH_M = 0.080
M1B_CYLINDER_RADIUS_M = 0.015
POST_GRASP_LIFT_M = 0.100


def attach_public_carrier(
    client: CalibrationClient, carrier_collision_id: str, centre_world_m: list[float],
) -> dict[str, object]:
    """Move one public collision proxy from the world onto panda_link7."""
    positions = [client.latest.get(name, math.nan) for name in JOINTS]
    missing = [name for name, value in zip(JOINTS, positions) if not math.isfinite(value)]
    link = client.fk_link("panda_link7", positions) if not missing else None
    result: dict[str, object] = {
        "joint_state_available": not missing,
        "joint_state_missing_or_nonfinite": missing,
        "fk_link_available": link is not None,
        "world_proxy_removed": False,
        "attached_proxy_applied": False,
    }
    if link is None:
        result["status"] = "PANDA_LINK7_FK_UNAVAILABLE"
        return result

    remove_scene = PlanningScene(is_diff=True)
    remove = CollisionObject(id=carrier_collision_id)
    remove.header.frame_id = "world"
    remove.operation = CollisionObject.REMOVE
    remove_scene.world.collision_objects = [remove]
    if not client.apply_scene_diff(remove_scene):
        result["status"] = "PUBLIC_WORLD_PROXY_REMOVE_REJECTED"
        return result
    result["world_proxy_removed"] = True

    relative_xyz = quaternion_rotate(
        [-link[3], -link[4], -link[5], link[6]],
        tuple(value - origin for value, origin in zip(centre_world_m, link[:3])),
    )
    scene = PlanningScene(is_diff=True)
    attached = AttachedCollisionObject()
    attached.link_name = "panda_link7"
    attached.touch_links = ["panda_link7", "panda_link8", "panda_hand", "panda_leftfinger", "panda_rightfinger"]
    attached.object.id = carrier_collision_id
    attached.object.header.frame_id = "panda_link7"
    attached.object.primitives = [
        SolidPrimitive(type=SolidPrimitive.CYLINDER, dimensions=[M1B_CYLINDER_LENGTH_M, M1B_CYLINDER_RADIUS_M])
    ]
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = relative_xyz
    pose.orientation.w = 1.0
    attached.object.primitive_poses = [pose]
    attached.object.operation = CollisionObject.ADD
    scene.robot_state.is_diff = True
    scene.robot_state.attached_collision_objects = [attached]
    applied = client.apply_scene_diff(scene)
    result["attached_proxy_applied"] = applied
    result["status"] = "APPLIED" if applied else "PUBLIC_ATTACHED_PROXY_REJECTED"
    return result


def configure_lift_contacts(client: CalibrationClient, carrier_collision_id: str) -> bool:
    """Allow only the grasp contacts present at the start of the vertical lift."""
    matrix = client.current_acm()
    if matrix is None:
        return False
    for link in ("panda_link7", "panda_link8", "panda_hand", "panda_leftfinger", "panda_rightfinger", "work_table"):
        set_allowed_pair(matrix, carrier_collision_id, link, True)
    set_allowed_pair(matrix, "panda_leftfinger", "panda_rightfinger", True)
    return client.apply_scene_diff(PlanningScene(is_diff=True, allowed_collision_matrix=matrix))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-perception-evidence", required=True, type=Path)
    parser.add_argument("--public-camera-info", required=True, type=Path)
    parser.add_argument("--public-track-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    calibration = M1BStaticCameraCalibrationV1.from_file(ROOT / "configs" / "m1b_camera_calibration.json")
    xy_correction = M1BPublicGeometryXYCorrectionV1.from_file(ROOT / "configs" / "m1b_public_geometry_xy_correction.json")
    table_supported_z = M1BTableSupportedCylinderCenterV1.from_file(ROOT / "configs" / "m1b_table_supported_cylinder_center.json")
    tracks, scene_evidence = public_tracks_from_evidence(
        args.public_perception_evidence, args.public_camera_info,
        calibration, xy_correction, table_supported_z,
    )
    target = tracks.get(args.public_track_id)
    if target is None:
        raise SystemExit("PUBLIC_POST_GRASP_TARGET_NOT_ADMITTED")
    carrier_collision_id = public_collision_id(args.public_track_id)

    rclpy.init()
    client = CalibrationClient()
    try:
        ready = client.wait_calibration_ready()
        for _ in range(20):
            rclpy.spin_once(client, timeout_sec=0.05)
        scene_applied = apply_public_cylinder_scene(client, tracks) if ready else False
        attach = (
            attach_public_carrier(client, carrier_collision_id, list(target["estimated_center_world_m"]))
            if scene_applied else {"status": "PUBLIC_SCENE_NOT_APPLIED", "attached_proxy_applied": False}
        )
        contact_exceptions_applied = (
            configure_lift_contacts(client, carrier_collision_id)
            if attach.get("attached_proxy_applied") else False
        )
        positions = [client.latest.get(name, math.nan) for name in JOINTS]
        link = client.fk_link("panda_link7", positions) if all(math.isfinite(value) for value in positions) else None
        if link is None:
            lift = {"planned": False, "executed": False, "reason": "PANDA_LINK7_FK_UNAVAILABLE"}
        elif not contact_exceptions_applied:
            lift = {"planned": False, "executed": False, "reason": "CARRIER_CONTACT_CONFIGURATION_REJECTED"}
        else:
            target_pose = Pose()
            target_pose.position.x, target_pose.position.y, target_pose.position.z = link[:3]
            target_pose.position.z += POST_GRASP_LIFT_M
            target_pose.orientation.x, target_pose.orientation.y, target_pose.orientation.z, target_pose.orientation.w = link[3:]
            lift = client.move_hand_cartesian(
                target_pose, duration_s=3.0, max_step_m=0.005,
                ik_link="panda_link7", ik_seed=positions,
            )
        payload = {
            "schema_version": "M1BPublicPostGraspLiftEvidenceV1",
            "provenance": "PUBLIC_PERCEPTION_PRODUCTION",
            "online_truth_access": False,
            "public_track_id": args.public_track_id,
            "public_carrier_collision_id": carrier_collision_id,
            "public_collision_scene": scene_evidence,
            "public_scene_applied": scene_applied,
            "carrier_attach": attach,
            "contact_exceptions_applied": contact_exceptions_applied,
            "lift_distance_m": POST_GRASP_LIFT_M,
            "lift": lift,
            "physical_detach_command_sent": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        succeeded = bool(lift.get("executed") and lift.get("converged"))
        print(json.dumps({"lift_succeeded": succeeded, "physical_detach_command_sent": False}))
        return 0 if succeeded else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
