"""Mechanical exporter for the checked-in JSON Schema counterparts of Pydantic models."""

import json
from pathlib import Path

from xh_agent.contracts.models import CONTRACT_MODELS


def main() -> int:
    destination = Path("schemas")
    destination.mkdir(exist_ok=True)
    for filename, model in CONTRACT_MODELS.items():
        (destination / filename).write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
