#!/usr/bin/env python3
"""Select a grasp target and top-grasp yaw from public geometric RGB-D only."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1
from xh_agent.runtime.m1b_center_correction import (
    M1BPublicGeometryXYCorrectionV1,
    M1BTableSupportedCylinderCenterV1,
)


FINGER_SWEEP_BOUND_RADIUS_M = 0.0148
FINGER_SWEEP_CENTER_OFFSET_M = 0.0039
OPEN_FINGER_M = 0.04
NEIGHBOR_RADIUS_M = 0.015
MIN_CLEARANCE_M = 0.005
YAW_CANDIDATES_RAD = tuple(math.radians(value) for value in range(0, 180, 15))
INDUSTRIAL_DIAMETER_RANGE_M = (0.020, 0.040)


def public_tracks(
    evidence_path: Path, camera_info_path: Path, calibration: M1BStaticCameraCalibrationV1,
    xy_correction: M1BPublicGeometryXYCorrectionV1,
    table_supported_z: M1BTableSupportedCylinderCenterV1,
) -> tuple[dict[str, dict[str, object]], list[dict[str, str]]]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    camera = json.loads(camera_info_path.read_text(encoding="utf-8"))
    intrinsics = camera.get("k", [])
    focal = min(float(intrinsics[0]), float(intrinsics[4])) if len(intrinsics) >= 5 else 0.0
    tracks: dict[str, dict[str, object]] = {}
    rejected: list[dict[str, str]] = []
    for result in evidence.get("results", []):
        track_id = str(result.get("track_id", ""))
        try:
            bbox = result["bbox_or_mask"]
            depth = float(result["position_3d"][2])
            diameter = min(int(bbox["width"]), int(bbox["height"])) * depth / focal
            surface = tuple(float(value) for value in result["position_3d"])
            support = tuple(float(result["covariance_or_quality"][f"support_plane_optical_{axis}_m"]) for axis in ("x", "y", "z"))
            orientation = str(result["orientation_state"])
            if not track_id or track_id in tracks or focal <= 0.0 or depth <= 0.0 or len(surface) != 3:
                raise ValueError("invalid or duplicate public track geometry")
            if not INDUSTRIAL_DIAMETER_RANGE_M[0] <= diameter <= INDUSTRIAL_DIAMETER_RANGE_M[1]:
                raise ValueError("public perceived diameter is outside the approved industrial-cylinder class band")
            baseline = calibration.visible_surface_to_center_world(surface, diameter)
            xy_center = xy_correction.correct_xy(
                baseline, surface_optical_m=surface, perceived_diameter_m=diameter,
                orientation_state=orientation,
            )
            center = table_supported_z.correct_z(xy_center, calibration.optical_to_world(support))
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            rejected.append({"track_id": track_id or "<missing>", "reason": str(error)})
            continue
        tracks[track_id] = {
            "track_id": track_id,
            "estimated_center_world_m": list(center),
            "perceived_diameter_m": diameter,
            "public_orientation_state": orientation,
        }
    return tracks, rejected


def best_free_gap_yaw(track_id: str, tracks: dict[str, dict[str, object]]) -> dict[str, object]:
    target = tracks[track_id]
    x, y = (float(value) for value in target["estimated_center_world_m"][:2])
    neighbours = [
        tuple(float(value) for value in item["estimated_center_world_m"][:2])
        for candidate_id, item in tracks.items() if candidate_id != track_id
    ]
    candidates = []
    for yaw in YAW_CANDIDATES_RAD:
        closing = (math.sin(yaw), -math.cos(yaw))
        clearance = math.inf
        for sign in (1.0, -1.0):
            centre = (
                x + sign * (OPEN_FINGER_M + FINGER_SWEEP_CENTER_OFFSET_M) * closing[0],
                y + sign * (OPEN_FINGER_M + FINGER_SWEEP_CENTER_OFFSET_M) * closing[1],
            )
            for neighbour in neighbours:
                clearance = min(
                    clearance,
                    math.dist(centre, neighbour) - FINGER_SWEEP_BOUND_RADIUS_M - NEIGHBOR_RADIUS_M,
                )
        candidates.append({"yaw_rad": yaw, "min_clearance_m": clearance})
    best = max(candidates, key=lambda item: float(item["min_clearance_m"]))
    return {"selected_yaw_rad": best["yaw_rad"], "min_clearance_m": best["min_clearance_m"], "clearance_ok": best["min_clearance_m"] >= MIN_CLEARANCE_M}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--camera-info", required=True, type=Path)
    parser.add_argument("--rank", type=int, default=0, help="0 is the clearest public target")
    parser.add_argument("--xy-correction", type=Path, default=Path("configs/m1b_public_geometry_xy_correction.json"))
    parser.add_argument("--table-supported-z", type=Path, default=Path("configs/m1b_table_supported_cylinder_center.json"))
    parser.add_argument("--calibration", type=Path, default=Path("configs/m1b_camera_calibration.json"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.rank < 0:
        raise SystemExit("rank must be non-negative")
    calibration = M1BStaticCameraCalibrationV1.from_file(args.calibration)
    xy_correction = M1BPublicGeometryXYCorrectionV1.from_file(args.xy_correction)
    table_supported_z = M1BTableSupportedCylinderCenterV1.from_file(args.table_supported_z)
    tracks, rejected = public_tracks(args.evidence, args.camera_info, calibration, xy_correction, table_supported_z)
    candidates = []
    for track_id in sorted(tracks):
        gap = best_free_gap_yaw(track_id, tracks)
        if gap["clearance_ok"]:
            candidates.append({**tracks[track_id], "free_gap": gap})
    candidates.sort(key=lambda item: (-float(item["free_gap"]["min_clearance_m"]), str(item["track_id"])))
    if args.rank >= len(candidates):
        raise SystemExit(f"PUBLIC_TARGET_RANK_UNAVAILABLE:{args.rank}:admitted={len(candidates)}")
    payload = {
        "schema_version": "M1BPublicGraspTargetSelectionV1",
        "provenance": "PUBLIC_PERCEPTION_ONLY",
        "online_truth_access": False,
        "evidence_sha256": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
        "camera_to_world_tf": calibration.episode_tf_evidence(),
        "xy_correction_fingerprint": xy_correction.fingerprint,
        "table_supported_z_fingerprint": table_supported_z.fingerprint,
        "requested_rank": args.rank,
        "selected": candidates[args.rank],
        "ranked_candidates": candidates,
        "rejected_public_tracks": rejected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected_track_id": payload["selected"]["track_id"], "rank": args.rank, "admitted": len(candidates)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
