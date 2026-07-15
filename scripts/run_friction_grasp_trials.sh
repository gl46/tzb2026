#!/usr/bin/env bash
# S2: at most five baseline friction trials; stop after three approach failures.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
local_sha="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"
if ! python3 - "$RUN_ID" "$local_sha" <<'PY'
import json
import sys
from pathlib import Path

run_id, local_sha = sys.argv[1:]
def load(name):
    path = Path("reports") / name
    return json.loads(path.read_text()) if path.exists() else {}
s0, s1 = load("m1a-contact-calibration.json"), load("m1a-motion-execution.json")
ready = (
    s0.get("status") == "CONTACT_TELEMETRY_CALIBRATED"
    and s0.get("model_match") is True
    and s0.get("local_gazebo_urdf_sha256") == local_sha
    and s1.get("motion_status") == "VERIFIED_MOVEIT_EXECUTION"
    and s1.get("model_match") is True
    and s1.get("local_gazebo_urdf_sha256") == local_sha
)
if not ready:
    data = {
        "status": "FRICTION_TRIALS_BLOCKED_REVALIDATION_REQUIRED",
        "run_id": run_id,
        "frictional_trials": 0,
        "frictional_successes": 0,
        "failure_counts": {},
        "trials": [],
        "detachable_joint_absent": True,
        "early_stop": False,
        "reason": "S2 requires current-model calibrated S0 and verified S1 evidence.",
        "local_gazebo_urdf_sha256": local_sha,
    }
    Path("reports/m1a-friction-trials.json").write_text(json.dumps(data, indent=2) + "\n")
    Path("reports/m1a-friction-trials.md").write_text(
        "# M1A S2 friction trials\n\n- Status: `FRICTION_TRIALS_BLOCKED_REVALIDATION_REQUIRED`\n"
    )
raise SystemExit(0 if ready else 1)
PY
then
  exit 2
fi
logs=()
for attempt in 1 2 3 4 5; do
  log="logs/${RUN_ID}-s2-baseline-${attempt}.log"; logs+=("$log")
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"; source /opt/ros/jazzy/setup.bash; source "/home/$USER/$root/robot_ws/install/setup.bash"
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then echo M1A_REMOTE_SIM_ALREADY_RUNNING; exit 0; fi
tmp=$(mktemp -d); launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=true >"$launch_log" 2>&1 & pid=$!
cleanup() { kill -TERM -- "-$pid" 2>/dev/null || true; sleep 1; kill -KILL -- "-$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -f "$launch_log"; rmdir "$tmp" 2>/dev/null || true; }
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
python3 - "$RUN_ID" "$local_sha" "${logs[@]}" <<'PY'
import json, sys
from pathlib import Path
run_id, local_sha, *logs = sys.argv[1:]
trials = []
for index, path in enumerate(logs, 1):
    payload = next((json.loads(line) for line in Path(path).read_text(errors="replace").splitlines()
                    if line.startswith("{") and '"primary_failure_class"' in line), None)
    if payload is None:
        payload = {"status": "FRICTION_TRIAL_FAILED", "primary_failure_class": "APPROACH_ALIGNMENT_FAILURE", "reason": "NO_STRUCTURED_RUNTIME_EVIDENCE"}
    trials.append({"trial_id": f"{run_id}-baseline-{index}", **payload, "raw_log": path})
counts = {name: sum(t.get("primary_failure_class") == name for t in trials) for name in ("APPROACH_ALIGNMENT_FAILURE", "CONTACT_CLOSURE_FAILURE", "HOLD_TRANSPORT_FAILURE", "RELEASE_PLACEMENT_FAILURE")}
early = counts["APPROACH_ALIGNMENT_FAILURE"] >= 3
data = {"status": "FRICTIONAL_GRASP_NOT_VERIFIED", "run_id": run_id, "frictional_trials": len(trials), "frictional_successes": 0, "failure_counts": counts, "trials": trials, "detachable_joint_absent": True, "early_stop": early, "reason": "Stopped after three approach-alignment failures; friction parameters were not changed because contact was not established." if early else "Baseline configuration completed without verified frictional grasp.", "local_gazebo_urdf_sha256": local_sha}
Path("reports/m1a-friction-trials.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-friction-trials.md").write_text("# M1A S2 friction trials\n\n" + f"- Status: `{data['status']}`\n- Trials: `{len(trials)}`\n- Failure counts: `{counts}`\n- Early stop: `{early}`\n")
PY
