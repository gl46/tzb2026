#!/usr/bin/env python3
"""Summarize strict M2B matched Isaac closed-loop episode records."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import cast

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    Method,
    M2BClosedLoopEpisodeV1,
    summarize_matched,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument(
        "--expected-method",
        action="append",
        choices=(
            "B0",
            "QRM_COARSE_NO_FC",
            "QRM_COARSE_FC",
            "QRM_COARSE_FC_MLP",
        ),
        required=True,
    )
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    episodes = [
        M2BClosedLoopEpisodeV1.model_validate_json(line)
        for line in args.episodes.read_text().splitlines()
        if line.strip()
    ]
    expected_methods = tuple(
        cast(Method, method) for method in args.expected_method
    )
    if len(set(expected_methods)) != len(expected_methods):
        raise SystemExit("expected methods must be unique")
    report = summarize_matched(
        episodes,
        expected_methods=expected_methods,
    )
    report.update(
        {
            "episodes_path": str(args.episodes),
            "episodes_sha256": hashlib.sha256(
                args.episodes.read_bytes()
            ).hexdigest(),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["formal_evaluation_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
