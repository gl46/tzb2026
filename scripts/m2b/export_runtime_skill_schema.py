#!/usr/bin/env python3
"""Export the checked-in RuntimeSkillRequestV1 JSON schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.skill_registry import RuntimeSkillRequestV1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("schemas/runtime-skill-v1.schema.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(RuntimeSkillRequestV1.model_json_schema(), indent=2, sort_keys=True)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
