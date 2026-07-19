#!/usr/bin/env python3
"""Fail-closed ADR-0016 orientation scan for one generated M1B scene.

This is a scene-admission tool, never an online policy component.  It records
pure kinematics separately from collision-aware corridor planning so a wrist
limit cannot be misreported as clutter interference.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import rclpy

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from generate_industrial_scenes import bin_cell_targets
from m1a_contact_calibration_client import CalibrationClient
from run_m1b_tolerance_trial import (
    M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M,
    M1B_TOP_CONTACT_CENTERLINE_Z_M,
    M1B_TOP_PRECONTACT_STANDOFF_M,
    _m1b_top_pose,
    apply_calibration_cylinder_scene,
)


def pose_results(client: CalibrationClient, center: list[float], *, collision_aware: bool) -> dict[str, object]:
    """Return pregrasp/final IK and, when collision-aware, home-corridor plans."""
    entries: dict[str, object] = {}
    seed = None
    for name, offset in (
        ("pregrasp", M1B_TOP_CONTACT_CENTERLINE_Z_M + M1B_TOP_PRECONTACT_STANDOFF_M),
        ("final_contact", M1B_TOP_CONTACT_CENTERLINE_Z_M),
    ):
        pose = _m1b_top_pose(
            center, hand_z_offset_m=offset,
            hand_y_centerline_bias_m=M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M, yaw_rad=0.0,
        )
        solution = client.ik(pose, avoid_collisions=collision_aware, seed=seed)
        plan = client.plan(solution) if collision_aware and solution is not None else None
        entries[name] = {
            "pose_world_xyzw": [pose.position.x, pose.position.y, pose.position.z, pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w],
            "ik_solved": solution is not None,
            "ik_error": None if solution is not None else client.last_ik_error,
            "corridor_planned_from_home": plan is not None if collision_aware else None,
        }
        seed = solution
    return entries


def passed(entries: dict[str, object], *, require_corridor: bool) -> bool:
    return all(
        bool(value["ik_solved"]) and (not require_corridor or bool(value["corridor_planned_from_home"]))
        for value in entries.values()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-supervision", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.scene_supervision.read_text())
    labels = list(data["simulator_supervision"]["objects"])
    points = [
        (str(label["actual_sim_entity_id"]), list(label["position_3d_world"]), True)
        for label in labels
    ] + [(f"bin_cell_{index:02d}", list(point), False) for index, point in enumerate(bin_cell_targets(), 1)]
    rclpy.init()
    client = CalibrationClient()
    try:
        ready = client.wait_calibration_ready() and client.apply_scene()
        records: list[dict[str, object]] = []
        populated = apply_calibration_cylinder_scene(client, labels) if ready else False
        for identifier, center, is_cylinder in points:
            empty = pose_results(client, center, collision_aware=False) if ready else {}
            exception = client.set_target_touch_exception(True, target_id=identifier) if populated and is_cylinder else False
            full = pose_results(client, center, collision_aware=True) if populated else {}
            restored = client.set_target_touch_exception(False, target_id=identifier) if exception else not is_cylinder
            records.append({
                "id": identifier, "center_world_m": center,
                "empty_scene_kinematic": empty,
                "populated_scene_corridor": full,
                "target_touch_exception_scoped": exception,
                "target_touch_exception_restored": restored,
                "passed": bool(ready and populated and restored and passed(empty, require_corridor=False) and passed(full, require_corridor=True)),
            })
        status = "ORIENTATION_FEASIBILITY_VERIFIED" if records and all(record["passed"] for record in records) else "ORIENTATION_FEASIBILITY_REJECTED"
        payload = {
            "schema_version": "M1BOrientationFeasibilityV1", "status": status,
            "scene_supervision": str(args.scene_supervision), "scene_admission": "FAIL_CLOSED",
            "primitive": "ADR-0016_VERTICAL_TOOL_TOP_GRASP", "executed_physical_motion": False,
            "records": records,
            "reason": "all spawn points and bin cells require empty-scene IK plus populated-scene collision-aware corridors",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps({"status": status, "points": len(records), "passed": sum(bool(record["passed"]) for record in records)}))
        return 0 if status == "ORIENTATION_FEASIBILITY_VERIFIED" else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
