"""Record contract-validated episodes only after a real recorder supplies non-privileged data."""

import argparse
import json
from pathlib import Path

from xh_agent.contracts.models import EpisodeTransitionV0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", help="validated EpisodeTransitionV0 JSON")
    parser.add_argument("--output", default="data/episodes/episode.json")
    args = parser.parse_args()
    sample = EpisodeTransitionV0.model_validate_json(Path(args.input_json).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sample.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
