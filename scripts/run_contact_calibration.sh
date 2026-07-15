#!/usr/bin/env bash
# S0: runtime-oracle geometry -> MoveIt -> controllers -> per-trial contacts/FK.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
CALIBRATION_SCOPE="${M1A_CALIBRATION_SCOPE:-full}"
CALIBRATION_REPETITION="${M1A_CALIBRATION_REPETITION:-1}"
CALIBRATION_LABEL="${M1A_CALIBRATION_LABEL:-}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-s0-contact-calibration.log"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT' '$CALIBRATION_SCOPE' '$CALIBRATION_REPETITION' '$CALIBRATION_LABEL'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
scope="$2"
repetition="$3"
label="$4"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
set -u
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_REMOTE_SIM_ALREADY_RUNNING
  exit 0
fi
tmp=$(mktemp -d)
launch_log="$tmp/launch.log"
calibration_world="/home/$USER/$root/robot_ws/install/xh_sim/share/xh_sim/worlds/m1a_contact_calibration.sdf"
setsid ros2 launch xh_sim moveit_execution.launch.py world_file:="$calibration_world" calibration_mode:=true >"$launch_log" 2>&1 & pid=$!
cleanup() {
  kill -TERM -- "-$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
sleep 15
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_S0_LAUNCH_FAILED
  sed -n '1,220p' "$launch_log"
  exit 0
fi
echo M1A_S0_LAUNCH_STARTED
gz topic -l 2>/dev/null | grep -E 'left_finger_contact|right_finger_contact|red_cube_contact' | sed 's/^/CONTACT_GZ_TOPIC:/' || true
ros2 topic list | grep -E '/xh/supervision/(panda_(left|right)finger_contacts|red_cube_contacts)' | sed 's/^/CONTACT_ROS_TOPIC:/' || true
M1A_CALIBRATION_SCOPE="$scope" M1A_CALIBRATION_REPETITION="$repetition" M1A_CALIBRATION_LABEL="$label" \
  python3 "/home/$USER/$root/scripts/m1a_contact_calibration_client.py"
echo M1A_S0_LAUNCH_TAIL
tail -n 220 "$launch_log"
REMOTE

python3 - "$RUN_ID" "$raw_log" <<'PY'
import json
import sys
from pathlib import Path

run_id, log = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
runtime = next(
    (json.loads(line) for line in raw.splitlines() if line.startswith("{") and '"trials"' in line),
    None,
)
if runtime is None:
    status = "CONTACT_TELEMETRY_BLOCKED"
    if "M1A_REMOTE_SIM_ALREADY_RUNNING" in raw:
        reason = "A pre-existing simulation was running; the bounded calibration did not attach to it."
    elif "M1A_S0_LAUNCH_FAILED" in raw:
        reason = "The bounded MoveIt/Gazebo calibration launch did not remain alive."
    else:
        reason = "No structured runtime-oracle contact calibration evidence returned."
    data = {"run_id": run_id, "status": status, "reason": reason, "raw_log": log, "trials": []}
else:
    data = {"run_id": run_id, **runtime, "raw_log": log}
    status, reason = data["status"], data["reason"]
data.update(
    {
        "minimum_contact_rate_hz": 20.0,
        "required_overlap_s": 0.1,
        "required_consecutive_samples": 3,
        "calibration_trials_completed": max(0, len(data.get("trials", [])) - 1),
        "use_sim_time": True,
        "listener_scope": "PER_TRIAL_FULL_ACTION_WINDOW",
    }
)
Path("reports/m1a-contact-calibration.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-calibration.md").write_text(
    "# M1A S0 contact telemetry calibration\n\n"
    f"- Status: `{status}`\n- Reason: {reason}\n"
    f"- Runtime oracle pose source: `{data.get('oracle_pose_source')}`\n"
    f"- Completed condition trials: `{data['calibration_trials_completed']}/13`\n"
    "- Every motion trial records cube pose, MoveIt/IK result, finger action, pad FK, minimum AABB separation, and raw contact pairs.\n"
    "- No grasp is claimed by this calibration audit.\n"
)
PY
