#!/usr/bin/env python3
"""Validate a READY Isaac shard, media, hashes, and Oracle isolation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from xh_agent.data_engine.isaac.contract import (
    canonical_json_sha256,
    sha256_file,
    stable_split,
    validate_episode,
)


def dataset_path(shard: Path, uri: str) -> Path:
    prefix = f"dataset://{shard.name}/"
    if not uri.startswith(prefix):
        raise ValueError(f"URI is not shard-relative: {uri}")
    relative = Path(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"URI escapes shard: {uri}")
    return shard / relative


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shard", type=Path)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()
    shard = args.shard
    manifest = json.loads((shard / "manifest.json").read_text())
    errors: list[str] = []
    if not shard.name.endswith(".READY") or manifest.get("state") != "READY":
        errors.append("shard is not READY")
    expected_hash = manifest.pop("manifest_content_hash", None)
    manifest_for_hash = dict(manifest)
    manifest_for_hash["state"] = "VALIDATING"
    if expected_hash != canonical_json_sha256(manifest_for_hash):
        errors.append("manifest content hash mismatch")
    manifest["manifest_content_hash"] = expected_hash
    for relative, expected in manifest.get("files", {}).items():
        path = shard / relative
        if not path.is_file() or sha256_file(path) != expected:
            errors.append(f"file hash mismatch: {relative}")
    episodes_path = shard / "episodes.jsonl"
    episodes = [
        json.loads(line) for line in episodes_path.read_text().splitlines() if line.strip()
    ]
    if len(episodes) != manifest.get("episode_count"):
        errors.append("episode count mismatch")
    ids: set[str] = set()
    seed_splits: dict[int, str] = {}
    for episode in episodes:
        errors.extend(f"{episode.get('episode_id')}: {item}" for item in validate_episode(episode))
        episode_id = episode["episode_id"]
        if episode_id in ids:
            errors.append(f"duplicate episode: {episode_id}")
        ids.add(episode_id)
        seed = int(episode["scene_seed"])
        split, _ = stable_split(seed)
        if episode["split"] != split:
            errors.append(f"split mismatch for seed {seed}")
        if seed in seed_splits and seed_splits[seed] != episode["split"]:
            errors.append(f"scene seed leaks across splits: {seed}")
        seed_splits[seed] = episode["split"]
        for observation_name in ("observation_before", "observation_after"):
            observation = episode[observation_name]
            rgb = np.asarray(Image.open(dataset_path(shard, observation["rgb_uri"])).convert("RGB"))
            depth = np.load(dataset_path(shard, observation["depth_uri"]))
            if rgb.size == 0 or np.all(rgb == 0) or np.all(rgb == 255):
                errors.append(f"{episode_id}: invalid RGB")
            valid_depth = np.isfinite(depth) & (depth > 0)
            if float(valid_depth.mean()) < 0.01:
                errors.append(f"{episode_id}: depth valid ratio below 1%")
    report = {
        "schema_version": "IsaacShardValidationV1",
        "status": "PASS" if not errors else "FAIL",
        "shard": str(shard),
        "episodes": len(episodes),
        "scene_seeds": sorted(seed_splits),
        "errors": sorted(set(errors)),
    }
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

