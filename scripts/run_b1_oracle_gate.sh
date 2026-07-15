#!/usr/bin/env bash
# S4 cannot relabel a plan or scripted run as B1 Oracle execution.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - <<'PY'
import json
from pathlib import Path
s1 = json.loads(Path("reports/m1a-motion-execution.json").read_text())
data = {"status": "B1_ORACLE_BLOCKED", "b1_trials": 0, "b1_successes": 0,
        "mode": "B1_ORACLE_GEOMETRIC_BASELINE", "reason": f"S1={s1['motion_status']}; B1 execution was not started.",
        "oracle_pose_in_observation": False}
Path("reports/m1a-b1-oracle.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-b1-oracle.md").write_text(f"# M1A S4 B1 Oracle\n\n- Status: `{data['status']}`\n- {data['reason']}\n")
PY
