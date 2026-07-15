#!/usr/bin/env bash
# Record 20 actual empty-grasp failures. The fixture deliberately never sends
# the DetachableJoint attach request, then verifies the cube did not enter bin_a.
set -euo pipefail

mkdir -p reports data/episodes
python_bin="python3"; [[ -x .venv/bin/python ]] && python_bin=".venv/bin/python"
host="${FAILURE_HOST:-${SIM_HOST:-}}"
user="${FAILURE_USER:-${SIM_USER:-}}"
project_root="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
[[ -n "$host" ]] || { echo "FAILURE_HOST or SIM_HOST is required" >&2; exit 2; }
[[ -n "$user" ]] || case "$host" in node2) user=gl;; chxy) user=fx;; *) user="$USER";; esac
[[ "$project_root" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "invalid PROJECT_REMOTE_ROOT" >&2; exit 2; }

remote_output="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$user@$host" "bash -s -- '$project_root'" <<'REMOTE'
source /opt/ros/jazzy/setup.bash
source "$HOME/$1/robot_ws/install/setup.bash"
set -eo pipefail
tmp=$(mktemp -d); pid=""
cleanup() { if [ -n "$pid" ]; then kill -TERM -- "-$pid" 2>/dev/null || true; sleep 1; kill -KILL -- "-$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi; rm -rf "$tmp"; }
trap cleanup EXIT INT TERM
pose() {
  local raw
  raw="$(gz model -m object_red_cube -p 2>/dev/null || true)"
  python3 - "$raw" <<'PY'
import re, sys
m = re.findall(r"\[(-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+)\]", sys.argv[1])
print(','.join(m[0]) if m else 'MISSING')
PY
}
setsid ros2 launch xh_bringup bringup.launch.py headless:=true >"$tmp/launch.log" 2>&1 & pid=$!
sleep 14
gz topic -t /xh/p0/red_cube/detach -m gz.msgs.Empty -p 'unused: true' || true
for index in $(seq 1 20); do
  # Small different approach offsets are intentional failure-injection seeds.
  q1=$(python3 - "$index" <<'PY'
import sys
print(f"{-0.337 + 0.003 * int(sys.argv[1]):.3f}")
PY
)
  timeout -k 2 12 ros2 action send_goal /panda_arm_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
    "{trajectory: {joint_names: [panda_joint1, panda_joint2, panda_joint3, panda_joint4, panda_joint5, panda_joint6, panda_joint7], points: [{positions: [$q1, 1.06, 0.76, -2.148, -1.435, 2.274, 1.422], time_from_start: {sec: 2}}, {positions: [0, 0, 0, 0, 0, 0, 0], time_from_start: {sec: 4}}, {positions: [-1.9262, -1.6941, 2.8863, -1.9115, -0.9962, 3.0409, 2.2138], time_from_start: {sec: 6}}]}}" >"$tmp/$index.log" 2>&1 || true
  action=false; grep -q 'Goal finished with status: SUCCEEDED' "$tmp/$index.log" && action=true
  cube=$(pose)
  echo "EMPTY_GRASP:$index:$action:$cube"
done
REMOTE
)" || true

REMOTE_OUTPUT="$remote_output" "$python_bin" - "$host" <<'PY'
import json, os, re, sys
from pathlib import Path
host, output = sys.argv[1], os.environ["REMOTE_OUTPUT"]
entries = []
for index, action, x, y, z in re.findall(r"^EMPTY_GRASP:(\d+):(true|false):([-0-9.]+),([-0-9.]+),([-0-9.]+)$", output, re.M):
    pose = [float(x), float(y), float(z)]
    in_bin = abs(pose[0] - .51) <= .17 and abs(pose[1] + .06) <= .17 and .47 <= pose[2] <= .56
    entries.append({"episode_id": f"p0-empty-grasp-{int(index):02d}", "failure_type": "empty_grasp", "injection": {"mode": "empty_grasp", "approach_seed": int(index)}, "arm_action_succeeded": action == "true", "final_cube_pose_xyz": pose, "task_success": False, "object_inside_bin": in_bin})
verified = len(entries) == 20 and all(item["arm_action_succeeded"] and not item["object_inside_bin"] for item in entries)
report = {"status": "VERIFIED_20_EMPTY_GRASP_FAILURE_TRAJECTORIES" if verified else "FAILED_FAILURE_TRAJECTORY_BATCH", "host": host, "count": len(entries), "entries": entries, "raw_output": output}
Path("reports/p0-empty-grasp-failures.json").write_text(json.dumps(report, indent=2) + "\n")
Path("data/episodes/p0-empty-grasp-failures.jsonl").write_text("".join(json.dumps(item) + "\n" for item in entries))
print(json.dumps({"status": report["status"], "count": len(entries)}))
PY
printf '%s\n' "$remote_output"
