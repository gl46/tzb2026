#!/usr/bin/env python3
"""Export M2B physical-failure and residual-pair schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.data_engine.isaac.failure_rich import (
    PhysicalFailureEvidenceV2,
    ResidualCorrectionPairV2,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema-dir", type=Path, default=Path("schemas"))
    args = parser.parse_args()
    args.schema_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in (
        ("physical-failure-evidence-v2.schema.json", PhysicalFailureEvidenceV2),
        ("residual-correction-pair-v2.schema.json", ResidualCorrectionPairV2),
    ):
        (args.schema_dir / filename).write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True)
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
