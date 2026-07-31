#!/usr/bin/env python3
"""Summarize hash-bound prospective Isaac runtime-mapping records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.prospective_mapping import (
    M2BProspectiveRuntimeDecisionV1,
    summarize_prospective_runtime_mapping,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    records = [
        M2BProspectiveRuntimeDecisionV1.model_validate_json(line)
        for line in args.decisions.read_text().splitlines()
        if line.strip()
    ]
    report = summarize_prospective_runtime_mapping(records)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["formal_mapping_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
