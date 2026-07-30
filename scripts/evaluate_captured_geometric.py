#!/usr/bin/env python3
"""Offline held-out evaluation of the non-oracle geometric pipeline."""
from __future__ import annotations

import argparse
import json
import math
from statistics import median
from pathlib import Path

from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1, PerceptionResultV1
from run_geometric_rgbd import load_depth, load_rgb


CAMERA_POSE_WORLD = (-0.80, -0.80, 1.40, 0.0, 0.77, 0.93)


def infer(sample: dict[str, object], *, color_similarity: float, min_component_pixels: int) -> list[PerceptionResultV1]:
    recording_path = Path(str(sample["rgb"])).parent / "recording.json"
    snapshot = recording_path.parent
    recording = json.loads(recording_path.read_text(encoding="utf-8"))
    camera = json.loads((snapshot / "camera_info.json").read_text(encoding="utf-8"))
    observation = PerceptionInputV1(frame_id=str(camera["frame_id"]), timestamp_ns=int(recording["depth"]["timestamp_ns"]), rgb_uri=str(sample["rgb"]), depth_uri=str(sample["depth"]), camera_intrinsics=list(camera["k"]), camera_frame=str(camera["frame_id"]))
    return GeometricRGBDBaseline(color_similarity=color_similarity, min_component_pixels=min_component_pixels).infer(observation, load_depth(snapshot, recording), load_rgb(snapshot, recording))


def _rotation(roll: float, pitch: float, yaw: float) -> list[list[float]]:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def world_to_optical(position: list[float], camera_pose: tuple[float, float, float, float, float, float] = CAMERA_POSE_WORLD) -> list[float]:
    """Evaluator-only static camera transform from the checked-in SDF pose."""
    x, y, z, roll, pitch, yaw = camera_pose
    rotation = _rotation(roll, pitch, yaw)
    delta = [position[0] - x, position[1] - y, position[2] - z]
    link = [sum(rotation[column][row] * delta[column] for column in range(3)) for row in range(3)]
    # Gazebo camera link axes (+X forward, -Y right, -Z down) to ROS optical.
    return [-link[1], -link[2], link[0]]


def optical_to_world(position: list[float], camera_pose: tuple[float, float, float, float, float, float] = CAMERA_POSE_WORLD) -> list[float]:
    """Public calibrated coordinate conversion usable by a downstream selector."""
    x, y, z, roll, pitch, yaw = camera_pose
    rotation = _rotation(roll, pitch, yaw)
    link = [position[2], -position[0], -position[1]]
    return [coordinate + sum(rotation[row][column] * link[column] for column in range(3)) for row, coordinate in enumerate((x, y, z))]


def label_pixel(position: list[float], intrinsics: list[float]) -> tuple[float, float]:
    optical = world_to_optical(position)
    return intrinsics[0] * optical[0] / optical[2] + intrinsics[2], intrinsics[4] * optical[1] / optical[2] + intrinsics[5]


def associate(predictions: list[PerceptionResultV1], labels: list[dict[str, object]], intrinsics: list[float], max_pixel_distance: float = 45.0) -> list[tuple[PerceptionResultV1, dict[str, object], float]]:
    """Greedy, evaluator-only association using known camera calibration."""
    candidates: list[tuple[float, int, int]] = []
    for predicted_index, prediction in enumerate(predictions):
        center_x = prediction.bbox_or_mask.x + prediction.bbox_or_mask.width / 2
        center_y = prediction.bbox_or_mask.y + prediction.bbox_or_mask.height / 2
        for label_index, label in enumerate(labels):
            target_x, target_y = label_pixel(list(label["position_3d_world"]), intrinsics)
            candidates.append((math.hypot(center_x - target_x, center_y - target_y), predicted_index, label_index))
    matches: list[tuple[PerceptionResultV1, dict[str, object], float]] = []
    used_predictions: set[int] = set()
    used_labels: set[int] = set()
    for distance, predicted_index, label_index in sorted(candidates):
        if distance > max_pixel_distance or predicted_index in used_predictions or label_index in used_labels:
            continue
        used_predictions.add(predicted_index)
        used_labels.add(label_index)
        matches.append((predictions[predicted_index], labels[label_index], distance))
    return matches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--split", default="test", choices=("train", "val", "test"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--color-similarity", type=float, default=0.95)
    parser.add_argument("--min-component-pixels", type=int, default=50)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = []
    for sample in manifest["samples"]:
        if sample["split"] != args.split:
            continue
        results = infer(sample, color_similarity=args.color_similarity, min_component_pixels=args.min_component_pixels)
        supervision = json.loads(Path(sample["supervision"]).read_text(encoding="utf-8"))
        labels = supervision["simulator_supervision"]["objects"]
        expected_count = len(labels)
        intrinsics = json.loads(Path(sample["camera_info"]).read_text(encoding="utf-8"))["k"]
        matches = associate(results, labels, intrinsics)
        position_errors = [sum((prediction.position_3d[index] - world_to_optical(list(label["position_3d_world"]))[index]) ** 2 for index in range(3)) ** 0.5 for prediction, label, _ in matches]
        orientation_accuracy = sum(prediction.orientation_state == label["orientation_state"] for prediction, label, _ in matches) / len(matches) if matches else 0.0
        target_label = min(labels, key=lambda label: list(label["position_3d_world"])[0])
        target_prediction = min(results, key=lambda prediction: optical_to_world(prediction.position_3d)[0]) if results else None
        target_selected = any(prediction is target_prediction and label is target_label for prediction, label, _ in matches)
        records.append({"seed": sample["seed"], "track_count": len(results), "expected_object_count": expected_count, "valid_output": bool(results), "matched_tracks": len(matches), "position_errors_m": position_errors, "orientation_accuracy": orientation_accuracy, "leftmost_target_selected": target_selected, "orientation_states": [result.orientation_state for result in results]})
    if not records:
        raise SystemExit(f"no {args.split} samples in manifest")
    count_errors = [abs(record["track_count"] - record["expected_object_count"]) for record in records]
    position_errors = [error for record in records for error in record["position_errors_m"]]
    matched_tracks = sum(record["matched_tracks"] for record in records)
    expected_tracks = sum(record["expected_object_count"] for record in records)
    metrics = {
        "valid_output_rate": sum(record["valid_output"] for record in records) / len(records),
        "median_absolute_track_count_error": median(count_errors),
        "matched_track_recall": matched_tracks / expected_tracks,
        "leftmost_target_selection_accuracy": sum(record["leftmost_target_selected"] for record in records) / len(records),
        "position_median_error_m": median(position_errors) if position_errors else None,
        "orientation_accuracy": sum(record["orientation_accuracy"] * record["matched_tracks"] for record in records) / matched_tracks if matched_tracks else None,
        "evaluated_scenes": len(records),
        "note": "Online inference receives RGB-D only. Static camera calibration and simulator labels are loaded only after prediction by this offline evaluator.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"backend": "geometric_rgbd_v1", "split": args.split, "metrics": metrics, "records": records, "truth_boundary": "offline evaluator only"}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
