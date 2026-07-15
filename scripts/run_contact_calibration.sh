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
setsid ros2 launch xh_sim moveit_execution.launch.py >"$launch_log" 2>&1 & pid=$!
cleanup() {
  kill -TERM -- "-$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log" "$tmp/left-contact.log" "$tmp/right-contact.log" "$tmp/cube-contact.log"
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
# The commands are calibration-only controller motions.  They never use a
# Gazebo set-pose service or modify the cube pose.  Their intended semantic is
# recorded separately from the observed contact pairs below.
left_topic=/world/xh_p0_pick_place/model/panda_controller/link/panda_leftfinger/sensor/left_finger_contact/contact
right_topic=/world/xh_p0_pick_place/model/panda_controller/link/panda_rightfinger/sensor/right_finger_contact/contact
cube_topic=/world/xh_p0_pick_place/model/object_red_cube/link/link/sensor/red_cube_contact/contact
timeout 42 gz topic -e -t "$left_topic" >"$tmp/left-contact.log" 2>&1 & left_monitor=$!
timeout 42 gz topic -e -t "$right_topic" >"$tmp/right-contact.log" 2>&1 & right_monitor=$!
timeout 42 gz topic -e -t "$cube_topic" >"$tmp/cube-contact.log" 2>&1 & cube_monitor=$!
declare -a labels=(idle left_1 left_2 left_3 right_1 right_2 right_3 bilateral_1 bilateral_2 bilateral_3 table_1 table_2 object_environment_1 object_environment_2)
declare -a targets=(
  '0.00,-0.50,0.00,-1.50,0.00,1.00,0.00'
  '0.12,-0.25,0.15,-0.20,0.10,0.15,-0.10'
  '0.14,-0.28,0.12,-0.25,0.12,0.18,-0.12'
  '0.10,-0.22,0.18,-0.18,0.08,0.12,-0.08'
  '0.12,-0.25,0.15,-0.20,0.10,0.15,-0.10'
  '0.08,-0.30,0.12,-0.22,0.08,0.18,-0.10'
  '0.16,-0.20,0.16,-0.24,0.12,0.12,-0.14'
  '0.12,-0.25,0.15,-0.20,0.10,0.15,-0.10'
  '0.10,-0.27,0.14,-0.22,0.10,0.16,-0.10'
  '0.14,-0.23,0.16,-0.18,0.10,0.14,-0.12'
  '0.00,-0.50,0.00,-1.50,0.00,1.00,0.00'
  '0.20,-0.35,0.10,-0.40,0.15,0.20,-0.15'
  '0.00,-0.50,0.00,-1.50,0.00,1.00,0.00'
  '0.20,-0.35,0.10,-0.40,0.15,0.20,-0.15'
)
for index in "${!labels[@]}"; do
  echo "CALIBRATION_TRIAL:$((index + 1)):${labels[$index]}:${targets[$index]}"
  IFS=, read -r q1 q2 q3 q4 q5 q6 q7 <<<"${targets[$index]}"
  timeout -k 2 8 ros2 action send_goal /panda_arm_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
    "{trajectory: {joint_names: [panda_joint1, panda_joint2, panda_joint3, panda_joint4, panda_joint5, panda_joint6, panda_joint7], points: [{positions: [$q1, $q2, $q3, $q4, $q5, $q6, $q7], time_from_start: {sec: 2}}]}}" 2>&1 | sed "s/^/CALIBRATION_ACTION:$((index + 1)):/"
done
wait "$left_monitor" || true
wait "$right_monitor" || true
wait "$cube_monitor" || true
echo CONTACT_RAW_LEFT_BEGIN; cat "$tmp/left-contact.log"; echo CONTACT_RAW_LEFT_END
echo CONTACT_RAW_RIGHT_BEGIN; cat "$tmp/right-contact.log"; echo CONTACT_RAW_RIGHT_END
echo CONTACT_RAW_CUBE_BEGIN; cat "$tmp/cube-contact.log"; echo CONTACT_RAW_CUBE_END
REMOTE

python3 - "$RUN_ID" "$raw_log" <<'PY'
import json, sys
from pathlib import Path
run_id, log = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
left = "CONTACT_TOPIC_PRESENT:/world/xh_p0_pick_place/model/panda_controller/link/panda_leftfinger/sensor/left_finger_contact/contact" in raw
right = "CONTACT_TOPIC_PRESENT:/world/xh_p0_pick_place/model/panda_controller/link/panda_rightfinger/sensor/right_finger_contact/contact" in raw
cube = "CONTACT_TOPIC_PRESENT:/world/xh_p0_pick_place/model/object_red_cube/link/link/sensor/red_cube_contact/contact" in raw
trials = raw.count("CALIBRATION_TRIAL:")
if left and right and trials == 14:
    status = "CONTACT_TELEMETRY_UNRELIABLE"
    reason = "All 13 required contact-condition commands plus the 2 s idle baseline ran, but no parsed per-trial bilateral contact calibration result is yet available."
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
    "raw_log": log, "calibration_trials_completed": max(0, trials - 1),
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
