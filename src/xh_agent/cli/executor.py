from __future__ import annotations

import argparse
import json

from xh_agent.agent.skill_planner import plan
from xh_agent.task_compiler.base import TaskSpecV1


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce the public M1B-beta skill sequence for a TaskSpecV1 JSON")
    parser.add_argument("task_spec_json")
    args = parser.parse_args()
    task = TaskSpecV1.model_validate_json(open(args.task_spec_json, encoding="utf-8").read())
    print(json.dumps({"task_id": task.task_id, "skills": plan(task), "oracle_provider": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
