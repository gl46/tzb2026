#!/usr/bin/env python3
"""Audit the fixed-seed Isaac contract suite and emit machine-readable status."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from xh_agent.data_engine.isaac.contract import stable_split, validate_episode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--minimum-seeds", type=int, default=50)
    parser.add_argument("--report-json", type=Path, default=Path("reports/m2a-s1-data-contract.json"))
    parser.add_argument("--report-md", type=Path, default=Path("reports/m2a-s1-data-contract.md"))
    args = parser.parse_args()
    episodes: list[dict] = []
    shard_errors: list[str] = []
    for shard in sorted((args.dataset_root / "shards").glob("*.READY")):
        manifest = json.loads((shard / "manifest.json").read_text())
        if manifest.get("state") != "READY":
            shard_errors.append(f"{shard.name}: state is not READY")
            continue
        episodes.extend(
            json.loads(line)
            for line in (shard / "episodes.jsonl").read_text().splitlines()
            if line.strip()
        )
    errors: list[str] = list(shard_errors)
    seed_splits: dict[int, str] = {}
    failure_types: Counter[str] = Counter()
    for episode in episodes:
        errors.extend(
            f"{episode.get('episode_id')}: {error}" for error in validate_episode(episode)
        )
        seed = int(episode["scene_seed"])
        expected_split, _ = stable_split(seed)
        if episode["split"] != expected_split:
            errors.append(f"seed {seed}: unstable split")
        if seed in seed_splits and seed_splits[seed] != episode["split"]:
            errors.append(f"seed {seed}: split leakage")
        seed_splits[seed] = episode["split"]
        failure_types[episode["failure_context"]["failure_type"]] += 1
    limitations: list[str] = []
    if len(seed_splits) < args.minimum_seeds:
        limitations.append(
            f"only {len(seed_splits)} distinct scene seeds; contract asks for {args.minimum_seeds}"
        )
    required_physical_failures = {"EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"}
    missing_failures = sorted(required_physical_failures - set(failure_types))
    if missing_failures:
        limitations.append(
            "pilot adjacent-frame corpus does not physically exercise: "
            + ", ".join(missing_failures)
        )
    if errors:
        status = "ISAAC_DATA_CONTRACT_BLOCKED"
    elif limitations:
        status = "ISAAC_DATA_CONTRACT_VERIFIED_WITH_LIMITATIONS"
    else:
        status = "ISAAC_DATA_CONTRACT_VERIFIED"
    report = {
        "schema_version": "M2AIsaacDataContractReportV1",
        "status": status,
        "dataset_root": str(args.dataset_root),
        "episodes_checked": len(episodes),
        "distinct_scene_seeds": len(seed_splits),
        "split_counts": dict(Counter(seed_splits.values())),
        "failure_types": dict(failure_types),
        "oracle_leakage_detected": any("forbidden" in error or "entity truth" in error for error in errors),
        "errors": sorted(set(errors)),
        "limitations": limitations,
        "protocol": {
            "length": "meter",
            "time": "second/timestamp_ns",
            "camera_optical_axes": "+X right, +Y down, +Z forward",
            "quaternion_runtime": "xyzw",
            "depth": "meter distance-to-image-plane",
            "executed_action": "9D named joint target @30Hz",
            "qrm_residual": "10D camera optical @5Hz",
        },
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.report_md.write_text(
        "\n".join(
            [
                "# M2A S1 Isaac data contract",
                "",
                f"- status: **{status}**",
                f"- episodes checked: {len(episodes)}",
                f"- distinct scene seeds: {len(seed_splits)}",
                f"- Oracle leakage detected: {report['oracle_leakage_detected']}",
                f"- failure types: `{dict(failure_types)}`",
                "",
                "## Limitations",
                "",
                *([f"- {item}" for item in limitations] or ["- None."]),
                "",
            ]
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

