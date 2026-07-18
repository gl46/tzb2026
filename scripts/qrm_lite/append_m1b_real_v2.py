#!/usr/bin/env python3
"""Reserved auto-import interface for M1B non-oracle episodes → QRM-Real-V2.

Beta-1 must not wait on M1B. When M1B emits episode manifests, call this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Append M1B non-oracle episodes as QRM-Real-V2")
    p.add_argument("--m1b-manifest", required=True, help="JSON/JSONL episode manifest from M1B")
    p.add_argument("--out-jsonl", default="data/qrm_lite/manifests/real-v2.jsonl")
    p.add_argument("--report", default="reports/qrm-lite-real-v2-append.json")
    args = p.parse_args(argv)

    src = Path(args.m1b_manifest)
    if not src.exists():
        report = {
            "status": "WAITING_FOR_M1B",
            "m1b_manifest": str(src),
            "note": "Interface ready; do not block Beta-1",
        }
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    # Placeholder: real converter will map M1B EpisodeTransition → QRMTrainingSampleV1
    # and reject oracle-in-observation fields.
    report = {
        "status": "NOT_IMPLEMENTED_CONVERTER_PENDING",
        "m1b_manifest": str(src),
        "out_jsonl": args.out_jsonl,
        "rules": [
            "oracle poses labels only",
            "episode-level split append",
            "no overwrite of Real-V1",
        ],
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
