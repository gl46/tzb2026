from __future__ import annotations

import argparse

from xh_agent.recovery.manager import recovery_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit a bounded non-Oracle recovery plan")
    parser.add_argument("failure_type", choices=("EMPTY_GRASP", "UNSTABLE_OR_WRONG_PLACEMENT", "RELEASE_FAILURE"))
    args = parser.parse_args()
    print(recovery_for(args.failure_type).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
