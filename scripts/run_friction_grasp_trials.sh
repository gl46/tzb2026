#!/usr/bin/env bash
# S2 is intentionally unreachable unless S1 is explicitly verified.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - <<'PY'
import json
from pathlib import Path
motion = json.loads(Path("reports/m1a-motion-execution.json").read_text())
status = "NOT_RUN_S1_NOT_VERIFIED" if motion["motion_status"] != "VERIFIED_MOVEIT_EXECUTION" else "NOT_IMPLEMENTED"
data = {"status": status, "frictional_trials": 0, "frictional_successes": 0,
        "failure_counts": {k: 0 for k in ("APPROACH_ALIGNMENT_FAILURE", "CONTACT_CLOSURE_FAILURE", "HOLD_TRANSPORT_FAILURE", "RELEASE_PLACEMENT_FAILURE")},
        "reason": "S2 did not run because S1 has not established a verified MoveIt execution chain."}
Path("reports/m1a-friction-trials.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-friction-trials.md").write_text(f"# M1A S2 friction trials\n\n- Status: `{status}`\n- Trials: `0`\n")
PY
