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
import hashlib
import json
import math
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path
from statistics import median
from typing import Callable

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
from xh_agent.grasp.m1b_broker import width_window_from_perceived_diameter  # noqa: E402
from xh_agent.grasp.m1b_contact_window import M1BContactSampleV1, broker_from_window  # noqa: E402
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1  # noqa: E402


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
# The calibration-only IK sweep in the isolated zero-offset scene found the
# side-grasp final pose is reachable from 65 mm upward; 55--60 mm is not.
# Keep the 65 mm plane while retaining the tangent-tip X placement.
M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M = 0.065
M1B_NORMAL_SIDE_HAND_X_OFFSET_M = -0.080
# A calibration-only insertion starts with both board leading edges clear of
# the cylinder, then brings the already-low *open* hand in along the board
# axis.  The 120 mm boards extend 60 mm from the hand origin, so -200 mm
# leaves 115 mm between the nearest leading edge and the 25 mm-radius target.
# This avoids the old vertical path, which entered through the cylinder top
# and physically displaced it before the close command.
# All four placements keep the nearest board edge at least 35 mm outside a
# 25 mm-radius cylinder (the board reaches +60 mm from the hand origin).
# The widest point is first, but a nearer one is required when an individual
# arm-workspace branch cannot solve the wide low-clear pose.
M1B_CALIBRATION_LATERAL_INSERTION_CLEAR_HAND_X_OFFSETS_M = (-0.200, -0.160, -0.140, -0.120)
# A raised board still overlaps the upper part of the 90 mm cylinder through
# 105 mm.  These are evaluated from low to high and never alter the runtime
# primitive until a repeatable calibration result exists.
M1B_CALIBRATION_LATERAL_INSERTION_HAND_Z_OFFSETS_M = (0.065, 0.080, 0.095, 0.105)
# Coarse calibration-only yaw grid.  Each candidate preserves a horizontal
# board axis and a horizontal closing axis; the cylinder is rotationally
# symmetric, so this explores Panda reachability rather than a new object
# model.  A successful coarse cell must be repeated and then locally refined
# before it may become a production primitive.
M1B_CALIBRATION_LATERAL_INSERTION_YAWS_RAD = tuple(math.radians(value) for value in range(0, 360, 30))
M1B_CALIBRATION_VERTICAL_BOARD_HAND_X_OFFSETS_M = (-0.120, -0.080, -0.040, 0.0, 0.040, 0.080, 0.120)
M1B_CALIBRATION_VERTICAL_BOARD_HAND_Z_OFFSETS_M = (-0.040, -0.030, -0.020)
# Live calibration link-pose evidence at the settled target shows the physical
# board midpoint is 0.8 mm left of the commanded hand Y.  +1 mm is the
# approved fixed hand-chain correction; calibration-only sweeps may override
# it, but isolated sweep successes are not promoted to production defaults.
M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M = 0.001
M1B_FINGER_BOARD_THICKNESS_M = 0.010
M1B_MAX_FINGER_POSITION_M = 0.040
M1B_NEAR_REOBSERVATION_DURATION_S = 8.0
M1B_NEAR_REOBSERVATION_MAX_ASSOCIATION_DISTANCE_M = 0.050
M1B_NEAR_REOBSERVATION_FRAME_COUNT = 3
CALIBRATION_SETTLE_S = 2.0
HAND_FEEDBACK_READY_TIMEOUT_S = 12.0
# Production hand timing remains the S1-verified 0.8 s trajectory.  Any
# alternative timing must earn a calibration-only repeatability result before
# it can become the production default.
M1B_NORMAL_CLOSE_DURATION_S = 0.8


def calibration_live_model_center(entity_name: str) -> list[float]:
    """Read post-settle simulator truth for calibration initialization only."""
    command = subprocess.run(
        ["timeout", "2", "gz", "model", "-m", entity_name, "-p"],
        check=False, capture_output=True, text=True, timeout=4.0,
    )
    match = re.search(
        r"- Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*"
        r"\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]",
        command.stdout,
    )
    if match is None:
        raise RuntimeError(f"CALIBRATION_SUPERVISION_POSE_UNAVAILABLE:{entity_name}")
    return [float(value) for value in match.groups()]


def calibration_displacement_m(initial: list[float], current: list[float]) -> list[float]:
    """Evaluator-only per-axis displacement for primitive diagnosis."""
    return [float(value) - float(origin) for origin, value in zip(initial, current)]


def wait_for_finite_hand_feedback(client: CalibrationClient) -> bool:
    """Do not send the first physical hand goal before joint feedback exists."""
    deadline = time.monotonic() + HAND_FEEDBACK_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        values = [client.latest_hand.get(name, math.nan) for name in ("panda_finger_joint1", "panda_finger_joint2")]
        if all(math.isfinite(value) for value in values):
            return True
        rclpy.spin_once(client, timeout_sec=0.05)
    return False


def m1b_close_finger_targets_from_perceived_diameter(
    perceived_diameter_m: float,
) -> tuple[list[float], dict[str, float]]:
    """Turn the public perceived diameter into the physical hand command.

    ``width_window_from_perceived_diameter`` is the desired inner-pad gap.
    The Panda controller instead takes one positive-open position per finger;
    for its 18 mm boards, ``inner_gap = 2q - 0.018``.  Select the lower edge
    of the public window to produce a bounded contact preload rather than
    stopping open at its midpoint.  This is never read from simulator
    supervision or a fixture label.
    """
    lower_m, upper_m = width_window_from_perceived_diameter(perceived_diameter_m)
    selected_inner_gap_m = lower_m
    per_finger_target_m = (selected_inner_gap_m + M1B_FINGER_BOARD_THICKNESS_M) / 2.0
    if per_finger_target_m > M1B_MAX_FINGER_POSITION_M:
        raise SystemExit("public aperture is outside the physical Panda-hand capacity")
    return [per_finger_target_m, per_finger_target_m], {
        "perceived_diameter_m": perceived_diameter_m,
        "inner_pad_gap_window_m": [lower_m, upper_m],
        "selected_inner_pad_gap_m": selected_inner_gap_m,
        "finger_board_thickness_m": M1B_FINGER_BOARD_THICKNESS_M,
        "per_finger_target_m": per_finger_target_m,
        "joint_mapping": "inner_pad_gap_m = 2 * per_finger_target_m - finger_board_thickness_m",
    }


def public_track_from_evidence(
    evidence_path: Path, camera_info_path: Path, track_id: str,
    calibration: M1BStaticCameraCalibrationV1,
) -> tuple[dict[str, object], dict[str, object]]:
    """Load one selected diameter from an actual public geometric-RGB-D run.

    The tolerance runner intentionally has no switch for a fixture diameter:
    its aperture must be reproducible from a captured public observation.  A
    caller supplies the public target track selected by the production-side
    tracker; this calibration helper never looks up that selection in labels.
    """
    raw = evidence_path.read_bytes()
    evidence = json.loads(raw)
    camera = json.loads(camera_info_path.read_text(encoding="utf-8"))
    matches = [item for item in evidence.get("results", []) if item.get("track_id") == track_id]
    if len(matches) != 1:
        raise SystemExit("public perception evidence must contain exactly one selected track")
    result = matches[0]
    bbox = result.get("bbox_or_mask", {})
    intrinsics = camera.get("k", [])
    focal_m = min(float(intrinsics[0]), float(intrinsics[4])) if len(intrinsics) >= 5 else 0.0
    depth_m = float(result.get("position_3d", [0.0, 0.0, 0.0])[2])
    pixel_diameter = min(int(bbox.get("width", 0)), int(bbox.get("height", 0)))
    if focal_m <= 0.0 or depth_m <= 0.0 or pixel_diameter <= 0:
        raise SystemExit("selected public track has invalid geometry for diameter")
    diameter_m = pixel_diameter * depth_m / focal_m
    surface_optical_m = [float(value) for value in result["position_3d"]]
    center_world_m = list(calibration.visible_surface_to_center_world(tuple(surface_optical_m), diameter_m))
    return {
        "track_id": track_id,
        "visual_color": result.get("attributes", {}).get("visual_color"),
        "perceived_diameter_m": diameter_m,
        "estimated_center_world_m": center_world_m,
    }, {
        "source": "ACTUAL_PUBLIC_RGBD_GEOMETRIC_OUTPUT",
        "evidence_path": str(evidence_path),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "camera_info_path": str(camera_info_path),
        "track_id": track_id,
        "pixel_diameter": pixel_diameter,
        "depth_m": depth_m,
        "focal_px": focal_m,
    }


def capture_near_public_observation(
    output_dir: Path, *, public_pipeline_python: str,
) -> Path:
    """Capture then infer a fresh public RGB-D frame at pregrasp.

    Both child tools consume public ROS camera topics only.  They receive no
    supervision file, simulator entity name, or calibration target pose.
    """
    recorder = subprocess.run(
        [public_pipeline_python, str(ROOT / "scripts" / "record_m1b_alpha_ros.py"),
         "--output-dir", str(output_dir), "--duration-s", str(M1B_NEAR_REOBSERVATION_DURATION_S), "--sensor-only"],
        cwd=ROOT, check=False, capture_output=True, text=True, timeout=M1B_NEAR_REOBSERVATION_DURATION_S + 10.0,
    )
    if recorder.returncode != 0:
        raise RuntimeError(f"PUBLIC_RGBD_CAPTURE_FAILED:{recorder.stderr.strip() or recorder.stdout.strip()}")
    evidence_path = output_dir / "geometric.json"
    inference = subprocess.run(
        [public_pipeline_python, str(ROOT / "scripts" / "run_geometric_rgbd.py"), str(output_dir), "--output", str(evidence_path)],
        cwd=ROOT, check=False, capture_output=True, text=True, timeout=30.0,
    )
    if inference.returncode != 0:
        raise RuntimeError(f"PUBLIC_RGBD_INFERENCE_FAILED:{inference.stderr.strip() or inference.stdout.strip()}")
    return evidence_path


def select_near_public_track(
    evidence_path: Path, camera_info_path: Path, *, initial: dict[str, object],
    calibration: M1BStaticCameraCalibrationV1,
) -> tuple[dict[str, object], dict[str, object]]:
    """Associate a reobservation using public colour and static-TF geometry."""
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    candidates: list[tuple[float, dict[str, object], dict[str, object]]] = []
    initial_center = [float(value) for value in initial["estimated_center_world_m"]]
    initial_color = initial.get("visual_color")
    for result in evidence.get("results", []):
        if initial_color and result.get("attributes", {}).get("visual_color") != initial_color:
            continue
        try:
            track, metadata = public_track_from_evidence(
                evidence_path, camera_info_path, str(result["track_id"]), calibration,
            )
        except (KeyError, TypeError, ValueError, SystemExit):
            continue
        distance_m = sum((float(actual) - expected) ** 2 for actual, expected in zip(track["estimated_center_world_m"], initial_center)) ** 0.5
        candidates.append((distance_m, track, metadata))
    if not candidates:
        raise RuntimeError("PUBLIC_NEAR_REOBSERVATION_TARGET_UNMATCHED")
    distance_m, track, metadata = min(candidates, key=lambda item: item[0])
    if distance_m > M1B_NEAR_REOBSERVATION_MAX_ASSOCIATION_DISTANCE_M:
        raise RuntimeError(f"PUBLIC_NEAR_REOBSERVATION_ASSOCIATION_TOO_FAR:{distance_m:.6f}")
    metadata["association_distance_to_initial_public_center_m"] = distance_m
    return track, metadata


def _m1b_normal_side_pose(
    centre_world_m: list[float], *, hand_z_offset_m: float, hand_y_centerline_bias_m: float,
    hand_x_offset_m: float = M1B_NORMAL_SIDE_HAND_X_OFFSET_M, mirrored_x_entry: bool = False,
    hand_yaw_rad: float = 0.0,
) -> Pose:
    """Return one side-grasp hand pose; production retains yaw zero."""
    value = Pose()
    # Side grasp uses the middle of the 12 cm boards to overlap the cylinder
    # along X, then closes along Y.  A fingertip-tangent approach was measured
    # to push the free cylinder along X during the vertical descent; this
    # fixed -80 mm board-centre placement is the collision-checked branch.
    yaw_rad = math.pi if mirrored_x_entry else hand_yaw_rad
    board_x = math.cos(yaw_rad)
    board_y = math.sin(yaw_rad)
    # Preserve the production +Y bias at yaw zero while rotating it with the
    # jaw-centreline for calibration yaw candidates.
    bias_x = -math.sin(yaw_rad) * hand_y_centerline_bias_m
    bias_y = math.cos(yaw_rad) * hand_y_centerline_bias_m
    value.position.x = centre_world_m[0] + hand_x_offset_m * board_x + bias_x
    # The high precontact phase removes the old approach-graze failure mode,
    # so final descent is now centred on the public centre estimate.  A
    # closing-axis bias would turn a nominal cylindrical grasp into unilateral
    # contact and must not be silently treated as self-centring.
    value.position.y = centre_world_m[1] + hand_x_offset_m * board_y + bias_y
    value.position.z = centre_world_m[2] + hand_z_offset_m
    # Rz(yaw) * Rx(pi): yaw zero is exactly the production quaternion
    # (x=1,y=0); yaw pi is the previously tested mirrored quaternion.
    value.orientation.x = math.cos(yaw_rad / 2.0)
    value.orientation.y = math.sin(yaw_rad / 2.0)
    return value


def m1b_normal_side_precontact(
    client: CalibrationClient, centre_world_m: list[float], *, hand_y_centerline_bias_m: float,
) -> dict[str, object]:
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
            _m1b_normal_side_pose(centre_world_m, hand_z_offset_m=M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M, hand_y_centerline_bias_m=hand_y_centerline_bias_m),
            ik_seed=M1B_NORMAL_SIDE_IK_SEED,
        )
        attempts += 1
    return {
        "executed": bool(final.get("executed")),
        "converged": bool(final.get("converged")), "final": final, "attempts": attempts,
        "geometry": {"finger_board_axis_world": [1.0, 0.0, 0.0], "closing_axis_world": [0.0, 1.0, 0.0], "side_hand_x_offset_m": M1B_NORMAL_SIDE_HAND_X_OFFSET_M, "hand_y_centerline_bias_m": hand_y_centerline_bias_m, "final_y_offset_m": hand_y_centerline_bias_m, "precontact_hand_z_offset_m": M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M, "contact_hand_z_offset_m": M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M, "ik_seed_source": "measured_scene1034_collision_checked_branch", "path_source": "MoveIt collision-checked trajectory from reset home"},
    }


def m1b_normal_side_contact_descend(
    client: CalibrationClient, centre_world_m: list[float], *, ik_seed: list[float] | None, hand_y_centerline_bias_m: float,
) -> dict[str, object]:
    """Execute the contact-bearing final descent before the physical close."""
    return client.move_hand_pose(_m1b_normal_side_pose(centre_world_m, hand_z_offset_m=M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M, hand_y_centerline_bias_m=hand_y_centerline_bias_m), ik_seed=ik_seed)


def _m1b_vertical_board_pose(
    centre_world_m: list[float], *, hand_x_offset_m: float, hand_z_offset_m: float,
    hand_y_centerline_bias_m: float,
) -> Pose:
    """Calibration-only side pinch with the 120 mm boards along world Z."""
    value = Pose()
    value.position.x = centre_world_m[0] + hand_x_offset_m
    value.position.y = centre_world_m[1] + hand_y_centerline_bias_m
    value.position.z = centre_world_m[2] + hand_z_offset_m
    # Ry(-pi/2): local board X -> world +Z, local jaw Y remains world +Y.
    value.orientation.y = -math.sqrt(0.5)
    value.orientation.w = math.sqrt(0.5)
    return value


def m1b_calibration_vertical_board_ik_probe(
    client: CalibrationClient, centre_world_m: list[float], *, hand_y_centerline_bias_m: float,
) -> dict[str, object]:
    """Evaluate vertical-board end poses without moving the physical arm."""
    candidates: list[dict[str, object]] = []
    for hand_z_offset_m in M1B_CALIBRATION_VERTICAL_BOARD_HAND_Z_OFFSETS_M:
        for hand_x_offset_m in M1B_CALIBRATION_VERTICAL_BOARD_HAND_X_OFFSETS_M:
            pose = _m1b_vertical_board_pose(
                centre_world_m, hand_x_offset_m=hand_x_offset_m,
                hand_z_offset_m=hand_z_offset_m, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
            )
            # This is a new orientation family; do not bias the solver with
            # the horizontal-board branch's measured seed.  Starting from the
            # reset-home joint state makes this a genuine feasibility probe.
            solution = client.ik(pose)
            trajectory = client.plan(solution) if solution is not None else None
            candidates.append({
                "hand_x_offset_m": hand_x_offset_m, "hand_z_offset_m": hand_z_offset_m,
                "world_pose_xyz_m": [pose.position.x, pose.position.y, pose.position.z],
                "ik_solved": solution is not None,
                "planned_from_reset_home": trajectory is not None,
                "ik_error": client.last_ik_error if solution is None else None,
            })
    planned = [item for item in candidates if item["planned_from_reset_home"]]
    return {
        "executed_physical_motion": False,
        "candidate_count": len(candidates),
        "planned_candidate_count": len(planned),
        "candidates": candidates,
        "geometry": {
            "finger_board_axis_world": [0.0, 0.0, 1.0],
            "closing_axis_world": [0.0, 1.0, 0.0],
            "orientation_quaternion_xyzw": [0.0, -math.sqrt(0.5), 0.0, math.sqrt(0.5)],
        },
    }


def m1b_calibration_lateral_insertion(
    client: CalibrationClient, centre_world_m: list[float], *, hand_y_centerline_bias_m: float,
    candidate_hand_z_offsets_m: tuple[float, ...] = M1B_CALIBRATION_LATERAL_INSERTION_HAND_Z_OFFSETS_M,
    authorize_lateral_target_contact: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Prove a collision-preserving open-hand insertion before promotion.

    This is deliberately a calibration-only diagnostic.  Unlike the current
    production descent, each segment remains collision-checked against the
    target cylinder: high-and-clear, vertical descent outside the board span,
    then a lateral insertion through the open finger gap.  It therefore tests
    the causal hypothesis (vertical entry pushes the free cylinder) without
    granting an ACM exception or becoming an online truth-dependent policy.
    """
    candidate_attempts: list[dict[str, object]] = []
    lateral_contact_authorization = {"requested": authorize_lateral_target_contact is not None, "applied": False}
    for z_offset_m in candidate_hand_z_offsets_m:
        for yaw_rad in M1B_CALIBRATION_LATERAL_INSERTION_YAWS_RAD:
            family_name = f"yaw_{round(math.degrees(yaw_rad)):03d}"
            for magnitude_m in (abs(value) for value in M1B_CALIBRATION_LATERAL_INSERTION_CLEAR_HAND_X_OFFSETS_M):
                clear_x_offset_m = -magnitude_m
                final_x_offset_m = -abs(M1B_NORMAL_SIDE_HAND_X_OFFSET_M)
                low_pose = _m1b_normal_side_pose(
                    centre_world_m, hand_z_offset_m=z_offset_m,
                    hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                    hand_x_offset_m=clear_x_offset_m, hand_yaw_rad=yaw_rad,
                )
                low_seed = client.ik(low_pose, seed=M1B_NORMAL_SIDE_IK_SEED)
                if low_seed is None:
                    candidate_attempts.append({"family": family_name, "yaw_rad": yaw_rad, "clear_hand_x_offset_m": clear_x_offset_m, "hand_z_offset_m": z_offset_m, "failed_stage": "low_clear_preflight_ik", "ik_error": client.last_ik_error})
                    continue
                final_pose = _m1b_normal_side_pose(
                    centre_world_m, hand_z_offset_m=z_offset_m,
                    hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                    hand_x_offset_m=final_x_offset_m, hand_yaw_rad=yaw_rad,
                )
                final_seed = client.ik(
                    final_pose, seed=low_seed,
                    avoid_collisions=authorize_lateral_target_contact is None,
                )
                if final_seed is None:
                    candidate_attempts.append({"family": family_name, "yaw_rad": yaw_rad, "clear_hand_x_offset_m": clear_x_offset_m, "hand_z_offset_m": z_offset_m, "failed_stage": "lateral_insert_preflight_ik", "ik_error": client.last_ik_error})
                    continue
                stages: dict[str, dict[str, object]] = {}
                seed: list[float] | None = M1B_NORMAL_SIDE_IK_SEED
                for name, stage_z_offset_m, x_offset_m in (
                    ("high_clear", M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M, clear_x_offset_m),
                    ("low_clear", z_offset_m, clear_x_offset_m),
                    ("lateral_insert", z_offset_m, final_x_offset_m),
                ):
                    if name == "lateral_insert" and authorize_lateral_target_contact is not None:
                        lateral_contact_authorization["applied"] = authorize_lateral_target_contact()
                        if not lateral_contact_authorization["applied"]:
                            candidate_attempts.append({"family": family_name, "yaw_rad": yaw_rad, "clear_hand_x_offset_m": clear_x_offset_m, "hand_z_offset_m": z_offset_m, "failed_stage": "LATERAL_TARGET_CONTACT_AUTHORIZATION_REJECTED", "stages": stages})
                            return {
                                "executed": False, "converged": False, "candidate_attempts": candidate_attempts,
                                "lateral_target_contact_authorization": lateral_contact_authorization,
                                "failed_physical_candidate": {"family": family_name, "yaw_rad": yaw_rad, "clear_hand_x_offset_m": clear_x_offset_m, "hand_z_offset_m": z_offset_m},
                            }
                    stage = client.move_hand_pose(
                        _m1b_normal_side_pose(
                            centre_world_m, hand_z_offset_m=stage_z_offset_m,
                            hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                            hand_x_offset_m=x_offset_m,
                            hand_yaw_rad=yaw_rad,
                        ),
                        ik_seed=seed,
                    )
                    stages[name] = stage
                    if not (stage.get("executed") and stage.get("converged")):
                        candidate_attempts.append({"family": family_name, "yaw_rad": yaw_rad, "clear_hand_x_offset_m": clear_x_offset_m, "hand_z_offset_m": z_offset_m, "failed_stage": name, "stages": stages})
                        # A failed physical candidate can leave the simulator
                        # in contact with the table or target.  Do not chain a
                        # second candidate through that altered state; record
                        # it and require a reset-isolated follow-up instead.
                        return {
                            "executed": False, "converged": False, "candidate_attempts": candidate_attempts,
                            "lateral_target_contact_authorization": lateral_contact_authorization,
                            "failed_physical_candidate": {"family": family_name, "yaw_rad": yaw_rad, "clear_hand_x_offset_m": clear_x_offset_m, "hand_z_offset_m": z_offset_m},
                        }
                    seed = stage.get("ik_solution")
                else:
                    return {
                        "executed": True, "converged": True, "stages": stages,
                        "candidate_attempts": candidate_attempts,
                        "lateral_target_contact_authorization": lateral_contact_authorization,
                        "geometry": {
                            "insertion_axis_world": [math.cos(yaw_rad), math.sin(yaw_rad), 0.0],
                            "family": family_name,
                            "yaw_rad": yaw_rad,
                            "yaw_degrees": math.degrees(yaw_rad),
                            "clear_hand_x_offset_m": clear_x_offset_m,
                            "candidate_clear_hand_x_offsets_m": list(M1B_CALIBRATION_LATERAL_INSERTION_CLEAR_HAND_X_OFFSETS_M),
                            "candidate_hand_z_offsets_m": list(candidate_hand_z_offsets_m),
                            "final_hand_x_offset_m": final_x_offset_m,
                            "hand_z_offset_m": z_offset_m,
                        },
                    }
    return {
        "executed": False, "converged": False,
        "candidate_attempts": candidate_attempts,
        "lateral_target_contact_authorization": lateral_contact_authorization,
        "geometry": {
            "insertion_axis_world": [1.0, 0.0, 0.0],
            "yaw_candidates_degrees": [math.degrees(value) for value in M1B_CALIBRATION_LATERAL_INSERTION_YAWS_RAD],
            "candidate_clear_hand_x_offsets_m": list(M1B_CALIBRATION_LATERAL_INSERTION_CLEAR_HAND_X_OFFSETS_M),
            "candidate_hand_z_offsets_m": list(candidate_hand_z_offsets_m),
            "final_hand_x_offset_m": M1B_NORMAL_SIDE_HAND_X_OFFSET_M,
            "hand_z_offset_m": M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M,
        },
    }


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
        item.primitives = [SolidPrimitive(type=SolidPrimitive.CYLINDER, dimensions=[0.08, 0.015])]
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
    aperture_source = parser.add_mutually_exclusive_group(required=True)
    aperture_source.add_argument("--calibration-fixture-diameter-m", type=float, help="Declared physical cylinder diameter for the perception-free tolerance experiment")
    aperture_source.add_argument("--public-perception-evidence", type=Path, help="Actual public RGB-D geometric output for a production-style run")
    parser.add_argument("--public-camera-info", type=Path, help="Camera intrinsics paired with public perception evidence")
    parser.add_argument("--public-track-id", help="Production-side public target track ID")
    parser.add_argument("--public-pipeline-python", default=os.environ.get("M1B_PUBLIC_PIPELINE_PYTHON", sys.executable), help="Python with the declared public RGB-D dependencies")
    parser.add_argument("--enable-near-pregrasp-reobservation", action="store_true", help="Enable the production NO-GO remediation; excluded from the baseline tolerance envelope")
    parser.add_argument("--calibration-hand-y-bias-m", type=float, help="Calibration-only centreline sweep; absent uses the production fixed hand-chain correction")
    parser.add_argument("--calibration-keep-target-collision-through-descend", action="store_true", help="Calibration-only contact-free final-descent probe")
    parser.add_argument("--calibration-lateral-insertion", action="store_true", help="Calibration-only collision-preserving open-hand lateral insertion probe")
    parser.add_argument("--calibration-lateral-insertion-hand-z-offset-m", type=float, help="Calibration-only single lateral-insertion height")
    parser.add_argument("--calibration-lateral-insert-target-touch-exception", action="store_true", help="Calibration-only: authorize target contact only for final lateral insert")
    parser.add_argument("--calibration-vertical-board-ik-probe", action="store_true", help="Calibration-only: plan vertical-board poses without physical motion")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    trial = json.loads(args.trial.read_text(encoding="utf-8"))
    if trial.get("provenance") != "CALIBRATION_ONLY_INITIALIZATION":
        raise SystemExit("trial is not calibration-only")
    if args.calibration_hand_y_bias_m is not None and args.calibration_fixture_diameter_m is None:
        raise SystemExit("--calibration-hand-y-bias-m is calibration-only")
    if args.calibration_keep_target_collision_through_descend and args.calibration_fixture_diameter_m is None:
        raise SystemExit("--calibration-keep-target-collision-through-descend is calibration-only")
    if args.calibration_lateral_insertion and args.calibration_fixture_diameter_m is None:
        raise SystemExit("--calibration-lateral-insertion is calibration-only")
    if args.calibration_lateral_insertion and not args.calibration_keep_target_collision_through_descend:
        raise SystemExit("--calibration-lateral-insertion requires --calibration-keep-target-collision-through-descend")
    if args.calibration_lateral_insertion_hand_z_offset_m is not None:
        if not args.calibration_lateral_insertion or args.calibration_fixture_diameter_m is None:
            raise SystemExit("--calibration-lateral-insertion-hand-z-offset-m is calibration-only lateral insertion")
        if not 0.065 <= args.calibration_lateral_insertion_hand_z_offset_m <= 0.105:
            raise SystemExit("calibration lateral insertion height must be in [0.065, 0.105] m")
    if args.calibration_lateral_insert_target_touch_exception:
        if not args.calibration_lateral_insertion or args.calibration_fixture_diameter_m is None:
            raise SystemExit("--calibration-lateral-insert-target-touch-exception is calibration-only lateral insertion")
        if args.calibration_lateral_insertion_hand_z_offset_m is None:
            raise SystemExit("--calibration-lateral-insert-target-touch-exception requires one explicit lateral insertion height")
    if args.calibration_vertical_board_ik_probe and args.calibration_fixture_diameter_m is None:
        raise SystemExit("--calibration-vertical-board-ik-probe is calibration-only")
    hand_y_centerline_bias_m = M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M if args.calibration_hand_y_bias_m is None else args.calibration_hand_y_bias_m
    axis = str(trial["axis"])
    if axis not in {"x", "y", "z"}:
        raise SystemExit("trial axis must be x, y, or z")
    labels = json.loads(args.supervision.read_text(encoding="utf-8"))["simulator_supervision"]["objects"]
    normal = [label for label in labels if label["orientation_state"] == "normal"]
    if not 1 <= args.object_slot <= len(normal):
        raise SystemExit(f"object slot must be in [1, {len(normal)}]")
    target_label = normal[args.object_slot - 1]
    target_entity = str(target_label["actual_sim_entity_id"])
    # Spawn labels are not assumed to remain physical truth after gravity and
    # the mandatory settling window.  This is evaluator-only calibration
    # initialization, explicitly outside online policy input.
    time.sleep(CALIBRATION_SETTLE_S)
    truth_center = calibration_live_model_center(target_entity)
    calibration_motion: dict[str, object] | None = (
        {"initial_center_world_m": truth_center} if args.calibration_fixture_diameter_m is not None else None
    )
    target = list(truth_center)
    target["xyz".index(axis)] += float(trial["offset_m"])
    calibration: M1BStaticCameraCalibrationV1 | None = None
    initial_public_track: dict[str, object] | None = None
    if args.calibration_fixture_diameter_m is not None:
        perceived_diameter_m = args.calibration_fixture_diameter_m
        public_evidence: dict[str, object] = {"source": "CALIBRATION_FIXTURE_DECLARED_GEOMETRY", "perceived_diameter_m": perceived_diameter_m}
    else:
        if args.public_perception_evidence is None or args.public_camera_info is None or not args.public_track_id:
            raise SystemExit("public perception evidence, camera info, and target track are required together")
        calibration = M1BStaticCameraCalibrationV1.from_file(ROOT / "configs" / "m1b_camera_calibration.json")
        initial_public_track, public_evidence = public_track_from_evidence(
            args.public_perception_evidence, args.public_camera_info, args.public_track_id, calibration,
        )
        perceived_diameter_m = float(initial_public_track["perceived_diameter_m"])
    if args.enable_near_pregrasp_reobservation and initial_public_track is None:
        raise SystemExit("near-pregrasp reobservation requires public perception evidence")
    close_targets, aperture = m1b_close_finger_targets_from_perceived_diameter(perceived_diameter_m)
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
        hand_feedback_ready = client.wait_calibration_ready() and wait_for_finite_hand_feedback(client)
        ready = hand_feedback_ready and client.apply_scene()
        approach = {"executed": False, "reason": "MOVEIT_UNAVAILABLE"}
        open_hand = {"succeeded": False}
        close = {"succeeded": False}
        contact_descend = {"executed": False, "reason": "MOVEIT_UNAVAILABLE"}
        lateral_target_touch_exception_restored: bool | None = None
        vertical_board_ik_probe: dict[str, object] | None = None
        near_reobservation: dict[str, object] = {"attempted": False, "succeeded": False}
        contact_start_index = len(raw)
        if ready:
            cylinder_scene_applied = apply_calibration_cylinder_scene(client, labels)
            # Keep the target collision-checked through the entire transit to
            # high precontact.  Enabling finger/target contact early lets a
            # planner legally side-swipe the free cylinder before close,
            # which both moves the calibration target and makes stale approach
            # contacts look tempting.  Only the deliberately contact-bearing
            # descent receives this narrow exception.
            target_touch_exception_applied = False
            if args.calibration_vertical_board_ik_probe and cylinder_scene_applied:
                vertical_board_ik_probe = m1b_calibration_vertical_board_ik_probe(
                    client, target, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                )
                approach = {"executed": False, "reason": "CALIBRATION_VERTICAL_BOARD_IK_PROBE_NO_PHYSICAL_MOTION"}
            else:
                open_hand = client.command_hand([0.04, 0.04])
                approach = m1b_normal_side_precontact(client, target, hand_y_centerline_bias_m=hand_y_centerline_bias_m) if cylinder_scene_applied else {"executed": False, "reason": "CALIBRATION_COLLISION_SCENE_UNAVAILABLE"}
            # A controller action can report success while the physical arm
            # was deflected by an unmodelled/free-cylinder contact.  Do not
            # close or enter the contact-bearing descent from that state:
            # production motion acceptance requires both execution and the
            # bounded terminal convergence evidence.
            approach_motion_accepted = bool(approach.get("executed") and approach.get("converged"))
            if calibration_motion is not None:
                after_pregrasp = calibration_live_model_center(target_entity)
                calibration_motion["after_pregrasp_center_world_m"] = after_pregrasp
                calibration_motion["pregrasp_displacement_world_xyz_m"] = calibration_displacement_m(truth_center, after_pregrasp)
            if approach_motion_accepted and open_hand.get("succeeded") and not args.calibration_keep_target_collision_through_descend:
                target_touch_exception_applied = client.set_target_touch_exception(True, target_id=target_entity)
            final_target = list(target)
            if target_touch_exception_applied and args.enable_near_pregrasp_reobservation:
                assert initial_public_track is not None and calibration is not None
                near_reobservation["attempted"] = True
                near_directory = args.output.parent / f"{args.output.stem}.near_rgbd"
                try:
                    near_frames = []
                    for index in range(1, M1B_NEAR_REOBSERVATION_FRAME_COUNT + 1):
                        frame_directory = near_directory / f"frame-{index:02d}"
                        near_evidence_path = capture_near_public_observation(frame_directory, public_pipeline_python=args.public_pipeline_python)
                        near_track, near_metadata = select_near_public_track(
                            near_evidence_path, frame_directory / "camera_info.json", initial=initial_public_track, calibration=calibration,
                        )
                        near_frames.append({"evidence_path": str(near_evidence_path), "selected_public_track": near_track, "metadata": near_metadata})
                    near_track = {
                        # The per-frame geometric helper is stateless in this
                        # calibration subprocess.  Association above has
                        # already established that every frame belongs to the
                        # initial public target, so retain that canonical
                        # public ID rather than minting a new one.
                        "track_id": str(initial_public_track["track_id"]),
                        "visual_color": initial_public_track.get("visual_color"),
                        "perceived_diameter_m": median(float(frame["selected_public_track"]["perceived_diameter_m"]) for frame in near_frames),
                        "estimated_center_world_m": [median(float(frame["selected_public_track"]["estimated_center_world_m"][axis]) for frame in near_frames) for axis in range(3)],
                    }
                    close_targets, aperture = m1b_close_finger_targets_from_perceived_diameter(float(near_track["perceived_diameter_m"]))
                    public_delta = [float(current) - float(previous) for current, previous in zip(near_track["estimated_center_world_m"], initial_public_track["estimated_center_world_m"])]
                    final_target = [coordinate + delta for coordinate, delta in zip(target, public_delta)]
                    near_reobservation = {"attempted": True, "succeeded": True, "aggregation": "PER_AXIS_MEDIAN_OF_PUBLIC_RGBD_FRAMES", "frames": near_frames, "selected_public_track": near_track, "public_center_delta_world_m": public_delta, "final_target_world_m": final_target}
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    near_reobservation = {"attempted": True, "succeeded": False, "reason": str(error)}
            if (target_touch_exception_applied or args.calibration_keep_target_collision_through_descend or args.calibration_lateral_insert_target_touch_exception) and not args.enable_near_pregrasp_reobservation:
                near_reobservation = {"attempted": False, "succeeded": True, "mode": "BASELINE_PERCEPTION_FREE_TOLERANCE"}
            if args.calibration_lateral_insertion and near_reobservation.get("succeeded"):
                def authorize_lateral_target_contact() -> bool:
                    return client.set_target_touch_exception(True, target_id=target_entity)
                contact_descend = m1b_calibration_lateral_insertion(
                    client, final_target, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                    candidate_hand_z_offsets_m=(args.calibration_lateral_insertion_hand_z_offset_m,) if args.calibration_lateral_insertion_hand_z_offset_m is not None else M1B_CALIBRATION_LATERAL_INSERTION_HAND_Z_OFFSETS_M,
                    authorize_lateral_target_contact=authorize_lateral_target_contact if args.calibration_lateral_insert_target_touch_exception else None,
                )
            else:
                contact_descend = (
                    m1b_normal_side_contact_descend(client, final_target, ik_seed=approach.get("final", {}).get("ik_solution"), hand_y_centerline_bias_m=hand_y_centerline_bias_m)
                    if near_reobservation.get("succeeded") else {"executed": False, "reason": "PUBLIC_NEAR_REOBSERVATION_GATE_REJECTED"}
                )
            if args.calibration_lateral_insert_target_touch_exception:
                # This exception is narrowly scoped to the final insert.  A
                # failed candidate must leave the planning scene restored
                # before it is recorded or any later motion is considered.
                lateral_target_touch_exception_restored = client.set_target_touch_exception(False, target_id=target_entity)
            if calibration_motion is not None and contact_descend.get("executed"):
                after_descend = calibration_live_model_center(target_entity)
                calibration_motion["after_descend_center_world_m"] = after_descend
                calibration_motion["descend_displacement_world_xyz_m"] = calibration_displacement_m(truth_center, after_descend)
            # Descend while open so the cylinder enters between both pads;
            # only then close to the public perception-derived jaw width.
            # The evidence window begins immediately before that close,
            # excluding all approach contact telemetry from authorization.
            contact_start_index = len(raw)
            # Once both boards enter the free-cylinder contact zone, load can
            # move an otherwise successful controller endpoint by more than
            # the no-contact joint-settle diagnostic.  The production gate is
            # the controller terminal success here; only the non-contact
            # approach requires strict terminal convergence.
            if contact_descend.get("executed"):
                close = client.command_hand(close_targets, duration_s=M1B_NORMAL_CLOSE_DURATION_S)
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
            and close.get("succeeded") and contact_descend.get("executed")
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
            "supervision_initialization": {"orientation_state": "normal", "object_slot": args.object_slot, "actual_sim_entity_id": target_entity, "settle_s": CALIBRATION_SETTLE_S, "truth_center_source": "EVALUATOR_ONLY_GAZEBO_MODEL_POSE_AFTER_SETTLE", "truth_center_used_only_for_initial_target_pose": truth_center},
            "public_aperture_input": {**public_evidence, **aperture},
            "near_pregrasp_public_reobservation": near_reobservation,
            "baseline_perception_free": args.calibration_fixture_diameter_m is not None and not args.enable_near_pregrasp_reobservation,
            "offset_vector_m": [target[index] - truth_center[index] for index in range(3)],
            "production_grasp_primitive": "open_physical_hand + m1b_normal_side_precontact + m1b_normal_side_contact_descend + close_physical_hand + m1b_internal_bilateral_broker",
            "ready": ready, "calibration_collision_scene_applied": cylinder_scene_applied if ready else False, "target_touch_exception_applied": target_touch_exception_applied if ready else False,
            # The non-contact pregrasp must converge to its planned terminal
            # state.  The final descent deliberately permits contact to
            # prevent the controller from driving through a free cylinder;
            # its authorization comes from successful execution plus the
            # post-close bilateral same-entity window below.
            "motion_gate_contract": {
                "pregrasp_terminal_convergence_required": True,
                "contact_descend_controller_execution_required": True,
                "contact_descend_terminal_convergence_required": False,
                "contact_descend_contact_authorization": "POST_CLOSE_BILATERAL_SAME_ENTITY_WINDOW",
            },
            "hand_close_duration_s": M1B_NORMAL_CLOSE_DURATION_S,
            "calibration_hand_y_centerline_bias_m": hand_y_centerline_bias_m,
            "calibration_keep_target_collision_through_descend": args.calibration_keep_target_collision_through_descend,
            "calibration_lateral_insertion": args.calibration_lateral_insertion,
            "calibration_lateral_insertion_hand_z_offset_m": args.calibration_lateral_insertion_hand_z_offset_m,
            "calibration_lateral_insert_target_touch_exception": args.calibration_lateral_insert_target_touch_exception,
            "calibration_lateral_target_touch_exception_restored": lateral_target_touch_exception_restored,
            "calibration_vertical_board_ik_probe": vertical_board_ik_probe,
            "calibration_motion_diagnostic": calibration_motion,
            "open_hand": open_hand, "approach": approach, "close": close, "contact_descend": contact_descend,
            "hand_feedback_ready": hand_feedback_ready,
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
