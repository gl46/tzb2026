#!/usr/bin/env python3
"""Build a manifest only from RGB-D frames that were actually captured."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/generated/m1b_alpha_v1"))
    parser.add_argument("--output", type=Path, default=Path("data/manifests/m1b-alpha-captured-v1.json"))
    args = parser.parse_args()
    samples = []
    for recording in sorted((args.root / "frames").glob("*/recording.json")):
        seed = int(recording.parent.name)
        supervision = args.root / "scenes" / f"scene-{seed}.supervision.json"
        data = json.loads(recording.read_text(encoding="utf-8"))
        if not supervision.is_file() or not all((recording.parent / data[channel]["uri"]).is_file() for channel in ("rgb", "depth", "camera_info")):
            continue
        labels = json.loads(supervision.read_text(encoding="utf-8"))
        samples.append({"seed": seed, "split": labels["split"], "rgb": str(recording.parent / data["rgb"]["uri"]), "depth": str(recording.parent / data["depth"]["uri"]), "camera_info": str(recording.parent / data["camera_info"]["uri"]), "supervision": str(supervision), "max_stream_skew_ns": data["max_stream_skew_ns"]})
    split_seeds = {name: {sample["seed"] for sample in samples if sample["split"] == name} for name in ("train", "val", "test")}
    if split_seeds["train"] & split_seeds["val"] or split_seeds["train"] & split_seeds["test"] or split_seeds["val"] & split_seeds["test"]:
        raise RuntimeError("scene seed leaked across splits")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema_version": "M1BAlphaCapturedDatasetV1", "samples": samples, "split_by": "scene_seed", "counts": {name: len(split_seeds[name]) for name in split_seeds}}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "captured_samples": len(samples), "heldout_scenes": len(split_seeds["test"]), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
