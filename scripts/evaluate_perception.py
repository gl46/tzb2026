#!/usr/bin/env python3
"""Evaluate deterministic fixture predictions with evaluator-only labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/m1b-alpha-perception-metrics.json"))
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    heldout = sum(item["split"] == "test" for item in data["samples"])
    result = {"model": "geometric_rgbd_v1", "heldout_scenes": heldout, "metrics": {}, "status": "MANIFEST_ONLY_NO_GAZEBO_FRAMES"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
