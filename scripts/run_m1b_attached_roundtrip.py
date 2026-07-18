#!/usr/bin/env python3
"""Verify an already broker-attached M1B cylinder follows, detaches, and decouples.

This is an acceptance/evaluation utility, not a control-stack component.  It
reads Gazebo poses only after the broker has selected and attached the entity,
and records them as simulator-supervision evidence.  No queried pose is fed
back into grasp selection, planning, or attachment.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
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

from m1a_contact_calibration_client import CalibrationClient  # noqa: E402
from m1a_contact_calibration_client import quaternion_rotate  # noqa: E402
from m1b_reset_detach import detach_and_observe  # noqa: E402
from m1a_moveit_execution_client import JOINTS, set_allowed_pair  # noqa: E402


POSE_RE = re.compile(
    r"Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*"
    r"\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
    r"\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
)


def gazebo_pose(model: str, *, link: str | None = None) -> list[float] | None:
    command = ["timeout", "2", "gz", "model", "-m", model]
    command.extend(["-l", link] if link else ["-p"])
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=4.0)
    matches = POSE_RE.findall(result.stdout)
    # A link query prints the model-root pose first and the requested link pose
    # later.  The final pose is therefore the requested link, while a model
    # query contains only its model pose.
    return [float(value) for value in matches[-1]] if matches else None


def distance(first: list[float] | None, second: list[float] | None) -> float | None:
    if first is None or second is None:
        return None
    return math.dist(first, second)


def rpy_quaternion(roll: float, pitch: float, yaw: float) -> list[float]:
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return [sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]


def xyz(pose: list[float] | None) -> list[float] | None:
    return pose[:3] if pose is not None else None


def relative(cylinder: list[float] | None, link: list[float] | None) -> list[float] | None:
    if cylinder is None or link is None:
        return None
    quat = rpy_quaternion(*link[3:])
    return quaternion_rotate([-quat[0], -quat[1], -quat[2], quat[3]], tuple(a - b for a, b in zip(cylinder[:3], link[:3])))


def attach_cylinder_to_moveit(client: CalibrationClient, entity: str, cylinder_world: list[float] | None) -> bool:
    """Mirror the already-observed Gazebo attach in MoveIt for transport planning."""
    positions = [client.latest.get(name, math.nan) for name in JOINTS]
    link = client.fk_link("panda_link7", positions) if all(math.isfinite(v) for v in positions) else None
    if link is None or cylinder_world is None:
        return False
    remove_scene = PlanningScene(is_diff=True)
    remove = CollisionObject(id=entity)
    remove.header.frame_id = "world"
    remove.operation = CollisionObject.REMOVE
    remove_scene.world.collision_objects = [remove]
    if not client.apply_scene_diff(remove_scene):
        return False
    relative_xyz = quaternion_rotate(
        [-link[3], -link[4], -link[5], link[6]],
        tuple(value - origin for value, origin in zip(cylinder_world, link[:3])),
    )
    scene = PlanningScene(is_diff=True)
    attached = AttachedCollisionObject()
    attached.link_name = "panda_link7"
    attached.touch_links = ["panda_link7", "panda_link8", "panda_hand", "panda_leftfinger", "panda_rightfinger"]
    attached.object.id = entity
    attached.object.header.frame_id = "panda_link7"
    attached.object.primitives = [SolidPrimitive(type=SolidPrimitive.CYLINDER, dimensions=[0.09, 0.025])]
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = relative_xyz
    pose.orientation.w = 1.0
    attached.object.primitive_poses = [pose]
    attached.object.operation = CollisionObject.ADD
    scene.robot_state.is_diff = True
    scene.robot_state.attached_collision_objects = [attached]
    return client.apply_scene_diff(scene)


def remove_attached_cylinder_from_moveit(client: CalibrationClient, entity: str) -> bool:
    scene = PlanningScene(is_diff=True)
    attached = AttachedCollisionObject()
    attached.object.id = entity
    attached.object.operation = CollisionObject.REMOVE
    scene.robot_state.is_diff = True
    scene.robot_state.attached_collision_objects = [attached]
    return client.apply_scene_diff(scene)


def configure_transport_collision_exceptions(client: CalibrationClient, entity: str) -> bool:
    """Permit only the physical grasp/initial-static contacts needed to transport."""
    matrix = client.current_acm()
    if matrix is None:
        return False
    for link in ("panda_link7", "panda_link8", "panda_hand", "panda_leftfinger", "panda_rightfinger", "work_table"):
        set_allowed_pair(matrix, entity, link, True)
    # Closed parallel fingers meet in this simplified Panda model.  It is a
    # self-contact inherent in the physical grasp state, not a free-space
    # collision exemption.
    set_allowed_pair(matrix, "panda_leftfinger", "panda_rightfinger", True)
    # These generated scene objects overlap the immobile base at reset.  They
    # cannot be cleared by any arm trajectory, so retain checking against every
    # moving link but allow the unavoidable base-only initial overlap.
    for index in range(1, 13):
        other = f"cylinder_{index:02d}"
        if other != entity:
            set_allowed_pair(matrix, other, "panda_link0", True)
    return client.apply_scene_diff(PlanningScene(is_diff=True, allowed_collision_matrix=matrix))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", required=True, help="Actuation-internal entity selected by the broker")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"cylinder_[0-9]{2}", args.entity):
        raise SystemExit("entity must be a generated cylinder id")

    rclpy.init()
    client = CalibrationClient()
    try:
        ready = client.wait_calibration_ready()
        for _ in range(20):
            rclpy.spin_once(client, timeout_sec=0.05)
        current = [client.latest.get(name, math.nan) for name in JOINTS]
        before_link = gazebo_pose("panda_controller", link="panda_link7")
        before_cylinder = gazebo_pose(args.entity)
        moveit_carried_object_applied = attach_cylinder_to_moveit(client, args.entity, xyz(before_cylinder)) if ready else False
        transport_collision_exceptions_applied = (
            configure_transport_collision_exceptions(client, args.entity)
            if moveit_carried_object_applied else False
        )
        move_target = list(current)
        # A small base-axis transport displacement gives the constraint a
        # measurable follow test while remaining far inside Panda limits.
        move_target[0] += 0.10
        attached_move = client.move_joint_target(move_target) if transport_collision_exceptions_applied else {"executed": False}
        after_link = gazebo_pose("panda_controller", link="panda_link7")
        after_cylinder = gazebo_pose(args.entity)
        link_motion = distance(xyz(before_link), xyz(after_link))
        cylinder_motion = distance(xyz(before_cylinder), xyz(after_cylinder))
        relative_drift = distance(relative(before_cylinder, before_link), relative(after_cylinder, after_link))
        attached_follow = bool(
            attached_move.get("executed")
            and link_motion is not None and link_motion >= 0.01
            and cylinder_motion is not None and cylinder_motion >= 0.01
            and relative_drift is not None and relative_drift <= 0.01
        )
        detach = detach_and_observe(args.entity, 2.0) if attached_follow else None
        detach_verified = bool(detach and detach.detached_observed)
        moveit_carried_object_removed = remove_attached_cylinder_from_moveit(client, args.entity) if detach_verified else False
        before_decouple_link = gazebo_pose("panda_controller", link="panda_link7")
        before_decouple_cylinder = gazebo_pose(args.entity)
        decouple_target = list(move_target)
        decouple_target[0] -= 0.12
        detached_move = client.move_joint_target(decouple_target) if detach_verified and moveit_carried_object_removed else {"executed": False}
        after_decouple_link = gazebo_pose("panda_controller", link="panda_link7")
        after_decouple_cylinder = gazebo_pose(args.entity)
        decouple_link_motion = distance(xyz(before_decouple_link), xyz(after_decouple_link))
        decouple_relative_change = distance(
            relative(before_decouple_cylinder, before_decouple_link),
            relative(after_decouple_cylinder, after_decouple_link),
        )
        detached_decoupled = bool(
            detached_move.get("executed")
            and decouple_link_motion is not None and decouple_link_motion >= 0.01
            and decouple_relative_change is not None and decouple_relative_change >= 0.01
        )
        payload = {
            "schema_version": "M1BAttachedRoundTripEvidenceV1",
            "provenance": "SUPERVISION_EVALUATION_ONLY",
            "online_truth_access": False,
            "entity_source": "actuation_internal_broker_attach_record",
            "entity": args.entity,
            "moveit_carried_object_applied": moveit_carried_object_applied,
            "transport_collision_exceptions_applied": transport_collision_exceptions_applied,
            "attached_move": attached_move,
            "attached_follow": attached_follow,
            "attached_follow_metrics": {"link_motion_m": link_motion, "cylinder_motion_m": cylinder_motion, "relative_drift_m": relative_drift},
            "detach": None if detach is None else {"topic": detach.detach_topic, "state_topic": detach.grasp_state_topic, "detached_observed": detach.detached_observed, "state_lines": list(detach.state_lines)},
            "moveit_carried_object_removed": moveit_carried_object_removed,
            "detached_move": detached_move,
            "detached_decoupled": detached_decoupled,
            "detached_decouple_metrics": {"link_motion_m": decouple_link_motion, "relative_change_m": decouple_relative_change},
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"attached_follow": attached_follow, "detach_verified": detach_verified, "detached_decoupled": detached_decoupled}))
        return 0 if attached_follow and detach_verified and detached_decoupled else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
