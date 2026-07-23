#!/usr/bin/env python3
"""Run one reset-isolated M1B calibration or public-production grasp.

Calibration mode admits privileged supervision only for the pre-authorized
tolerance experiment. Public-production mode rejects every supervision input,
constructs target and obstacle proxies from public RGB-D tracks, and asks the
broker to identify an attached entity only from physical bilateral contacts.
An outer runner owns the mandatory full reset and calibration worklist.
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
from moveit_msgs.msg import CollisionObject, PlanningScene, PlanningSceneComponents
from moveit_msgs.srv import GetPlanningScene
from ros_gz_interfaces.msg import Contacts
from shape_msgs.msg import SolidPrimitive

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from m1a_contact_calibration_client import CalibrationClient  # noqa: E402
from xh_agent.grasp.m1b_broker import width_window_from_perceived_diameter  # noqa: E402
from xh_agent.grasp.m1b_contact_window import M1BContactSampleV1, broker_from_window  # noqa: E402
from xh_agent.grasp.contact_seek import descending_contact_seek_offsets_m  # noqa: E402
from xh_agent.runtime.m1b_center_correction import M1BPublicGeometryXYCorrectionV1, M1BTableSupportedCylinderCenterV1  # noqa: E402
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
# ADR-0016 S0 measured that the inline tapered tip extends beyond the named
# main pad.  On a 30 mm cylinder at the table, a 100 mm hand offset puts that
# tip into the tabletop; 140 mm preserves upper-sidewall overlap while giving
# the tip the measured 5 mm table clearance.
# ADR-0016b (franka-copy hand) re-measured the centreline with bounded
# zero-offset probes: 100 mm fails the descent corridor (seeded-IK branch
# fold), 110 mm passed 2/4 with single-sided dead-band failures, and 120 mm
# passed the full bilateral+attach predicate 2/2 under the two-stage close,
# so the production centreline remains the measured 120 mm.
M1B_TOP_CONTACT_CENTERLINE_Z_M = 0.120
M1B_TOP_PRECONTACT_STANDOFF_M = 0.150
# ADR-0013 Amendment 2: replace the fixed final height only when this explicit
# primitive is selected.  The search always moves along the already-verified
# straight tool axis; it cannot use a truth pose or a contact identity to
# choose an endpoint.  A physical same-entity bilateral window is the sole
# stop signal, otherwise the primitive fails before close/attach.
M1B_CONTACT_SEEK_MIN_HAND_Z_OFFSET_M = 0.060
M1B_CONTACT_SEEK_STEP_M = 0.005
M1B_CONTACT_SEEK_WAYPOINT_DURATION_S = 0.50
M1B_CONTACT_SEEK_OBSERVATION_S = 0.15
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
M1B_CALIBRATION_TARGET_HEIGHT_LIFTS_M = (0.0, 0.010, 0.020, 0.030, 0.040, 0.060, 0.080, 0.100)
# Live calibration link-pose evidence at the settled target shows the physical
# board midpoint is 0.8 mm left of the commanded hand Y.  +1 mm is the
# approved fixed hand-chain correction; calibration-only sweeps may override
# it, but isolated sweep successes are not promoted to production defaults.
M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M = 0.001
# ADR-0016 pre-authorized fallback hand: the public inner-pad gap is
# 2q - 0.006 while each pad's collision face is modelled 6.5 mm proud of its
# finger-link y=0 plane.  The 0.5 mm-per-side difference is measured engine
# compensation: the live M1B diagnostic recorded a 2-3 mm shallow-penetration
# dead band in bullet-featherstone contact generation against free dynamic
# bodies (0 events at 2 mm commanded overlap vs >1000 at 3.5 mm), so the
# ADR-0013 window-edge close command must land its modelled overlap about
# 4.5 mm inside a centred target to guarantee a persistent stall force.
M1B_FINGER_BOARD_THICKNESS_M = 0.006
# Measured close margin: command the jaw this far below the perceived
# diameter so both position-controlled fingers stall against the target with
# sustained force instead of stopping at a zero-force kiss.  Frozen from the
# bounded ADR-0016b zero-offset probes on the franka-copy hand: kiss
# (squeeze 0) produced single-sided ghost contact and no bilateral window,
# while the 2 mm window-edge squeeze with the two-stage close measured
# bilateral same-entity windows of 0.20-0.66 s and confirmed attaches (2/2
# at the 120 mm centreline).  The ADR-0013 window's lower edge still bounds
# every command.
M1B_CLOSE_SQUEEZE_M = 0.002
M1B_MAX_FINGER_POSITION_M = 0.040
# The approved current industrial class is 30 mm in diameter.  Bounding a
# production aperture estimate to this deliberately broad public class band
# rejects components whose long visible axis was mistaken for their diameter;
# accepting such a value would command an open jaw that cannot contact a
# 30 mm cylinder.  This is a public observation gate, never a label lookup.
M1B_PUBLIC_INDUSTRIAL_DIAMETER_RANGE_M = (0.020, 0.040)
M1B_NEAR_REOBSERVATION_DURATION_S = 8.0
M1B_NEAR_REOBSERVATION_MAX_ASSOCIATION_DISTANCE_M = 0.050
M1B_NEAR_REOBSERVATION_FRAME_COUNT = 3
CALIBRATION_SETTLE_S = 2.0
HAND_FEEDBACK_READY_TIMEOUT_S = 12.0
# Production hand timing remains the S1-verified 0.8 s trajectory.  Any
# alternative timing must earn a calibration-only repeatability result before
# it can become the production default.
M1B_NORMAL_CLOSE_DURATION_S = 0.8


# Calibration-only free-gap yaw selection.  ADR-0016 §2 makes the production
# top-grasp yaw a perception free-gap output (--public-free-gap-yaw-rad); the
# perception-free tolerance experiment previously pinned yaw 0, which aims the
# open jaw straight at whatever neighbour happens to sit on the closing axis.
# The straight cartesian descent then fail-closes on that neighbour's planning
# primitive (probe evidence: fraction 0.71 toward slot 1, neighbour 70 mm away
# on -y while the open finger sweep extends 51.4 mm half-width).  Deriving the
# yaw from the supervision labels is the same class of calibration-only
# initialization as the target centre itself.
M1B_CALIBRATION_FREE_GAP_YAW_CANDIDATES_RAD = tuple(math.radians(v) for v in range(0, 180, 15))
M1B_FINGER_SWEEP_BOUND_RADIUS_M = 0.0148  # half-diagonal of the 0.021 x 0.0208 plate footprint
M1B_FINGER_SWEEP_CENTER_OFFSET_M = 0.0039  # plate-box centre beyond the finger origin
M1B_FREE_GAP_MIN_CLEARANCE_M = 0.005
# The reset lifecycle hands the trial an arm at the SRDF home posture, and
# the corridor pre-scan validates each descent from a home-seeded pregrasp
# branch.  A yaw retry must therefore re-enter through home: re-planning the
# pregrasp from the failed descend posture selects a different IK branch
# whose corridor was never admitted (measured: the same 270-degree descent
# completes home-seeded but jumps 0.38 rad when re-approached in place).
M1B_RESET_HOME_JOINTS_RAD = [0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0]


def m1b_free_gap_yaw_from_xy(
    target_xy: list[float], neighbors: list[list[float]], *, source: str,
    open_finger_m: float = 0.04, neighbor_radius_m: float = 0.015,
) -> dict[str, object]:
    """Pick the safest open-jaw descent yaw from one explicit XY scene.

    The caller determines the source of the coordinates.  This shared helper
    keeps the calibration-label geometry deliberately separate from the
    production public-RGB-D geometry rather than quietly converting either
    representation into the other.
    """
    arm_offset = open_finger_m + M1B_FINGER_SWEEP_CENTER_OFFSET_M
    candidates = []
    for yaw_rad in M1B_CALIBRATION_FREE_GAP_YAW_CANDIDATES_RAD:
        closing = (math.sin(yaw_rad), -math.cos(yaw_rad))
        clearance = math.inf
        for sign in (1.0, -1.0):
            centre = (target_xy[0] + sign * arm_offset * closing[0], target_xy[1] + sign * arm_offset * closing[1])
            for neighbor in neighbors:
                distance = math.hypot(centre[0] - neighbor[0], centre[1] - neighbor[1])
                clearance = min(clearance, distance - M1B_FINGER_SWEEP_BOUND_RADIUS_M - neighbor_radius_m)
        candidates.append({"yaw_rad": yaw_rad, "min_clearance_m": clearance})
    best = max(candidates, key=lambda item: item["min_clearance_m"])
    return {
        "selected_yaw_rad": best["yaw_rad"],
        "min_clearance_m": best["min_clearance_m"],
        "clearance_ok": best["min_clearance_m"] >= M1B_FREE_GAP_MIN_CLEARANCE_M,
        "candidates": candidates,
        "source": source,
    }


def m1b_calibration_free_gap_yaw(
    labels: list[dict[str, object]], target_entity: str, *, open_finger_m: float = 0.04,
    neighbor_radius_m: float = 0.015,
) -> dict[str, object]:
    """Pick the descent yaw whose open-jaw sweep clears calibration labels."""
    target = next(label for label in labels if str(label["actual_sim_entity_id"]) == target_entity)
    target_xy = [float(v) for v in target["position_3d_world"][:2]]
    neighbors = [
        [float(v) for v in label["position_3d_world"][:2]]
        for label in labels if str(label["actual_sim_entity_id"]) != target_entity
    ]
    return m1b_free_gap_yaw_from_xy(
        target_xy, neighbors, source="CALIBRATION_LABEL_FREE_GAP_GEOMETRY",
        open_finger_m=open_finger_m, neighbor_radius_m=neighbor_radius_m,
    )


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
    perceived_diameter_m: float, *, squeeze_m: float | None = None,
) -> tuple[list[float], dict[str, float]]:
    """Turn the public perceived diameter into the physical hand command.

    ``width_window_from_perceived_diameter`` is the desired inner-pad gap.
    The Panda controller instead takes one positive-open position per finger;
    for the franka-copy pads with faces on the link y=0 planes,
    ``inner_gap = 2q``.  Select the perceived diameter minus the measured
    close squeeze, clamped to the public window, so both fingers stall on the
    target with sustained force rather than ending at a zero-force kiss.
    This is never read from simulator supervision or a fixture label.
    """
    selected_squeeze_m = M1B_CLOSE_SQUEEZE_M if squeeze_m is None else squeeze_m
    lower_m, upper_m = width_window_from_perceived_diameter(perceived_diameter_m)
    selected_inner_gap_m = min(upper_m, max(lower_m, perceived_diameter_m - selected_squeeze_m))
    per_finger_target_m = (selected_inner_gap_m + M1B_FINGER_BOARD_THICKNESS_M) / 2.0
    if per_finger_target_m > M1B_MAX_FINGER_POSITION_M:
        raise SystemExit("public aperture is outside the physical Panda-hand capacity")
    return [per_finger_target_m, per_finger_target_m], {
        "perceived_diameter_m": perceived_diameter_m,
        "inner_pad_gap_window_m": [lower_m, upper_m],
        "close_squeeze_m": selected_squeeze_m,
        "selected_inner_pad_gap_m": selected_inner_gap_m,
        "finger_board_thickness_m": M1B_FINGER_BOARD_THICKNESS_M,
        "per_finger_target_m": per_finger_target_m,
        "joint_mapping": "inner_pad_gap_m = 2 * per_finger_target_m - finger_board_thickness_m",
    }


def public_track_from_evidence(
    evidence_path: Path, camera_info_path: Path, track_id: str,
    calibration: M1BStaticCameraCalibrationV1,
    xy_correction: M1BPublicGeometryXYCorrectionV1,
    table_supported_z: M1BTableSupportedCylinderCenterV1,
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
    if not M1B_PUBLIC_INDUSTRIAL_DIAMETER_RANGE_M[0] <= diameter_m <= M1B_PUBLIC_INDUSTRIAL_DIAMETER_RANGE_M[1]:
        raise SystemExit("selected public track diameter is outside the approved industrial-cylinder class band")
    surface_optical_m = [float(value) for value in result["position_3d"]]
    if len(surface_optical_m) != 3:
        raise SystemExit("selected public track has invalid surface geometry")
    orientation_state = str(result.get("orientation_state", "unknown"))
    quality = result.get("covariance_or_quality", {})
    try:
        support_optical_m = [float(quality[f"support_plane_optical_{axis}_m"]) for axis in ("x", "y", "z")]
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"selected public track lacks support-plane geometry:{error}") from error
    try:
        baseline_center = calibration.visible_surface_to_center_world(tuple(surface_optical_m), diameter_m)
        xy_center = xy_correction.correct_xy(
            baseline_center, surface_optical_m=tuple(surface_optical_m), perceived_diameter_m=diameter_m,
            orientation_state=orientation_state,
        )
        center_world_m = list(table_supported_z.correct_z(
            xy_center, calibration.optical_to_world(tuple(support_optical_m)),
        ))
    except ValueError as error:
        raise SystemExit(f"PUBLIC_GEOMETRY_CENTER_GATE_REJECTED:{error}") from error
    return {
        "track_id": track_id,
        "visual_color": result.get("attributes", {}).get("visual_color"),
        "public_orientation_state": orientation_state,
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
        "surface_optical_m": surface_optical_m,
        "support_plane_optical_m": support_optical_m,
        "xy_correction_fingerprint": xy_correction.fingerprint,
        "table_supported_z_fingerprint": table_supported_z.fingerprint,
        "center_estimator": "public_rgbd_surface + frozen_public_geometry_xy + public_rgbd_support_plane_z",
    }


def public_tracks_from_evidence(
    evidence_path: Path, camera_info_path: Path,
    calibration: M1BStaticCameraCalibrationV1,
    xy_correction: M1BPublicGeometryXYCorrectionV1,
    table_supported_z: M1BTableSupportedCylinderCenterV1,
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    """Build a planning scene solely from valid public RGB-D tracks.

    The rejection list is evidence, not a cue to fall back to a Gazebo model
    name or pose.  A requested target absent from the returned mapping is a
    fail-closed production admission failure.
    """
    raw = json.loads(evidence_path.read_text(encoding="utf-8"))
    tracks: dict[str, dict[str, object]] = {}
    rejected: list[dict[str, str]] = []
    for result in raw.get("results", []):
        track_id = str(result.get("track_id", ""))
        if not track_id or track_id in tracks:
            rejected.append({"track_id": track_id or "<missing>", "reason": "MISSING_OR_DUPLICATE_TRACK_ID"})
            continue
        try:
            track, _ = public_track_from_evidence(
                evidence_path, camera_info_path, track_id,
                calibration, xy_correction, table_supported_z,
            )
        except (OSError, ValueError, SystemExit) as error:
            rejected.append({"track_id": track_id, "reason": str(error)})
            continue
        tracks[track_id] = track
    return tracks, {
        "source": "ACTUAL_PUBLIC_RGBD_GEOMETRIC_OUTPUT",
        "valid_track_count": len(tracks),
        "rejected_tracks": rejected,
        "xy_correction_fingerprint": xy_correction.fingerprint,
        "table_supported_z_fingerprint": table_supported_z.fingerprint,
    }


def m1b_public_free_gap_yaw(
    tracks: dict[str, dict[str, object]], target_track_id: str,
) -> dict[str, object]:
    """Choose the production descent yaw from public RGB-D centres only."""
    target = tracks.get(target_track_id)
    if target is None:
        raise SystemExit("PUBLIC_TARGET_TRACK_NOT_ADMITTED_TO_PLANNING_SCENE")
    target_xy = [float(value) for value in target["estimated_center_world_m"][:2]]
    neighbours = [
        [float(value) for value in track["estimated_center_world_m"][:2]]
        for track_id, track in tracks.items() if track_id != target_track_id
    ]
    return m1b_free_gap_yaw_from_xy(
        target_xy, neighbours, source="PUBLIC_RGBD_FREE_GAP_GEOMETRY",
    )


def public_collision_id(track_id: str) -> str:
    """Keep public tracking IDs distinct from simulator entity identifiers."""
    return f"m1b_public_{track_id}"


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
    xy_correction: M1BPublicGeometryXYCorrectionV1,
    table_supported_z: M1BTableSupportedCylinderCenterV1,
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
                evidence_path, camera_info_path, str(result["track_id"]), calibration, xy_correction, table_supported_z,
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


def _m1b_top_pose(
    centre_world_m: list[float], *, hand_z_offset_m: float,
    hand_y_centerline_bias_m: float, yaw_rad: float,
) -> Pose:
    """Return ADR-0016's vertical-tool inline-hand pose.

    Local +Z is the re-oriented finger-board axis and maps to world down.
    The target centre lies at the measured pad centre-line, 100 mm distal to
    the hand origin, so the compact palm remains above a 30 mm cylinder.
    """
    value = Pose()
    # Rz(yaw) Rx(pi): local +Z -> world down; local +/-Y still close the jaw.
    value.orientation.x = math.cos(yaw_rad / 2.0)
    value.orientation.y = math.sin(yaw_rad / 2.0)
    value.orientation.z = 0.0
    value.orientation.w = 0.0
    # The centre-line correction remains along the rotating closing direction.
    value.position.x = centre_world_m[0] + math.sin(yaw_rad) * hand_y_centerline_bias_m
    value.position.y = centre_world_m[1] - math.cos(yaw_rad) * hand_y_centerline_bias_m
    value.position.z = centre_world_m[2] + hand_z_offset_m
    return value


def m1b_top_down_precontact(
    client: CalibrationClient, centre_world_m: list[float], *, hand_y_centerline_bias_m: float,
    yaw_rad: float,
) -> dict[str, object]:
    """Execute the sole ADR-0016 M1B production pick family's pregrasp."""
    final = {"executed": False}
    attempts = 0
    while attempts < 3 and not final.get("executed"):
        final = client.move_hand_pose(
            _m1b_top_pose(
                centre_world_m,
                hand_z_offset_m=M1B_TOP_CONTACT_CENTERLINE_Z_M + M1B_TOP_PRECONTACT_STANDOFF_M,
                hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                yaw_rad=yaw_rad,
            ),
        )
        attempts += 1
    return {
        "executed": bool(final.get("executed")), "converged": bool(final.get("converged")),
        "final": final, "attempts": attempts,
        "geometry": {
            "finger_board_axis_world": [0.0, 0.0, -1.0],
            "tool_axis_world": [0.0, 0.0, -1.0],
            "closing_axis_world": [math.sin(yaw_rad), -math.cos(yaw_rad), 0.0],
            "contact_centerline_z_m": M1B_TOP_CONTACT_CENTERLINE_Z_M,
            "precontact_hand_z_offset_m": M1B_TOP_CONTACT_CENTERLINE_Z_M + M1B_TOP_PRECONTACT_STANDOFF_M,
            "contact_hand_z_offset_m": M1B_TOP_CONTACT_CENTERLINE_Z_M,
            "yaw_rad": yaw_rad,
            "path_source": "MoveIt collision-checked vertical-tool trajectory from reset home",
        },
    }


def m1b_top_down_contact_descend(
    client: CalibrationClient, centre_world_m: list[float], *,
    hand_y_centerline_bias_m: float, yaw_rad: float,
) -> dict[str, object]:
    """Descend vertically to the pad centre-line on a straight cartesian path.

    An OMPL joint-space descend between the same endpoints may bow sideways;
    with the finger/target ACM exception active that bow was measured to
    displace the free target 10--18 mm before the close (campaign raws
    000/027/044), which converts a nominal centred grasp into a unilateral
    press.  The cartesian segment keeps the tool axis on the vertical line
    and is still collision-checked against the scene and current ACM.
    """
    result = client.move_hand_cartesian(
        _m1b_top_pose(
            centre_world_m, hand_z_offset_m=M1B_TOP_CONTACT_CENTERLINE_Z_M,
            hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_rad,
        ),
        duration_s=3.0,
    )
    result["path_source"] = "MoveIt computeCartesianPath straight vertical descent"
    return result


def m1b_top_down_contact_seek_descent(
    client: CalibrationClient, centre_world_m: list[float], *,
    hand_y_centerline_bias_m: float, yaw_rad: float,
    contact_samples_since_seek_start: Callable[[], list[M1BContactSampleV1]],
) -> dict[str, object]:
    """Seek a physical bilateral contact window along the vertical tool axis.

    The caller has already executed the measured, continuous precontact-to-
    120 mm Cartesian descent. This function deliberately avoids using the
    target's simulator identity or pose as a stop condition. Each subsequent
    5 mm downward waypoint is a normal collision-aware MoveIt Cartesian
    action. After it settles, the existing actuator-internal broker must
    observe a 100 ms same-entity bilateral window; one-sided, table, unknown,
    and no-contact observations all continue or fail closed.
    """

    waypoints: list[dict[str, object]] = []
    deadline = time.monotonic() + M1B_CONTACT_SEEK_OBSERVATION_S
    while time.monotonic() < deadline:
        rclpy.spin_once(client, timeout_sec=0.02)
    feedback, internal = broker_from_window(contact_samples_since_seek_start())
    initial_entry: dict[str, object] = {
        "hand_z_offset_m": M1B_TOP_CONTACT_CENTERLINE_Z_M,
        "motion": "MEASURED_CONTINUOUS_BASELINE_DESCENT",
        "broker_feedback": {
            "grasp_success": feedback.grasp_success,
            "tactile_state": feedback.tactile_state,
            "reobservation_required": feedback.reobservation_required,
        },
        "internal_actuation_record": internal,
    }
    waypoints.append(initial_entry)
    if feedback.grasp_success:
        return {
            "executed": True, "converged": True,
            "seek_contact_found": True,
            "contact_hand_z_offset_m": M1B_TOP_CONTACT_CENTERLINE_Z_M,
            "seek_feedback": initial_entry["broker_feedback"],
            "waypoints": waypoints,
            "path_source": "MEASURED_BASELINE_THEN_STAGED_VERTICAL_CONTACT_SEEK",
        }

    ik_seed: list[float] | None = None
    for hand_z_offset_m in descending_contact_seek_offsets_m(
        start_m=M1B_TOP_CONTACT_CENTERLINE_Z_M - M1B_CONTACT_SEEK_STEP_M,
        minimum_m=M1B_CONTACT_SEEK_MIN_HAND_Z_OFFSET_M,
        step_m=M1B_CONTACT_SEEK_STEP_M,
    ):
        motion = client.move_hand_cartesian(
            _m1b_top_pose(
                centre_world_m, hand_z_offset_m=hand_z_offset_m,
                hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_rad,
            ),
            duration_s=M1B_CONTACT_SEEK_WAYPOINT_DURATION_S,
            ik_seed=ik_seed,
        )
        entry: dict[str, object] = {
            "hand_z_offset_m": hand_z_offset_m,
            "motion": motion,
        }
        if not motion.get("executed"):
            entry["seek_result"] = "MOTION_REJECTED"
            waypoints.append(entry)
            return {
                "executed": False, "converged": False,
                "seek_contact_found": False,
                "reason": f"CONTACT_SEEK_{motion.get('reason', 'WAYPOINT_MOTION_REJECTED')}",
                "motion_failure_reason": motion.get("reason"),
                "waypoints": waypoints,
            }
        expected = motion.get("expected_final_joints")
        if not isinstance(expected, list) or len(expected) != 7:
            entry["seek_result"] = "MOTION_ENDPOINT_SEED_UNAVAILABLE"
            waypoints.append(entry)
            return {
                "executed": False, "converged": False,
                "seek_contact_found": False,
                "reason": "CONTACT_SEEK_MOTION_ENDPOINT_SEED_UNAVAILABLE",
                "waypoints": waypoints,
            }
        ik_seed = [float(value) for value in expected]
        deadline = time.monotonic() + M1B_CONTACT_SEEK_OBSERVATION_S
        while time.monotonic() < deadline:
            rclpy.spin_once(client, timeout_sec=0.02)
        feedback, internal = broker_from_window(contact_samples_since_seek_start())
        entry["broker_feedback"] = {
            "grasp_success": feedback.grasp_success,
            "tactile_state": feedback.tactile_state,
            "reobservation_required": feedback.reobservation_required,
        }
        entry["internal_actuation_record"] = internal
        waypoints.append(entry)
        if feedback.grasp_success:
            return {
                "executed": True, "converged": bool(motion.get("converged")),
                "seek_contact_found": True,
                "contact_hand_z_offset_m": hand_z_offset_m,
                "seek_feedback": entry["broker_feedback"],
                "waypoints": waypoints,
                "path_source": "MOVEIT_STAGED_VERTICAL_CONTACT_SEEK",
            }
    return {
        "executed": True, "converged": True,
        "seek_contact_found": False,
        "reason": "CONTACT_SEEK_BILATERAL_WINDOW_NOT_OBSERVED",
        "waypoints": waypoints,
        "path_source": "MOVEIT_STAGED_VERTICAL_CONTACT_SEEK",
    }


def m1b_top_down_contact_descend_with_seek(
    client: CalibrationClient, centre_world_m: list[float], *,
    hand_y_centerline_bias_m: float, yaw_rad: float,
    contact_samples_since_seek_start: Callable[[], list[M1BContactSampleV1]],
) -> dict[str, object]:
    """Keep the measured continuous descent, then seek only below its endpoint."""

    baseline = m1b_top_down_contact_descend(
        client, centre_world_m,
        hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_rad,
    )
    if not baseline.get("executed"):
        return baseline
    seek = m1b_top_down_contact_seek_descent(
        client, centre_world_m,
        hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_rad,
        contact_samples_since_seek_start=contact_samples_since_seek_start,
    )
    seek["baseline_descend"] = baseline
    return seek


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


def apply_m1b_cylinder_scene(
    client: CalibrationClient, cylinders: list[tuple[str, list[float]]],
) -> bool:
    """Replace M1B cylinder collision proxies with one explicit input scene."""
    # Scene admission may assess several generated scenes in one MoveIt
    # session.  A diff only updates names it contains, so without this
    # separate removal a shorter later scene inherits collision objects from
    # the preceding seed and its corridor result is not an independent audit.
    # Generated industrial scenes contain at most twelve named cylinders.
    expected_ids = {f"cylinder_{index:02d}" for index in range(1, 13)}
    request = GetPlanningScene.Request()
    request.components = PlanningSceneComponents(components=PlanningSceneComponents.WORLD_OBJECT_NAMES)
    future = client.scene_get_client.call_async(request)
    rclpy.spin_until_future_complete(client, future, timeout_sec=10.0)
    result = future.result()
    existing_ids = {
        item.id for item in (result.scene.world.collision_objects if result is not None else [])
        if item.id in expected_ids or item.id.startswith("m1b_public_")
    }
    removal = PlanningScene(is_diff=True)
    for object_id in sorted(existing_ids):
        item = CollisionObject()
        item.id = object_id
        item.header.frame_id = "world"
        item.operation = CollisionObject.REMOVE
        removal.world.collision_objects.append(item)
    if existing_ids and not client.apply_scene_diff(removal):
        return False

    scene = PlanningScene(is_diff=True)
    for object_id, center_world_m in cylinders:
        item = CollisionObject()
        item.id = object_id
        item.header.frame_id = "world"
        item.primitives = [SolidPrimitive(type=SolidPrimitive.CYLINDER, dimensions=[0.08, 0.015])]
        pose = Pose()
        pose.position.x, pose.position.y, pose.position.z = (float(value) for value in center_world_m)
        pose.orientation.w = 1.0
        item.primitive_poses = [pose]
        item.operation = CollisionObject.ADD
        scene.world.collision_objects.append(item)
    return client.apply_scene_diff(scene)


def apply_calibration_cylinder_scene(client: CalibrationClient, labels: list[dict[str, object]]) -> bool:
    """Add every supervised cylinder as a calibration-only collision proxy."""
    return apply_m1b_cylinder_scene(
        client,
        [
            (str(label["actual_sim_entity_id"]), [float(value) for value in label["position_3d_world"]])
            for label in labels
        ],
    )


def apply_public_cylinder_scene(
    client: CalibrationClient, tracks: dict[str, dict[str, object]],
) -> bool:
    """Build the production collision scene from public RGB-D tracks only."""
    if not tracks:
        return False
    return apply_m1b_cylinder_scene(
        client,
        [
            (public_collision_id(track_id), [float(value) for value in track["estimated_center_world_m"]])
            for track_id, track in tracks.items()
        ],
    )


def m1b_calibration_scene_labels_at_lift(
    labels: list[dict[str, object]], *, lift_m: float,
) -> list[dict[str, object]]:
    """Translate the complete calibration fixture for one height candidate."""
    virtual_labels: list[dict[str, object]] = []
    for label in labels:
        copy = dict(label)
        position = list(copy["position_3d_world"])
        position[2] = float(position[2]) + lift_m
        copy["position_3d_world"] = position
        virtual_labels.append(copy)
    return virtual_labels


def m1b_calibration_target_height_scan(
    client: CalibrationClient, labels: list[dict[str, object]], *, target_entity: str,
    target_world_m: list[float], hand_y_centerline_bias_m: float, yaw_rad: float,
) -> dict[str, object]:
    """No-motion scan of virtual whole-fixture raised planning scenes."""
    candidates: list[dict[str, object]] = []
    for lift_m in M1B_CALIBRATION_TARGET_HEIGHT_LIFTS_M:
        # A physical pedestal lifts every cylinder.  Scanning only the target
        # would leave its neighbours at stale lower collision heights and can
        # manufacture an IK/planning result that the physical fixture cannot
        # reproduce.  Translate the entire supervised fixture identically.
        virtual_labels = m1b_calibration_scene_labels_at_lift(labels, lift_m=lift_m)
        scene_applied = apply_calibration_cylinder_scene(client, virtual_labels)
        exception_applied = client.set_target_touch_exception(True, target_id=target_entity) if scene_applied else False
        virtual_target = [target_world_m[0], target_world_m[1], target_world_m[2] + lift_m]
        pre_pose = _m1b_top_pose(
            virtual_target,
            hand_z_offset_m=M1B_TOP_CONTACT_CENTERLINE_Z_M + M1B_TOP_PRECONTACT_STANDOFF_M,
            hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_rad,
        )
        pre_ik = client.ik(pre_pose)
        pre_plan = client.plan(pre_ik) if pre_ik is not None else None
        contact_pose = _m1b_top_pose(
            virtual_target, hand_z_offset_m=M1B_TOP_CONTACT_CENTERLINE_Z_M,
            hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_rad,
        )
        contact_ik = client.ik(contact_pose, seed=pre_ik)
        contact_plan = client.plan(contact_ik) if contact_ik is not None else None
        restored = client.set_target_touch_exception(False, target_id=target_entity) if exception_applied else False
        candidates.append({
            "lift_m": lift_m, "virtual_target_center_world_m": virtual_target,
            "top_down_yaw_rad": yaw_rad,
            "scene_applied": scene_applied, "target_touch_exception_applied": exception_applied,
            "precontact_ik_solved": pre_ik is not None, "precontact_planned_from_reset_home": pre_plan is not None,
            "contact_ik_solved": contact_ik is not None, "contact_planned_from_reset_home": contact_plan is not None,
            "target_touch_exception_restored": restored,
        })
    restored_scene = apply_calibration_cylinder_scene(client, labels)
    return {"executed_physical_motion": False, "candidate_count": len(candidates), "candidates": candidates, "original_scene_restored": restored_scene}


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
    parser.add_argument("--trial", type=Path, help="One immutable calibration worklist record")
    parser.add_argument("--supervision", type=Path, help="Evaluator-only labels; calibration mode only")
    parser.add_argument("--object-slot", type=int, help="1-based normal-object slot, calibration mode only")
    aperture_source = parser.add_mutually_exclusive_group(required=True)
    aperture_source.add_argument("--calibration-fixture-diameter-m", type=float, help="Declared physical cylinder diameter for the perception-free tolerance experiment")
    aperture_source.add_argument("--public-perception-evidence", type=Path, help="Actual public RGB-D geometric output for a production-style run")
    parser.add_argument("--public-camera-info", type=Path, help="Camera intrinsics paired with public perception evidence")
    parser.add_argument("--public-track-id", help="Production-side public target track ID")
    parser.add_argument("--public-free-gap-yaw-rad", type=float, help="Deprecated: production derives yaw from the public RGB-D scene")
    parser.add_argument("--public-xy-correction", type=Path, default=ROOT / "configs" / "m1b_public_geometry_xy_correction.json", help="Frozen train-only public RGB-D X/Y correction")
    parser.add_argument("--public-table-supported-z", type=Path, default=ROOT / "configs" / "m1b_table_supported_cylinder_center.json", help="Versioned public RGB-D support-plane Z estimator")
    parser.add_argument("--public-pipeline-python", default=os.environ.get("M1B_PUBLIC_PIPELINE_PYTHON", sys.executable), help="Python with the declared public RGB-D dependencies")
    parser.add_argument("--enable-near-pregrasp-reobservation", action="store_true", help="Enable the production NO-GO remediation; excluded from the baseline tolerance envelope")
    parser.add_argument("--enable-contact-seeking-terminal-descent", action="store_true", help="Use the ADR-0013 Amendment 2 physical bilateral-contact terminal descent")
    parser.add_argument("--calibration-hand-y-bias-m", type=float, help="Calibration-only centreline sweep; absent uses the production fixed hand-chain correction")
    parser.add_argument("--calibration-keep-target-collision-through-descend", action="store_true", help="Calibration-only contact-free final-descent probe")
    parser.add_argument("--calibration-lateral-insertion", action="store_true", help="Calibration-only collision-preserving open-hand lateral insertion probe")
    parser.add_argument("--calibration-lateral-insertion-hand-z-offset-m", type=float, help="Calibration-only single lateral-insertion height")
    parser.add_argument("--calibration-lateral-insert-target-touch-exception", action="store_true", help="Calibration-only: authorize target contact only for final lateral insert")
    parser.add_argument("--calibration-vertical-board-ik-probe", action="store_true", help="Calibration-only: plan vertical-board poses without physical motion")
    parser.add_argument("--calibration-target-height-scan", action="store_true", help="Calibration-only: scan virtual target elevations without physical motion")
    parser.add_argument("--calibration-top-contact-height-m", type=float, help="Calibration-only physical top-contact hand offset; does not change the production default")
    parser.add_argument("--calibration-close-squeeze-m", type=float, help="Calibration-only close-squeeze probe below the perceived diameter; does not change the production default")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    calibration_mode = args.calibration_fixture_diameter_m is not None
    if calibration_mode:
        if args.trial is None or args.supervision is None or args.object_slot is None:
            raise SystemExit("calibration mode requires --trial, --supervision, and --object-slot")
    else:
        if args.trial is not None or args.supervision is not None or args.object_slot is not None:
            raise SystemExit("public production mode forbids --trial, --supervision, and --object-slot")
        if args.public_perception_evidence is None or args.public_camera_info is None or not args.public_track_id:
            raise SystemExit("public production mode requires perception evidence, camera info, and target track")
        if args.public_free_gap_yaw_rad is not None:
            raise SystemExit("public production derives free-gap yaw from RGB-D tracks; do not supply --public-free-gap-yaw-rad")
        if not args.enable_near_pregrasp_reobservation:
            raise SystemExit("public production requires --enable-near-pregrasp-reobservation")
    global M1B_TOP_CONTACT_CENTERLINE_Z_M
    if args.calibration_top_contact_height_m is not None:
        if args.calibration_fixture_diameter_m is None or not 0.10 <= args.calibration_top_contact_height_m <= 0.14:
            raise SystemExit("--calibration-top-contact-height-m requires calibration mode and must be in [0.10, 0.14] m")
        M1B_TOP_CONTACT_CENTERLINE_Z_M = args.calibration_top_contact_height_m
    trial: dict[str, object] | None = None
    if calibration_mode:
        assert args.trial is not None
        trial = json.loads(args.trial.read_text(encoding="utf-8"))
        if trial.get("provenance") != "CALIBRATION_ONLY_INITIALIZATION":
            raise SystemExit("trial is not calibration-only")
    if args.calibration_hand_y_bias_m is not None and not calibration_mode:
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
    if args.calibration_target_height_scan and args.calibration_fixture_diameter_m is None:
        raise SystemExit("--calibration-target-height-scan is calibration-only")
    if args.calibration_close_squeeze_m is not None:
        if args.calibration_fixture_diameter_m is None or not 0.0 <= args.calibration_close_squeeze_m <= 0.004:
            raise SystemExit("--calibration-close-squeeze-m requires calibration mode and must be in [0.0, 0.004] m")
    hand_y_centerline_bias_m = M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M if args.calibration_hand_y_bias_m is None else args.calibration_hand_y_bias_m
    labels: list[dict[str, object]] = []
    target_entity: str | None = None
    planning_target_id: str | None = None
    truth_center: list[float] | None = None
    public_tracks: dict[str, dict[str, object]] = {}
    public_scene_evidence: dict[str, object] | None = None
    axis: str | None = None
    if calibration_mode:
        assert args.supervision is not None and args.object_slot is not None and trial is not None
        axis = str(trial["axis"])
        if axis not in {"x", "y", "z"}:
            raise SystemExit("trial axis must be x, y, or z")
        labels = json.loads(args.supervision.read_text(encoding="utf-8"))["simulator_supervision"]["objects"]
        normal = [label for label in labels if label["orientation_state"] == "normal"]
        if not 1 <= args.object_slot <= len(normal):
            raise SystemExit(f"object slot must be in [1, {len(normal)}]")
        target_label = normal[args.object_slot - 1]
        target_entity = str(target_label["actual_sim_entity_id"])
        planning_target_id = target_entity
        # Spawn labels are not assumed to remain physical truth after gravity
        # and the mandatory settling window. This is evaluator-only
        # calibration initialization, explicitly outside online policy input.
        time.sleep(CALIBRATION_SETTLE_S)
        truth_center = calibration_live_model_center(target_entity)
        target = list(truth_center)
        target["xyz".index(axis)] += float(trial["offset_m"])
    else:
        target = []
    calibration: M1BStaticCameraCalibrationV1 | None = None
    xy_correction: M1BPublicGeometryXYCorrectionV1 | None = None
    table_supported_z: M1BTableSupportedCylinderCenterV1 | None = None
    camera_to_world_tf: dict[str, object] | None = None
    initial_public_track: dict[str, object] | None = None
    free_gap_yaw: dict[str, object] | None = None
    if args.calibration_fixture_diameter_m is not None:
        perceived_diameter_m = args.calibration_fixture_diameter_m
        public_evidence: dict[str, object] = {"source": "CALIBRATION_FIXTURE_DECLARED_GEOMETRY", "perceived_diameter_m": perceived_diameter_m}
        free_gap_yaw = m1b_calibration_free_gap_yaw(labels, target_entity)
        if not free_gap_yaw["clearance_ok"]:
            raise SystemExit(
                f"CALIBRATION_FREE_GAP_YAW_CLEARANCE_REJECTED:{free_gap_yaw['min_clearance_m']:.4f}"
            )
        top_grasp_yaw_rad = float(free_gap_yaw["selected_yaw_rad"])
        top_grasp_yaw_source = "CALIBRATION_LABEL_FREE_GAP_GEOMETRY"
    else:
        assert args.public_perception_evidence is not None and args.public_camera_info is not None and args.public_track_id
        calibration = M1BStaticCameraCalibrationV1.from_file(ROOT / "configs" / "m1b_camera_calibration.json")
        camera_to_world_tf = calibration.episode_tf_evidence()
        xy_correction = M1BPublicGeometryXYCorrectionV1.from_file(args.public_xy_correction)
        table_supported_z = M1BTableSupportedCylinderCenterV1.from_file(args.public_table_supported_z)
        public_tracks, public_scene_evidence = public_tracks_from_evidence(
            args.public_perception_evidence, args.public_camera_info,
            calibration, xy_correction, table_supported_z,
        )
        initial_public_track = public_tracks.get(args.public_track_id)
        if initial_public_track is None:
            raise SystemExit("PUBLIC_TARGET_TRACK_NOT_ADMITTED_TO_PLANNING_SCENE")
        _, public_evidence = public_track_from_evidence(
            args.public_perception_evidence, args.public_camera_info, args.public_track_id,
            calibration, xy_correction, table_supported_z,
        )
        perceived_diameter_m = float(initial_public_track["perceived_diameter_m"])
        target = [float(value) for value in initial_public_track["estimated_center_world_m"]]
        planning_target_id = public_collision_id(args.public_track_id)
        free_gap_yaw = m1b_public_free_gap_yaw(public_tracks, args.public_track_id)
        if not free_gap_yaw["clearance_ok"]:
            raise SystemExit(f"PUBLIC_FREE_GAP_YAW_CLEARANCE_REJECTED:{free_gap_yaw['min_clearance_m']:.4f}")
        top_grasp_yaw_rad = float(free_gap_yaw["selected_yaw_rad"])
        top_grasp_yaw_source = "PUBLIC_RGBD_FREE_GAP_GEOMETRY"
    calibration_motion: dict[str, object] | None = (
        {"initial_center_world_m": truth_center} if calibration_mode else None
    )
    if args.enable_near_pregrasp_reobservation and initial_public_track is None:
        raise SystemExit("near-pregrasp reobservation requires public perception evidence")
    close_targets, aperture = m1b_close_finger_targets_from_perceived_diameter(
        perceived_diameter_m, squeeze_m=args.calibration_close_squeeze_m,
    )
    rclpy.init()
    client = CalibrationClient()
    raw: list[M1BContactSampleV1] = []
    cylinder_contact_samples = 0
    contact_channel_diag: dict[str, dict[str, int]] = {}
    contact_subscriptions: dict[str, object] = {}
    def on_contact(message: Contacts, finger: str) -> None:
        timestamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        pairs = tuple((contact.collision1.name, contact.collision2.name) for contact in message.contacts)
        raw.append(M1BContactSampleV1(timestamp, finger, pairs))
        contact_channel_diag[finger]["messages"] = contact_channel_diag[finger].get("messages", 0) + 1
    for finger, topic in RAW_CONTACT_TOPICS.items():
        contact_channel_diag[finger] = {"messages": 0}
        contact_subscriptions[finger] = client.create_subscription(
            Contacts, topic, lambda message, finger=finger: on_contact(message, finger), 1000
        )
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
        target_height_scan: dict[str, object] | None = None
        near_reobservation: dict[str, object] = {"attempted": False, "succeeded": False}
        contact_start_index = len(raw)
        if ready:
            cylinder_scene_applied = (
                apply_calibration_cylinder_scene(client, labels)
                if calibration_mode else apply_public_cylinder_scene(client, public_tracks)
            )
            # Keep the target collision-checked through the entire transit to
            # high precontact.  Enabling finger/target contact early lets a
            # planner legally side-swipe the free cylinder before close,
            # which both moves the calibration target and makes stale approach
            # contacts look tempting.  Only the deliberately contact-bearing
            # descent receives this narrow exception.
            target_touch_exception_applied = False
            if args.calibration_target_height_scan and cylinder_scene_applied:
                target_height_scan = m1b_calibration_target_height_scan(
                    client, labels, target_entity=target_entity, target_world_m=target,
                    hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=top_grasp_yaw_rad,
                )
                approach = {"executed": False, "reason": "CALIBRATION_TARGET_HEIGHT_SCAN_NO_PHYSICAL_MOTION"}
            elif args.calibration_vertical_board_ik_probe and cylinder_scene_applied:
                vertical_board_ik_probe = m1b_calibration_vertical_board_ik_probe(
                    client, target, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                )
                approach = {"executed": False, "reason": "CALIBRATION_VERTICAL_BOARD_IK_PROBE_NO_PHYSICAL_MOTION"}
            else:
                open_hand = client.command_hand([0.04, 0.04])
                approach = m1b_top_down_precontact(
                    client, target, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                    yaw_rad=top_grasp_yaw_rad,
                ) if cylinder_scene_applied else {"executed": False, "reason": "CALIBRATION_COLLISION_SCENE_UNAVAILABLE"}
            # A controller action can report success while the physical arm
            # was deflected by an unmodelled/free-cylinder contact.  Do not
            # close or enter the contact-bearing descent from that state:
            # production motion acceptance requires both execution and the
            # bounded terminal convergence evidence.
            approach_motion_accepted = bool(approach.get("executed") and approach.get("converged"))
            if calibration_motion is not None:
                assert target_entity is not None and truth_center is not None
                after_pregrasp = calibration_live_model_center(target_entity)
                calibration_motion["after_pregrasp_center_world_m"] = after_pregrasp
                calibration_motion["pregrasp_displacement_world_xyz_m"] = calibration_displacement_m(truth_center, after_pregrasp)
            if approach_motion_accepted and open_hand.get("succeeded") and not args.calibration_keep_target_collision_through_descend:
                assert planning_target_id is not None
                target_touch_exception_applied = client.set_target_touch_exception(True, target_id=planning_target_id)
            final_target = list(target)
            if target_touch_exception_applied and args.enable_near_pregrasp_reobservation:
                assert initial_public_track is not None and calibration is not None and xy_correction is not None and table_supported_z is not None
                near_reobservation["attempted"] = True
                near_directory = args.output.parent / f"{args.output.stem}.near_rgbd"
                try:
                    near_frames = []
                    for index in range(1, M1B_NEAR_REOBSERVATION_FRAME_COUNT + 1):
                        frame_directory = near_directory / f"frame-{index:02d}"
                        near_evidence_path = capture_near_public_observation(frame_directory, public_pipeline_python=args.public_pipeline_python)
                        near_track, near_metadata = select_near_public_track(
                            near_evidence_path, frame_directory / "camera_info.json", initial=initial_public_track,
                            calibration=calibration, xy_correction=xy_correction, table_supported_z=table_supported_z,
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
                    close_targets, aperture = m1b_close_finger_targets_from_perceived_diameter(
                        float(near_track["perceived_diameter_m"]), squeeze_m=args.calibration_close_squeeze_m,
                    )
                    public_delta = [float(current) - float(previous) for current, previous in zip(near_track["estimated_center_world_m"], initial_public_track["estimated_center_world_m"])]
                    final_target = [coordinate + delta for coordinate, delta in zip(target, public_delta)]
                    near_reobservation = {"attempted": True, "succeeded": True, "aggregation": "PER_AXIS_MEDIAN_OF_PUBLIC_RGBD_FRAMES", "frames": near_frames, "selected_public_track": near_track, "public_center_delta_world_m": public_delta, "final_target_world_m": final_target}
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    near_reobservation = {"attempted": True, "succeeded": False, "reason": str(error)}
            if (target_touch_exception_applied or args.calibration_keep_target_collision_through_descend or args.calibration_lateral_insert_target_touch_exception) and not args.enable_near_pregrasp_reobservation:
                near_reobservation = {"attempted": False, "succeeded": True, "mode": "BASELINE_PERCEPTION_FREE_TOLERANCE"}
            seek_contact_start_index = len(raw)
            if args.calibration_lateral_insertion and near_reobservation.get("succeeded"):
                def authorize_lateral_target_contact() -> bool:
                    return client.set_target_touch_exception(True, target_id=target_entity)
                contact_descend = m1b_calibration_lateral_insertion(
                    client, final_target, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                    candidate_hand_z_offsets_m=(args.calibration_lateral_insertion_hand_z_offset_m,) if args.calibration_lateral_insertion_hand_z_offset_m is not None else M1B_CALIBRATION_LATERAL_INSERTION_HAND_Z_OFFSETS_M,
                    authorize_lateral_target_contact=authorize_lateral_target_contact if args.calibration_lateral_insert_target_touch_exception else None,
                )
            else:
                if not near_reobservation.get("succeeded"):
                    contact_descend = {"executed": False, "reason": "PUBLIC_NEAR_REOBSERVATION_GATE_REJECTED"}
                elif args.enable_contact_seeking_terminal_descent:
                    contact_descend = m1b_top_down_contact_descend_with_seek(
                        client, final_target,
                        hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                        yaw_rad=top_grasp_yaw_rad,
                        contact_samples_since_seek_start=lambda: raw[seek_contact_start_index:],
                    )
                else:
                    contact_descend = m1b_top_down_contact_descend(
                        client, final_target,
                        hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=top_grasp_yaw_rad,
                    )
            # The jaw is symmetric under a pi yaw flip, but the wrist is not:
            # the measured slot-1 descent ends on an IK branch boundary
            # (CARTESIAN_JOINT_JUMP_REJECTED, 0.45 rad in one 5 mm step) at
            # yaw 90 deg while the identical grasp at yaw+pi uses a different
            # wrist branch.  Retry the physically identical flip first, then
            # the next-ranked clear yaw, before recording a descend failure.
            yaw_retry_attempts: list[dict[str, object]] = []
            if (
                args.calibration_fixture_diameter_m is not None and free_gap_yaw is not None
                and not contact_descend.get("executed")
                and "CARTESIAN" in str(contact_descend.get("reason", ""))
            ):
                ranked = sorted(
                    [c for c in free_gap_yaw["candidates"] if c["min_clearance_m"] >= M1B_FREE_GAP_MIN_CLEARANCE_M],
                    key=lambda c: -float(c["min_clearance_m"]),
                )
                alternates: list[float] = []
                for candidate in ranked[:2]:
                    for flip in (math.pi, 0.0):
                        yaw_value = (float(candidate["yaw_rad"]) + flip) % (2.0 * math.pi)
                        if abs(yaw_value - top_grasp_yaw_rad) > 1e-9 and yaw_value not in alternates:
                            alternates.append(yaw_value)
                for yaw_value in alternates[:3]:
                    home_return = client.move_joint_target(M1B_RESET_HOME_JOINTS_RAD)
                    entry: dict[str, object] = {"yaw_rad": yaw_value, "home_return": {
                        "executed": home_return.get("executed"), "converged": home_return.get("converged"),
                    }}
                    if not (home_return.get("executed") and home_return.get("converged")):
                        yaw_retry_attempts.append(entry)
                        continue
                    retry_approach = m1b_top_down_precontact(
                        client, target, hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                        yaw_rad=yaw_value,
                    )
                    entry["approach"] = retry_approach
                    if retry_approach.get("executed") and retry_approach.get("converged"):
                        seek_contact_start_index = len(raw)
                        retry_descend = (
                            m1b_top_down_contact_descend_with_seek(
                                client, final_target,
                                hand_y_centerline_bias_m=hand_y_centerline_bias_m,
                                yaw_rad=yaw_value,
                                contact_samples_since_seek_start=lambda: raw[seek_contact_start_index:],
                            ) if args.enable_contact_seeking_terminal_descent else
                            m1b_top_down_contact_descend(
                                client, final_target,
                                hand_y_centerline_bias_m=hand_y_centerline_bias_m, yaw_rad=yaw_value,
                            )
                        )
                        entry["contact_descend"] = retry_descend
                        if retry_descend.get("executed"):
                            approach = retry_approach
                            contact_descend = retry_descend
                            top_grasp_yaw_rad = yaw_value
                            top_grasp_yaw_source = "CALIBRATION_LABEL_FREE_GAP_GEOMETRY_YAW_RETRY"
                            yaw_retry_attempts.append(entry)
                            break
                    yaw_retry_attempts.append(entry)
            if args.calibration_lateral_insert_target_touch_exception:
                # This exception is narrowly scoped to the final insert.  A
                # failed candidate must leave the planning scene restored
                # before it is recorded or any later motion is considered.
                assert target_entity is not None
                lateral_target_touch_exception_restored = client.set_target_touch_exception(False, target_id=target_entity)
            if calibration_motion is not None and contact_descend.get("executed"):
                assert target_entity is not None and truth_center is not None
                after_descend = calibration_live_model_center(target_entity)
                calibration_motion["after_descend_center_world_m"] = after_descend
                calibration_motion["descend_displacement_world_xyz_m"] = calibration_displacement_m(truth_center, after_descend)
            # Descend while open so the cylinder enters between both pads;
            # only then close to the public perception-derived jaw width.
            # The evidence window begins immediately before that close,
            # excluding all approach contact telemetry from authorization.
            contact_start_index = len(raw)
            for finger, subscription in contact_subscriptions.items():
                contact_channel_diag[finger]["matched_publishers_before_close"] = subscription.get_publisher_count()
            # Once both boards enter the free-cylinder contact zone, load can
            # move an otherwise successful controller endpoint by more than
            # the no-contact joint-settle diagnostic.  The production gate is
            # the controller terminal success here; only the non-contact
            # approach requires strict terminal convergence.
            if contact_descend.get("executed"):
                # Two-stage close.  Single-stage closes measured a per-pair
                # force-response lottery in bullet-featherstone: a pad could
                # stream 30 Hz contact events while exerting no force
                # (fingers reach a 4.5 mm-overlap command unresisted), and
                # which side engaged varied per instance.  Both live
                # diagnostics that first paused just clear of the surface and
                # then pressed measured full bilateral force engagement (2/2),
                # matching the S0 bilateral precontact-close precedent, so
                # the production primitive establishes the contact pairs at a
                # 2 mm-clear pre-close before the squeezing command.
                # "2 mm clear" is measured at the modelled collision skin
                # (6.5 mm proud faces): public pre-close gap = d + 0.011
                # places each skin face 2 mm outside the perceived surface.
                preclose_targets, _ = m1b_close_finger_targets_from_perceived_diameter(
                    perceived_diameter_m + 0.011, squeeze_m=0.0,
                )
                preclose = client.command_hand(
                    preclose_targets, duration_s=M1B_NORMAL_CLOSE_DURATION_S,
                    goal_tolerance_m=0.002,
                )
                settle_deadline = time.monotonic() + 0.4
                while time.monotonic() < settle_deadline:
                    rclpy.spin_once(client, timeout_sec=0.02)
                # A squeezed close is DESIGNED to stall against the target
                # above its command: the fingers stop where the engine's
                # contact response balances, measured at up to ~1 mm modelled
                # overlap.  Accept any stall between the command and the
                # perceived-diameter surface plus that engine margin; the
                # mimic-symmetry contract stays at the same tolerance.
                per_finger_target_m = float(aperture["per_finger_target_m"])
                close_goal_tolerance_m = 0.001 + max(
                    0.0,
                    (float(aperture["perceived_diameter_m"]) + M1B_FINGER_BOARD_THICKNESS_M) / 2.0
                    + 0.003 - per_finger_target_m,
                )
                close = client.command_hand(
                    close_targets, duration_s=1.2,
                    goal_tolerance_m=close_goal_tolerance_m,
                )
                close["preclose"] = {
                    "succeeded": preclose.get("succeeded"),
                    "targets_m": preclose_targets,
                    "observed_positions_m": preclose.get("observed_positions_m"),
                }
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
            and (not args.enable_contact_seeking_terminal_descent or contact_descend.get("seek_contact_found"))
        )
        attach = {"sent": False, "state_confirmed": False, "reason": "BILATERAL_GATE_REJECTED"}
        if feedback.grasp_success and not motion_gate_passed:
            attach["reason"] = "MOTION_OR_HAND_GATE_REJECTED"
        if feedback.grasp_success and motion_gate_passed and internal["attach_topic"] and internal["actual_sim_entity_id"]:
            entity = str(internal["actual_sim_entity_id"])
            attach = attach_and_observe(str(internal["attach_topic"]), f"/xh/m1b/{entity}/grasp_state")
        payload = {
            "schema_version": "M1BToleranceTrialEvidenceV1",
            "provenance": "CALIBRATION_ONLY_INITIALIZATION" if calibration_mode else "PUBLIC_PERCEPTION_PRODUCTION",
            "trial": trial,
            "supervision_initialization": (
                {"orientation_state": "normal", "object_slot": args.object_slot, "actual_sim_entity_id": target_entity,
                 "settle_s": CALIBRATION_SETTLE_S,
                 "truth_center_source": "EVALUATOR_ONLY_GAZEBO_MODEL_POSE_AFTER_SETTLE",
                 "truth_center_used_only_for_initial_target_pose": truth_center}
                if calibration_mode else None
            ),
            "public_aperture_input": {**public_evidence, **aperture},
            "camera_to_world_tf": camera_to_world_tf,
            "public_collision_scene": public_scene_evidence if not calibration_mode else None,
            "public_planning_target": (
                {"track_id": args.public_track_id, "collision_id": planning_target_id,
                 "estimated_center_world_m": target}
                if not calibration_mode else None
            ),
            "near_pregrasp_public_reobservation": near_reobservation,
            "baseline_perception_free": calibration_mode and not args.enable_near_pregrasp_reobservation,
            "offset_vector_m": (
                [target[index] - truth_center[index] for index in range(3)] if truth_center is not None else None
            ),
            "production_grasp_primitive": (
                "open_physical_hand + m1b_top_down_precontact + m1b_top_down_contact_seek_descent "
                "+ close_physical_hand + m1b_internal_bilateral_broker"
                if args.enable_contact_seeking_terminal_descent else
                "open_physical_hand + m1b_top_down_precontact + m1b_top_down_contact_descend "
                "+ close_physical_hand + m1b_internal_bilateral_broker"
            ),
            "top_grasp_yaw": {"yaw_rad": top_grasp_yaw_rad, "source": top_grasp_yaw_source},
            "calibration_free_gap_yaw": free_gap_yaw if calibration_mode else None,
            "public_free_gap_yaw": free_gap_yaw if not calibration_mode else None,
            "calibration_yaw_retry_attempts": yaw_retry_attempts if ready else [],
            "calibration_top_contact_height_m": args.calibration_top_contact_height_m,
            "calibration_close_squeeze_m": args.calibration_close_squeeze_m,
            "contact_seeking_terminal_descent_enabled": args.enable_contact_seeking_terminal_descent,
            "ready": ready,
            "cylinder_collision_scene_applied": cylinder_scene_applied if ready else False,
            "collision_scene_source": "CALIBRATION_SUPERVISION" if calibration_mode else "PUBLIC_RGBD_TRACKS",
            "target_touch_exception_applied": target_touch_exception_applied if ready else False,
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
                "contact_seek_preclose_bilateral_window_required": args.enable_contact_seeking_terminal_descent,
            },
            "hand_close_duration_s": M1B_NORMAL_CLOSE_DURATION_S,
            "calibration_hand_y_centerline_bias_m": hand_y_centerline_bias_m,
            "calibration_keep_target_collision_through_descend": args.calibration_keep_target_collision_through_descend,
            "calibration_lateral_insertion": args.calibration_lateral_insertion,
            "calibration_lateral_insertion_hand_z_offset_m": args.calibration_lateral_insertion_hand_z_offset_m,
            "calibration_lateral_insert_target_touch_exception": args.calibration_lateral_insert_target_touch_exception,
            "calibration_lateral_target_touch_exception_restored": lateral_target_touch_exception_restored,
            "calibration_vertical_board_ik_probe": vertical_board_ik_probe,
            "calibration_target_height_scan": target_height_scan,
            "calibration_motion_diagnostic": calibration_motion,
            "open_hand": open_hand, "approach": approach, "close": close, "contact_descend": contact_descend,
            "hand_feedback_ready": hand_feedback_ready,
            "raw_contact_samples": [{"timestamp_s": item.timestamp_s, "finger": item.finger, "collision_pairs": list(item.collision_pairs)} for item in raw],
            "post_close_contact_samples": [{"timestamp_s": item.timestamp_s, "finger": item.finger, "collision_pairs": list(item.collision_pairs)} for item in post_close_raw],
            "cylinder_side_contact_samples": cylinder_contact_samples,
            "contact_channel_diagnostic": contact_channel_diag,
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
