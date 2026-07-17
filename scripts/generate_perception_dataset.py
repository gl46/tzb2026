#!/usr/bin/env python3
"""Create a deterministic, scene-seed split manifest for M1B-alpha.

This command produces a small local geometric fixture for software verification.
It does not label itself as Gazebo evidence; Gazebo runs use the same manifest
format and replace `generator` with `gazebo_harmonic`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def split(seed: int) -> str:
    bucket = seed % 20
    return "train" if bucket < 14 else "val" if bucket < 17 else "test"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("data/manifests/m1b-alpha-dataset-v1.json"))
    parser.add_argument("--generator", choices=["fixture", "gazebo_harmonic"], default="fixture")
    args = parser.parse_args()
    if args.count < 150:
        raise SystemExit("--count must be at least 150")
    records = []
    for offset in range(args.count):
        seed = args.seed_start + offset
        heldout = split(seed) == "test"
        records.append({
            "scene_id": "IndustrialCylinderBenchmarkV1", "seed": seed, "split": split(seed),
            "generator": args.generator, "rgb": f"data/generated/m1b_alpha_v1/{seed}/rgb.png",
            "depth": f"data/generated/m1b_alpha_v1/{seed}/depth.npy", "labels": f"data/generated/m1b_alpha_v1/{seed}/labels.json",
            "randomization": {"material": "reflective_metal" if heldout else "matte_metal", "camera_offset_m": 0.02 if heldout else 0.0, "part_count": 6 + seed % 7, "orientation": ["normal", "inverted", "tilted"][seed % 3]},
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema_version": "SceneManifestV1", "samples": records, "split_by": "scene_seed", "heldout_combination": "reflective_metal_plus_camera_offset"}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "samples": len(records), "heldout_scenes": sum(row["split"] == "test" for row in records), "generator": args.generator}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
