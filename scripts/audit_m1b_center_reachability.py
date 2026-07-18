#!/usr/bin/env python3
"""Audit public RGB-D centre estimates against held-out supervision offline.

This script is deliberately an evaluator, not a runtime component.  It first
runs the public geometric RGB-D pipeline and the checked-in static TF plus
perceived-radius correction.  Only then does it load supervision to associate
predictions and calculate errors.  Its output is the concrete input evidence
for the S0-style M1B reachability gate.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

from evaluate_captured_geometric import associate, infer
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1


def percentile90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil(0.9 * len(ordered)) - 1
    return ordered[index]


def perceived_diameter_m(prediction: object, intrinsics: list[float]) -> float:
    """Conservative RGB-D diameter estimate from the public mask bounding box."""
    bbox = prediction.bbox_or_mask
    depth = float(prediction.position_3d[2])
    focal = min(float(intrinsics[0]), float(intrinsics[4]))
    pixel_diameter = min(int(bbox.width), int(bbox.height))
    if focal <= 0 or depth <= 0 or pixel_diameter <= 0:
        raise ValueError("invalid public geometry for perceived diameter")
    return pixel_diameter * depth / focal


def category_metrics(matches: list[dict[str, object]]) -> dict[str, object]:
    axes = ("x", "y", "z")
    errors = [[abs(float(record["error_world_xyz_m"][index])) for record in matches] for index in range(3)]
    return {
        "matched_instances": len(matches),
        "median_abs_error_world_xyz_m": {axis: median(values) if values else None for axis, values in zip(axes, errors)},
        "p90_abs_error_world_xyz_m": {axis: percentile90(values) for axis, values in zip(axes, errors)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--calibration", type=Path, default=Path("configs/m1b_camera_calibration.json"))
    parser.add_argument("--split", default="test", choices=("train", "val", "test"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--color-similarity", type=float, default=0.95)
    parser.add_argument("--min-component-pixels", type=int, default=50)
    args = parser.parse_args()

    calibration = M1BStaticCameraCalibrationV1.from_file(args.calibration)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    matches: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    evaluated_scenes = 0
    for sample in manifest["samples"]:
        if sample["split"] != args.split:
            continue
        evaluated_scenes += 1
        predictions = infer(sample, color_similarity=args.color_similarity, min_component_pixels=args.min_component_pixels)
        supervision = json.loads(Path(sample["supervision"]).read_text(encoding="utf-8"))
        labels = supervision["simulator_supervision"]["objects"]
        intrinsics = json.loads(Path(sample["camera_info"]).read_text(encoding="utf-8"))["k"]
        for prediction, label, pixel_distance in associate(predictions, labels, intrinsics):
            try:
                diameter = perceived_diameter_m(prediction, intrinsics)
                estimated = calibration.visible_surface_to_center_world(tuple(float(value) for value in prediction.position_3d), diameter)
            except ValueError as error:
                exclusions.append({
                    "seed": sample["seed"], "track_id": prediction.track_id,
                    "reason": str(error), "orientation_state": label["orientation_state"],
                })
                continue
            truth = tuple(float(value) for value in label["position_3d_world"])
            matches.append({
                "seed": sample["seed"],
                "track_id": prediction.track_id,
                "orientation_state": label["orientation_state"],
                "estimated_center_world_m": list(estimated),
                "perceived_diameter_m": diameter,
                "error_world_xyz_m": [estimate - expected for estimate, expected in zip(estimated, truth)],
                "association_pixel_distance": pixel_distance,
            })
    if not evaluated_scenes:
        raise SystemExit(f"no {args.split} samples in manifest")
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in matches:
        grouped[str(record["orientation_state"])].append(record)
    payload = {
        "schema_version": "M1BPublicCenterAuditV1",
        "status": "ACTUAL_GAZEBO_RGBD_FRAMES_EVALUATED",
        "input": {
            "manifest": str(args.manifest), "split": args.split,
            "calibration_fingerprint": calibration.fingerprint,
            "pipeline": "geometric_rgbd_v1 + perceived_radius + static_tf",
        },
        "metrics_by_orientation": {state: category_metrics(grouped[state]) for state in ("normal", "inverted", "tilted")},
        "all_matches": category_metrics(matches),
        "evaluated_scenes": evaluated_scenes,
        "matches": matches,
        "exclusions": exclusions,
        "truth_boundary": "RGB-D inference, perceived radius, and static TF run before labels; simulator supervision is read only by this offline evaluator.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "scenes": evaluated_scenes, "matches": len(matches), "exclusions": len(exclusions), "metrics_by_orientation": payload["metrics_by_orientation"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
