#!/usr/bin/env bash
# S0: observe real finger-specific Gazebo contact telemetry.  This runner
# never treats the cube's single contact sensor as bilateral finger evidence.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-s0-contact-calibration.log"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
source /opt/ros/jazzy/setup.bash
source "$HOME/$root/robot_ws/install/setup.bash"
set -u
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_REMOTE_SIM_ALREADY_RUNNING
  exit 0
fi
tmp=$(mktemp -d)
launch_log="$tmp/launch.log"
setsid ros2 launch xh_bringup bringup.launch.py headless:=true >"$launch_log" 2>&1 & pid=$!
cleanup() {
  kill -TERM -- "-$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
sleep 12
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_S0_LAUNCH_FAILED
  sed -n '1,160p' "$launch_log"
  exit 0
fi
echo M1A_S0_LAUNCH_STARTED
topics="$(gz topic -l 2>/dev/null || true)"
for topic in \
  /world/xh_p0_pick_place/model/panda_controller/link/panda_leftfinger/sensor/left_finger_contact/contact \
  /world/xh_p0_pick_place/model/panda_controller/link/panda_rightfinger/sensor/right_finger_contact/contact \
  /world/xh_p0_pick_place/model/object_red_cube/link/link/sensor/red_cube_contact/contact; do
  if grep -Fqx "$topic" <<<"$topics"; then
    echo "CONTACT_TOPIC_PRESENT:$topic"
    timeout 3 gz topic -e -t "$topic" 2>&1 | head -n 160 || true
  else
    echo "CONTACT_TOPIC_ABSENT:$topic"
  fi
done
REMOTE

python3 - "$RUN_ID" "$raw_log" <<'PY'
import json, sys
from pathlib import Path
run_id, log = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
left = "CONTACT_TOPIC_PRESENT:/world/xh_p0_pick_place/model/panda_controller/link/panda_leftfinger/sensor/left_finger_contact/contact" in raw
right = "CONTACT_TOPIC_PRESENT:/world/xh_p0_pick_place/model/panda_controller/link/panda_rightfinger/sensor/right_finger_contact/contact" in raw
cube = "CONTACT_TOPIC_PRESENT:/world/xh_p0_pick_place/model/object_red_cube/link/link/sensor/red_cube_contact/contact" in raw
if left and right:
    status = "CONTACT_TELEMETRY_PARTIAL"
    reason = "Finger-specific topics exist, but this bounded sensor audit has no calibrated left-only/right-only/bilateral target-contact trials."
else:
    status = "CONTACT_TELEMETRY_BLOCKED"
    reason = "Finger-specific contact topics were not both available from the launched project world."
if "M1A_REMOTE_SIM_ALREADY_RUNNING" in raw:
    status, reason = "CONTACT_TELEMETRY_BLOCKED", "An unrelated or pre-existing project simulation was already running; M1A did not attach to or terminate it."
if "M1A_S0_LAUNCH_FAILED" in raw:
    status, reason = "CONTACT_TELEMETRY_BLOCKED", "The bounded M1A Gazebo launch did not remain alive."
data = {
    "run_id": run_id, "status": status, "reason": reason,
    "left_finger_topic_present": left, "right_finger_topic_present": right,
    "object_contact_topic_present": cube, "minimum_contact_rate_hz": 20.0,
    "required_overlap_s": 0.1, "required_consecutive_samples": 3,
    "raw_log": log, "calibration_trials_completed": 0,
    "calibration_initialization": "NOT_USED", "use_sim_time": True,
}
Path("reports/m1a-contact-calibration.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-calibration.md").write_text(
    "# M1A S0 contact telemetry calibration\n\n"
    f"- Status: `{status}`\n- Reason: {reason}\n"
    f"- Left/right/cube contact topics: `{left}` / `{right}` / `{cube}`\n"
    "- No grasp is claimed by this calibration audit.\n"
)
PY
