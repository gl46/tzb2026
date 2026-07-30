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

from generate_industrial_scenes import bin_cell_targets  # noqa: E402
from m1a_contact_calibration_client import CalibrationClient  # noqa: E402
from run_m1b_tolerance_trial import (  # noqa: E402
    M1B_FREE_GAP_MIN_CLEARANCE_M,
    M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M,
    M1B_TOP_CONTACT_CENTERLINE_Z_M,
    M1B_TOP_PRECONTACT_STANDOFF_M,
    _m1b_top_pose,
    apply_calibration_cylinder_scene,
    m1b_calibration_free_gap_yaw,
)

# The production descent travels with the jaw fully open; corridor
# admission must therefore collision-check exactly that aperture.
SCAN_OPEN_HAND_M = [0.04, 0.04]
# Candidate production contact heights admitted by the campaign guard; the
# corridor is walked per height so the physical probes choose only among
# corridor-valid ones.
SCAN_CONTACT_HEIGHTS_M = (0.12, 0.11)
SCAN_MAX_STEP_M = 0.005
SCAN_MAX_JOINT_STEP_RAD = 0.35


def descent_corridor(
    client: CalibrationClient, center: list[float], *, yaw_rad: float,
    contact_height_m: float, max_step_m: float = SCAN_MAX_STEP_M,
) -> dict[str, object]:
    """Walk the straight open-jaw descent with seeded collision-aware IK.

    Endpoint IK feasibility is not corridor feasibility: the slot-1 probes
    measured a seeded-IK branch fold at hand offsets around +0.125 m where
    every yaw candidate jumps 0.38--0.46 rad within one 5 mm step, although
    both endpoints solve.  This is the same no-motion walk the production
    descent executes, so a scene point that fails here fails the trial.

    ``max_step_m`` is a parameter rather than the module constant so the same
    walk can be re-run at a finer resolution.  A branch fold is discrete and
    step-size dependent; a genuinely infeasible pose is not.  Re-walking a
    failing corridor at 2.5 and 1.25 mm therefore distinguishes the two without
    executing any motion and without touching the production primitive.
    """
    pregrasp = _m1b_top_pose(
        center, hand_z_offset_m=contact_height_m + M1B_TOP_PRECONTACT_STANDOFF_M,
        hand_y_centerline_bias_m=M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M, yaw_rad=yaw_rad,
    )
    seed = client.ik(pregrasp, avoid_collisions=True, hand_positions=SCAN_OPEN_HAND_M)
    if seed is None:
        return {"complete": False, "stage": "pregrasp_ik", "ik_error": client.last_ik_error}
    steps = max(2, math.ceil(M1B_TOP_PRECONTACT_STANDOFF_M / max_step_m))
    for index in range(1, steps + 1):
        offset = contact_height_m + M1B_TOP_PRECONTACT_STANDOFF_M * (1.0 - index / steps)
        pose = _m1b_top_pose(
            center, hand_z_offset_m=offset,
            hand_y_centerline_bias_m=M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M, yaw_rad=yaw_rad,
        )
        solution = client.ik(pose, seed=seed, avoid_collisions=True, hand_positions=SCAN_OPEN_HAND_M)
        if solution is None:
            return {
                "complete": False, "stage": "waypoint_ik",
                "failed_hand_z_offset_m": offset, "ik_error": client.last_ik_error,
            }
        joint_step = max(abs(current - previous) for current, previous in zip(solution, seed))
        if joint_step > SCAN_MAX_JOINT_STEP_RAD:
            return {
                "complete": False, "stage": "joint_jump",
                "failed_hand_z_offset_m": offset,
                "max_observed_joint_step_rad": joint_step,
            }
        seed = solution
    return {"complete": True}


def cylinder_descent_corridors(
    client: CalibrationClient, labels: list[dict[str, object]], identifier: str,
    center: list[float],
) -> dict[str, object]:
    """Evaluate free-gap yaw candidates and per-height descent corridors."""
    free_gap = m1b_calibration_free_gap_yaw(labels, identifier)
    ranked = sorted(
        [c for c in free_gap["candidates"] if c["min_clearance_m"] >= M1B_FREE_GAP_MIN_CLEARANCE_M],
        key=lambda c: -float(c["min_clearance_m"]),
    )
    yaw_candidates: list[float] = []
    for candidate in ranked[:2]:
        for flip in (0.0, math.pi):
            value = (float(candidate["yaw_rad"]) + flip) % (2.0 * math.pi)
            if value not in yaw_candidates:
                yaw_candidates.append(value)
    heights: dict[str, object] = {}
    for height in SCAN_CONTACT_HEIGHTS_M:
        attempts = []
        selected = None
        for yaw_value in yaw_candidates:
            walk = descent_corridor(client, center, yaw_rad=yaw_value, contact_height_m=height)
            attempts.append({"yaw_rad": yaw_value, **walk})
            if walk["complete"]:
                selected = yaw_value
                break
        heights[f"{height:.2f}"] = {
            "corridor_complete": selected is not None,
            "selected_yaw_rad": selected,
            "attempts": attempts,
        }
    return {
        "free_gap_yaw": {
            "selected_yaw_rad": free_gap["selected_yaw_rad"],
            "min_clearance_m": free_gap["min_clearance_m"],
            "clearance_ok": free_gap["clearance_ok"],
        },
        "contact_heights": heights,
        "any_height_complete": any(value["corridor_complete"] for value in heights.values()),
    }


def descent_step_probe(
    client: CalibrationClient, labels: list[dict[str, object]], identifier: str,
    center: list[float], *, offset_m: list[float], step_sizes_m: tuple[float, ...],
) -> dict[str, object]:
    """Re-walk one offset pose's descent at several step resolutions.

    Answers a single question with no motion: when the production descent
    aborts on CARTESIAN_JOINT_JUMP_REJECTED, is the solver crossing a discrete
    IK branch that a finer step would stay on, or is the pose simply outside
    the arm's reach there?  Every measured near-band abort had all three yaw
    candidates exhausted, which is what a real boundary looks like, so this is
    a genuine test and not a formality.
    """
    offset_center = [value + delta for value, delta in zip(center, offset_m)]
    free_gap = m1b_calibration_free_gap_yaw(labels, identifier)
    ranked = sorted(
        [c for c in free_gap["candidates"] if c["min_clearance_m"] >= M1B_FREE_GAP_MIN_CLEARANCE_M],
        key=lambda c: -float(c["min_clearance_m"]),
    )
    yaw_candidates: list[float] = []
    for candidate in ranked[:2]:
        for flip in (0.0, math.pi):
            value = (float(candidate["yaw_rad"]) + flip) % (2.0 * math.pi)
            if value not in yaw_candidates:
                yaw_candidates.append(value)
    by_step: dict[str, object] = {}
    for step_m in step_sizes_m:
        attempts = []
        for yaw_value in yaw_candidates:
            walk = descent_corridor(
                client, offset_center, yaw_rad=yaw_value,
                contact_height_m=M1B_TOP_CONTACT_CENTERLINE_Z_M, max_step_m=step_m,
            )
            attempts.append({"yaw_rad": yaw_value, **walk})
            if walk["complete"]:
                break
        by_step[f"{step_m*1000:.2f}mm"] = {
            "any_yaw_complete": any(a["complete"] for a in attempts),
            "attempts": attempts,
        }
    coarse = by_step.get(f"{step_sizes_m[0]*1000:.2f}mm", {})
    finest = by_step.get(f"{step_sizes_m[-1]*1000:.2f}mm", {})
    return {
        "identifier": identifier,
        "spawn_center_world_m": list(center),
        "offset_m": list(offset_m),
        "offset_center_world_m": offset_center,
        "contact_height_m": M1B_TOP_CONTACT_CENTERLINE_Z_M,
        "by_step": by_step,
        "recovered_by_finer_step": bool(
            not coarse.get("any_yaw_complete") and finest.get("any_yaw_complete")
        ),
    }


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
        solution = client.ik(pose, avoid_collisions=collision_aware, seed=seed, hand_positions=SCAN_OPEN_HAND_M)
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


PROBE_STEP_SIZES_M = (0.005, 0.0025, 0.00125)


def run_descent_step_probe(args, labels: list[dict[str, object]]) -> int:
    """Diagnostic entry point: no motion, no gate, no acceptance consequence."""
    centers = {
        str(label["actual_sim_entity_id"]): list(label["position_3d_world"])
        for label in labels
    }
    requests = []
    for spec in args.probe_entity:
        entity, axis, offset_mm = spec.split(":")
        if entity not in centers:
            raise SystemExit(f"UNKNOWN_PROBE_ENTITY:{entity}")
        if axis not in "xyz":
            raise SystemExit(f"UNKNOWN_PROBE_AXIS:{axis}")
        offset = [0.0, 0.0, 0.0]
        offset["xyz".index(axis)] = float(offset_mm) / 1000.0
        requests.append((entity, axis, offset))
    if not requests:
        raise SystemExit("NO_PROBE_ENTITY_SUPPLIED")
    rclpy.init()
    client = CalibrationClient()
    try:
        ready = client.wait_calibration_ready() and client.apply_scene()
        populated = apply_calibration_cylinder_scene(client, labels) if ready else False
        if not populated:
            raise SystemExit("PROBE_SCENE_UNAVAILABLE")
        results = []
        for entity, axis, offset in requests:
            exception = client.set_target_touch_exception(True, target_id=entity)
            probe = (
                descent_step_probe(
                    client, labels, entity, centers[entity],
                    offset_m=offset, step_sizes_m=PROBE_STEP_SIZES_M,
                )
                if exception else {"error": "TARGET_TOUCH_EXCEPTION_NOT_SCOPED"}
            )
            restored = client.set_target_touch_exception(False, target_id=entity) if exception else False
            results.append({**probe, "axis": axis, "target_touch_exception_restored": restored})
        payload = {
            "schema_version": "M1BDescentStepProbeV1",
            "provenance": "DIAGNOSTIC_ONLY_NO_EXECUTED_MOTION",
            "question": (
                "Do the measured near-band CARTESIAN_JOINT_JUMP_REJECTED aborts survive a "
                "finer descent step, or are they a discrete IK branch fold that a finer step "
                "stays on?"
            ),
            "step_sizes_m": list(PROBE_STEP_SIZES_M),
            "max_joint_step_rad": SCAN_MAX_JOINT_STEP_RAD,
            "scene_supervision": str(args.scene_supervision),
            "results": results,
            "recovered_count": sum(1 for r in results if r.get("recovered_by_finer_step")),
            "online_truth_access": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "recovered": payload["recovered_count"], "probed": len(results),
        }))
        return 0
    finally:
        client.destroy_node()
        rclpy.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-supervision", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--descent-step-probe", action="store_true",
        help="diagnostic only: re-walk the measured near-band aborts at finer step sizes",
    )
    parser.add_argument(
        "--probe-entity", action="append", default=[],
        help="with --descent-step-probe: ENTITY:AXIS:OFFSET_MM, e.g. cylinder_01:z:+5",
    )
    args = parser.parse_args()
    data = json.loads(args.scene_supervision.read_text())
    labels = list(data["simulator_supervision"]["objects"])
    if args.descent_step_probe:
        return run_descent_step_probe(args, labels)
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
            descent = (
                cylinder_descent_corridors(client, labels, identifier, center)
                if populated and is_cylinder and exception else None
            )
            restored = client.set_target_touch_exception(False, target_id=identifier) if exception else not is_cylinder
            records.append({
                "id": identifier, "center_world_m": center,
                "empty_scene_kinematic": empty,
                "populated_scene_corridor": full,
                "descent_corridor": descent,
                "target_touch_exception_scoped": exception,
                "target_touch_exception_restored": restored,
                "passed": bool(
                    ready and populated and restored
                    and (
                        # A cylinder's production feasibility is its selected
                        # free-gap-yaw descent corridor (which subsumes both
                        # endpoint IKs at the acting yaw); the fixed yaw-0
                        # endpoint entries remain recorded as diagnostics.
                        (descent is not None and descent["any_height_complete"])
                        if is_cylinder
                        else (passed(empty, require_corridor=False) and passed(full, require_corridor=True))
                    )
                ),
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
