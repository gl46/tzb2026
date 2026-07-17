#!/usr/bin/env python3
"""Run the non-oracle geometric baseline on one recorded RGB-D snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1


def load_depth(snapshot: Path, metadata: dict[str, object]) -> np.ndarray:
    depth = metadata["depth"]
    assert isinstance(depth, dict)
    encoding = depth["encoding"]
    if encoding != "32FC1":
        raise ValueError(f"only 32FC1 depth is currently supported, got {encoding}")
    width, height, step = int(depth["width"]), int(depth["height"]), int(depth["step"])
    raw = (snapshot / str(depth["uri"])).read_bytes()
    if len(raw) != height * step:
        raise ValueError("depth byte length does not match recording metadata")
    rows = np.frombuffer(raw, dtype="<f4").reshape(height, step // 4)
    return rows[:, :width].astype(float)


def load_rgb(snapshot: Path, metadata: dict[str, object]) -> np.ndarray:
    rgb = metadata["rgb"]
    assert isinstance(rgb, dict)
    raw = (snapshot / str(rgb["uri"])).read_bytes()
    header, pixels = raw.split(b"\n", 3)[0:3], raw.split(b"\n", 3)[3]
    if header[0] != b"P6":
        raise ValueError("only P6 RGB recordings are supported")
    width, height = (int(value) for value in header[1].split())
    if header[2] != b"255" or len(pixels) != width * height * 3:
        raise ValueError("invalid P6 RGB payload")
    return np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    recording = json.loads((args.snapshot / "recording.json").read_text(encoding="utf-8"))
    camera = json.loads((args.snapshot / "camera_info.json").read_text(encoding="utf-8"))
    observation = PerceptionInputV1(
        frame_id=str(camera["frame_id"]), timestamp_ns=int(recording["depth"]["timestamp_ns"]),
        rgb_uri=str(args.snapshot / recording["rgb"]["uri"]), depth_uri=str(args.snapshot / recording["depth"]["uri"]),
        camera_intrinsics=list(camera["k"]), camera_frame=str(camera["frame_id"]),
    )
    results = GeometricRGBDBaseline().infer(observation, load_depth(args.snapshot, recording), load_rgb(args.snapshot, recording))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"input": recording["channels"], "results": [item.model_dump() for item in results]}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "tracks": len(results), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
