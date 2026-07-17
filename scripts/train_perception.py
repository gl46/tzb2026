#!/usr/bin/env python3
"""Record the selected lightweight fine-tune invocation without fabricating a run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/m1b-alpha-finetune-run.json"))
    parser.add_argument("--execute", action="store_true", help="requires explicitly installed GroundingDINO environment")
    args = parser.parse_args()
    if not args.dataset.exists():
        raise SystemExit(f"dataset manifest missing: {args.dataset}")
    result = {"backend": "GroundingDINO", "mode": "frozen_backbone_detector_head", "dataset": str(args.dataset), "executed": False, "status": "NOT_RUN_MODEL_NOT_INSTALLED"}
    if args.execute:
        raise SystemExit("GroundingDINO environment is not bundled; install it outside the repository, record revision, then rerun")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
