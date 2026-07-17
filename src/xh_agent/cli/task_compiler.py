from __future__ import annotations

import argparse

from xh_agent.task_compiler.deterministic import DeterministicTaskCompiler


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a supported Chinese instruction into TaskSpecV1 JSON")
    parser.add_argument("instruction")
    parser.add_argument("--task-id", default="m1b-beta-cli")
    args = parser.parse_args()
    print(DeterministicTaskCompiler().compile(args.instruction, task_id=args.task_id).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
