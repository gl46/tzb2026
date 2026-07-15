#!/usr/bin/env bash
# Bounded remote MoveIt planning check. This does not execute a Gazebo action.
set -euo pipefail

mkdir -p reports
python_bin="python3"
if [[ -x .venv/bin/python ]]; then python_bin=".venv/bin/python"; fi
host="${MOVEIT_HOST:-${SIM_HOST:-}}"
user="${MOVEIT_USER:-${SIM_USER:-}}"
if [[ -z "$host" ]]; then
  "$python_bin" - <<'PY'
import json
from pathlib import Path
Path("reports/b1-moveit-planning-status.json").write_text(json.dumps({"status": "NOT_RUN_REMOTE_NOT_CONFIGURED"}, indent=2) + "\n")
PY
  echo "NOT_RUN_REMOTE_NOT_CONFIGURED"
  exit 0
fi
if [[ -z "$user" ]]; then
  case "$host" in node2) user="gl";; chxy) user="fx";; *) user="$USER";; esac
fi
project_root="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
if [[ ! "$project_root" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "PROJECT_REMOTE_ROOT must be a simple relative path" >&2
  exit 2
fi
remote_output="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "${user}@${host}" "bash -s -- '${project_root}'" <<'REMOTE'
set -e
source /opt/ros/jazzy/setup.bash
source "$HOME/$1/robot_ws/install/setup.bash"
tmp=$(mktemp -d)
log="$tmp/launch.log"
plan="$tmp/plan.log"
setsid ros2 launch xh_sim moveit_planning_smoke.launch.py >"$log" 2>&1 & pid=$!
cleanup() {
  kill -TERM -- "-$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$log" "$plan"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
sleep 12
if ! kill -0 "$pid" 2>/dev/null; then
  echo MOVEIT_SERVER_DID_NOT_STAY_UP
  sed -n '1,120p' "$log"
  exit 0
fi
if ros2 service list | grep -qx /plan_kinematic_path; then echo MOVEIT_PLAN_SERVICE_FOUND; fi
timeout -k 2 20 ros2 service call /plan_kinematic_path moveit_msgs/srv/GetMotionPlan \
  '{motion_plan_request: {group_name: panda_arm, num_planning_attempts: 1, allowed_planning_time: 3.0, max_velocity_scaling_factor: 0.1, max_acceleration_scaling_factor: 0.1, goal_constraints: [{joint_constraints: [{joint_name: panda_joint1, position: 0.1, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}, {joint_name: panda_joint2, position: -0.2, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}, {joint_name: panda_joint3, position: 0.1, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}, {joint_name: panda_joint4, position: -1.5, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}, {joint_name: panda_joint5, position: 0.1, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}, {joint_name: panda_joint6, position: 1.5, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}, {joint_name: panda_joint7, position: 0.1, tolerance_above: 0.01, tolerance_below: 0.01, weight: 1.0}]}]}}' >"$plan" 2>&1 || true
if grep -q 'MoveItErrorCodes(val=1' "$plan" && grep -q 'JointTrajectoryPoint' "$plan"; then
  echo MOVEIT_PLAN_SUCCEEDED
fi
REMOTE
)" || true

status="BLOCKED_MOVEIT_PLANNING"
if grep -q MOVEIT_PLAN_SUCCEEDED <<<"$remote_output"; then status="VERIFIED_MOTION_PLAN_ONLY"; fi
"$python_bin" - "$status" "$host" <<'PY'
import json, sys
from pathlib import Path
Path("reports/b1-moveit-planning-status.json").write_text(json.dumps({
    "status": sys.argv[1], "host": sys.argv[2],
    "gazebo_execution_verified": False,
    "note": "Official Panda MoveIt planning service only; dispatch to the Gazebo controller is not claimed.",
}, indent=2) + "\n")
PY
printf '%s\n' "$remote_output"
echo "$status"
