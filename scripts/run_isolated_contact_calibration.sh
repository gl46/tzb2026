#!/usr/bin/env bash
# S0 calibration with one fresh Gazebo/MoveIt session per required condition.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
labels=(left_1 left_2 left_3 right_1 right_2 right_3 bilateral_1 bilateral_2 bilateral_3 object_environment_1 object_environment_2 table_1 table_2)
logs=()

for label in "${labels[@]}"; do
  child_run_id="${RUN_ID}-${label}"
  M1A_RUN_ID="$child_run_id" M1A_CALIBRATION_SCOPE=one M1A_CALIBRATION_LABEL="$label" \
    bash "$ROOT/scripts/run_contact_calibration.sh"
  logs+=("$ROOT/logs/${child_run_id}-s0-contact-calibration.log")
done

python3 - "$RUN_ID" "${logs[@]}" <<'PY'
import json
import sys
from pathlib import Path

run_id, *logs = sys.argv[1:]
trials = []
idle = None
for log in logs:
    raw = Path(log).read_text(errors="replace")
    payload = next((json.loads(line) for line in raw.splitlines()
                    if line.startswith("{") and '"trials"' in line), None)
    if payload is None:
        raise SystemExit(f"no structured contact evidence in {log}")
    for trial in payload["trials"]:
        if trial["label"] == "idle" and idle is None:
            idle = trial
        elif trial["label"] != "idle":
            trials.append(trial)
if idle is None or len(trials) != 13:
    raise SystemExit(f"expected one idle and 13 isolated trials, got idle={idle is not None} trials={len(trials)}")
combined = [idle, *trials]
positives = [trial for trial in trials if trial["expected"] in {"left", "right", "bilateral"}]
status = "CONTACT_TELEMETRY_CALIBRATED" if all(trial.get("passed") for trial in combined) else "CONTACT_TELEMETRY_PARTIAL"
data = {
    "run_id": run_id,
    "status": status,
    "reason": f"{sum(bool(trial.get('passed')) for trial in combined)}/14 independent calibration windows passed; {sum(bool(trial.get('passed')) for trial in positives)}/9 finger-target positive windows passed.",
    "oracle_pose_source": "gz model runtime query before every motion trial",
    "listener_scope": "PER_TRIAL_FULL_ACTION_WINDOW",
    "session_isolation": "FRESH_GAZEBO_MOVEIT_SESSION_PER_CONDITION",
    "source_logs": logs,
    "trials": combined,
}
Path("reports/m1a-contact-calibration.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-calibration.md").write_text(
    "# M1A S0 contact telemetry calibration\n\n"
    f"- Status: `{status}`\n- Reason: {data['reason']}\n"
    "- Each of the 13 conditions ran in a fresh Gazebo/MoveIt session; no post-contact state is reused.\n"
    "- No grasp is claimed by this calibration audit.\n"
)
PY
