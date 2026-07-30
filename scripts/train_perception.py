#!/usr/bin/env python3
"""Calibrate the lightweight RGB-D colour-prototype semantic head.

The calibration uses only train/validation supervision to choose a fixed RGB
similarity threshold.  The resulting checkpoint contains no scene seed, object
identifier, pose, or test label, so it can be used by the observation-only
perception process.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median

from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1
from run_geometric_rgbd import load_depth, load_rgb


def _infer_count(sample: dict[str, object], similarity: float) -> tuple[int, int]:
    snapshot = Path(str(sample["rgb"])).parent
    recording = json.loads((snapshot / "recording.json").read_text(encoding="utf-8"))
    camera = json.loads((snapshot / "camera_info.json").read_text(encoding="utf-8"))
    observation = PerceptionInputV1(
        frame_id=str(camera["frame_id"]), timestamp_ns=int(recording["depth"]["timestamp_ns"]),
        rgb_uri=str(sample["rgb"]), depth_uri=str(sample["depth"]),
        camera_intrinsics=list(camera["k"]), camera_frame=str(camera["frame_id"]),
    )
    predictions = GeometricRGBDBaseline(min_component_pixels=50, color_similarity=similarity).infer(
        observation, load_depth(snapshot, recording), load_rgb(snapshot, recording),
    )
    supervision = json.loads(Path(str(sample["supervision"])).read_text(encoding="utf-8"))
    return len(predictions), len(supervision["simulator_supervision"]["objects"])


def _metrics(samples: list[dict[str, object]], similarity: float) -> dict[str, float | int]:
    counts = [_infer_count(sample, similarity) for sample in samples]
    errors = [abs(predicted - expected) for predicted, expected in counts]
    return {
        "scenes": len(counts),
        "median_absolute_track_count_error": float(median(errors)),
        "mean_absolute_track_count_error": sum(errors) / len(errors),
        "valid_output_rate": sum(predicted > 0 for predicted, _ in counts) / len(counts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/m1b-alpha-finetune-run.json"))
    parser.add_argument("--execute", action="store_true", help="run train/validation threshold calibration")
    parser.add_argument("--candidates", type=float, nargs="+", default=[0.93, 0.95, 0.97])
    args = parser.parse_args()
    if not args.dataset.is_file():
        raise SystemExit(f"dataset manifest missing: {args.dataset}")
    if not args.execute:
        raise SystemExit("pass --execute to run the observation-only colour-prototype calibration")
    if any(not 0 < value <= 1 for value in args.candidates):
        raise SystemExit("all --candidates must be in (0, 1]")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    splits = {name: [sample for sample in dataset["samples"] if sample["split"] == name] for name in ("train", "val")}
    if not splits["train"] or not splits["val"]:
        raise SystemExit("captured dataset requires non-empty train and val splits")
    train_metrics = {str(value): _metrics(splits["train"], value) for value in args.candidates}
    selected = min(args.candidates, key=lambda value: (train_metrics[str(value)]["mean_absolute_track_count_error"], -train_metrics[str(value)]["valid_output_rate"]))
    payload = {
        "backend": "color_prototype_adapter_v1",
        "mode": "train_split_threshold_calibration",
        "dataset": str(args.dataset),
        "executed": True,
        "selected_color_similarity": selected,
        "train_metrics_by_candidate": train_metrics,
        "validation_metrics": _metrics(splits["val"], selected),
        "online_contract": "RGB-D observation only; supervision used only during calibration",
        "status": "CALIBRATED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "selected_color_similarity": selected, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
