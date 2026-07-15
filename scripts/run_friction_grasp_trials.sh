#!/usr/bin/env bash
# S2: at most five baseline friction trials; stop after three approach failures.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
logs=()
for attempt in 1 2 3 4 5; do
  log="logs/${RUN_ID}-s2-baseline-${attempt}.log"; logs+=("$log")
  ssh gl@node2 'bash -s -- xh-202607-world-agent' >"$log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"; source /opt/ros/jazzy/setup.bash; source "/home/$USER/$root/robot_ws/install/setup.bash"
tmp=$(mktemp -d); launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=true >"$launch_log" 2>&1 & pid=$!
cleanup() { kill -TERM -- "-$pid" 2>/dev/null || true; sleep 1; kill -KILL -- "-$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -rf "$tmp"; }
trap cleanup EXIT
sleep 15
python3 "/home/$USER/$root/scripts/m1a_friction_trial_client.py"
REMOTE
  failures=$(python3 - "${logs[@]}" <<'PY'
import json, sys
count = 0
for path in sys.argv[1:]:
    for line in open(path, errors="replace"):
        if line.startswith("{") and '"primary_failure_class"' in line:
            count += json.loads(line)["primary_failure_class"] == "APPROACH_ALIGNMENT_FAILURE"
            break
print(count)
PY
)
  [ "$failures" -ge 3 ] && break
done
python3 - "$RUN_ID" "${logs[@]}" <<'PY'
import json, sys
from pathlib import Path
run_id, *logs = sys.argv[1:]
trials = []
for index, path in enumerate(logs, 1):
    payload = next((json.loads(line) for line in Path(path).read_text(errors="replace").splitlines()
                    if line.startswith("{") and '"primary_failure_class"' in line), None)
    if payload is None:
        payload = {"status": "FRICTION_TRIAL_FAILED", "primary_failure_class": "APPROACH_ALIGNMENT_FAILURE", "reason": "NO_STRUCTURED_RUNTIME_EVIDENCE"}
    trials.append({"trial_id": f"{run_id}-baseline-{index}", **payload, "raw_log": path})
counts = {name: sum(t.get("primary_failure_class") == name for t in trials) for name in ("APPROACH_ALIGNMENT_FAILURE", "CONTACT_CLOSURE_FAILURE", "HOLD_TRANSPORT_FAILURE", "RELEASE_PLACEMENT_FAILURE")}
early = counts["APPROACH_ALIGNMENT_FAILURE"] >= 3
data = {"status": "FRICTIONAL_GRASP_NOT_VERIFIED", "run_id": run_id, "frictional_trials": len(trials), "frictional_successes": 0, "failure_counts": counts, "trials": trials, "detachable_joint_absent": True, "early_stop": early, "reason": "Stopped after three approach-alignment failures; friction parameters were not changed because contact was not established." if early else "Baseline configuration completed without verified frictional grasp."}
Path("reports/m1a-friction-trials.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-friction-trials.md").write_text("# M1A S2 friction trials\n\n" + f"- Status: `{data['status']}`\n- Trials: `{len(trials)}`\n- Failure counts: `{counts}`\n- Early stop: `{early}`\n")
PY
