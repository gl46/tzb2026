#!/usr/bin/env python3
"""Merge validated isolated-preflight JSONL shards without duplication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from m2b.build_prospective_runtime_decisions import (
    IsolatedIsaacPreflightManifestV1,
)


def merge_shards(
    shards: list[Path],
) -> list[IsolatedIsaacPreflightManifestV1]:
    records = [
        IsolatedIsaacPreflightManifestV1.model_validate_json(line)
        for shard in shards
        for line in shard.read_text().splitlines()
        if line.strip()
    ]
    sample_ids = [record.sample_id for record in records]
    duplicates = sorted(
        sample_id
        for sample_id in set(sample_ids)
        if sample_ids.count(sample_id) > 1
    )
    if duplicates:
        raise ValueError(f"duplicate preflight sample IDs: {duplicates}")
    return sorted(records, key=lambda record: record.sample_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    records = merge_shards(args.shard)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(record.model_dump_json() + "\n" for record in records)
    )
    report = {
        "schema_version": "M2BIsolatedPreflightShardMergeV1",
        "status": "PASS",
        "shards": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in args.shard
        ],
        "records": len(records),
        "unique_sample_ids": len({record.sample_id for record in records}),
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
