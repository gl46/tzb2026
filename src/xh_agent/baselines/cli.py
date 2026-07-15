from __future__ import annotations

import json
from pathlib import Path

from xh_agent.baselines.b1 import run_b1
from xh_agent.contracts.models import TaskSpecV0


def main() -> int:
    task = TaskSpecV0(
        task_id="baseline-demo", operation="pick_place", target_object_id="object_red_cube",
        reference_frame="world", destination="bin_a", goal_predicates=["in:bin_a"],
        ambiguity_score=0.0, need_clarification=False, source_instruction="place red cube in bin",
    )
    result = run_b1(task)
    payload = {"status": result.status, "reason": result.reason, "skill_count": len(result.skills),
               "teacher_used": False, "execution_verified": False}
    Path("reports").mkdir(exist_ok=True)
    Path("reports/b1-baseline-status.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
