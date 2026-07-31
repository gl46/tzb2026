#!/usr/bin/env python3
"""Emit the immutable 81-trial, calibration-only M1B tolerance worklist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    trials = []
    instances = config.get("calibration_instances", [])
    if len(instances) != config["repetitions_per_point"]:
        raise SystemExit(
            "calibration_instances must provide exactly one distinct "
            "instance per repetition"
        )
    instance_keys = {
        (item.get("scene_seed"), item.get("object_slot"))
        for item in instances
    }
    if len(instance_keys) != len(instances):
        raise SystemExit(
            "calibration_instances must be distinct scene/object pairs"
        )
    for axis in config["offset_axes"]:
        for offset in config["offsets_m"]:
            for repetition in range(
                1,
                config["repetitions_per_point"] + 1,
            ):
                instance = instances[repetition - 1]
                trials.append(
                    {
                        "axis": axis,
                        "offset_m": offset,
                        "repetition": repetition,
                        "provenance": "CALIBRATION_ONLY_INITIALIZATION",
                        "required_distinct_instance_slot": repetition,
                        "scene_seed": int(instance["scene_seed"]),
                        "object_slot": int(instance["object_slot"]),
                    }
                )
    payload = {
        "schema_version": "M1BToleranceCalibrationWorklistV1",
        "timebox_hours": 3,
        "trials": trials,
        "trial_count": len(trials),
        "early_stop": "forbidden_except_infrastructure_failure",
        "online_truth_access": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"trial_count": len(trials)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
