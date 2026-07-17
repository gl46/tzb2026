#!/usr/bin/env python3
"""Offline held-out evaluation of the non-oracle geometric pipeline."""
from __future__ import annotations

import argparse
import json
from statistics import median
from pathlib import Path

from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1
from run_geometric_rgbd import load_depth, load_rgb


def infer(sample: dict[str, object]) -> list[object]:
    recording_path = Path(str(sample["rgb"])).parent / "recording.json"
    snapshot = recording_path.parent
    recording = json.loads(recording_path.read_text(encoding="utf-8"))
    camera = json.loads((snapshot / "camera_info.json").read_text(encoding="utf-8"))
    observation = PerceptionInputV1(frame_id=str(camera["frame_id"]), timestamp_ns=int(recording["depth"]["timestamp_ns"]), rgb_uri=str(sample["rgb"]), depth_uri=str(sample["depth"]), camera_intrinsics=list(camera["k"]), camera_frame=str(camera["frame_id"]))
    return GeometricRGBDBaseline().infer(observation, load_depth(snapshot, recording), load_rgb(snapshot, recording))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--split", default="test", choices=("train", "val", "test"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = []
    for sample in manifest["samples"]:
        if sample["split"] != args.split:
            continue
        results = infer(sample)
        supervision = json.loads(Path(sample["supervision"]).read_text(encoding="utf-8"))
        expected_count = len(supervision["simulator_supervision"]["objects"])
        records.append({"seed": sample["seed"], "track_count": len(results), "expected_object_count": expected_count, "valid_output": bool(results), "orientation_states": [result.orientation_state for result in results]})
    if not records:
        raise SystemExit(f"no {args.split} samples in manifest")
    count_errors = [abs(record["track_count"] - record["expected_object_count"]) for record in records]
    metrics = {"valid_output_rate": sum(record["valid_output"] for record in records) / len(records), "median_absolute_track_count_error": median(count_errors), "evaluated_scenes": len(records), "note": "No target/pose correspondence is claimed until camera extrinsics and simulator truth association are validated."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"backend": "geometric_rgbd_v1", "split": args.split, "metrics": metrics, "records": records, "truth_boundary": "offline evaluator only"}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
