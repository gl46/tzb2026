from __future__ import annotations

import argparse
import json

from xh_agent.agent.comparator import compare
from xh_agent.agent.expected_outcome import expected_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare public actual predicates to a skill expectation")
    parser.add_argument("skill")
    parser.add_argument("actual_predicates_json")
    args = parser.parse_args()
    actual = json.loads(args.actual_predicates_json)
    outcome, residual = compare(expected_for(args.skill), actual)
    print(json.dumps({"comparison": outcome, "residual": residual, "oracle_provider": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
