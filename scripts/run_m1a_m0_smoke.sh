#!/usr/bin/env bash
# A bounded M0 control/perception recheck that writes only new M1A evidence.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-m0-smoke.log"

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
action_log="$tmp/action.log"
probe_log="$tmp/probe.log"
setsid ros2 launch xh_bringup bringup.launch.py headless:=true >"$launch_log" 2>&1 & pid=$!
cleanup() {
  kill -TERM -- "-$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log" "$action_log" "$probe_log"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
sleep 12
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_M0_LAUNCH_FAILED
  sed -n '1,160p' "$launch_log"
  exit 0
fi
echo M1A_M0_LAUNCH_STARTED
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then echo M0_WORLD_SERVICE; fi
controllers="$(timeout -k 1 6 ros2 control list_controllers 2>&1 || true)"
for controller in joint_state_broadcaster panda_arm_controller panda_hand_controller; do
  if grep -Eq "^${controller}[[:space:]].*[[:space:]]active$" <<<"$controllers"; then echo "M0_CONTROLLER_ACTIVE:$controller"; fi
done
if grep -Eq '^panda_arm_controller[[:space:]].*[[:space:]]active$' <<<"$controllers"; then
  timeout -k 2 18 ros2 action send_goal /panda_arm_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
    '{trajectory: {joint_names: [panda_joint1, panda_joint2, panda_joint3, panda_joint4, panda_joint5, panda_joint6, panda_joint7], points: [{positions: [0.12, -0.25, 0.15, -0.20, 0.10, 0.15, -0.10], time_from_start: {sec: 3}}]}}' >"$action_log" 2>&1 || true
  if grep -q 'Goal finished with status: SUCCEEDED' "$action_log"; then echo M0_ARM_ACTION_SUCCEEDED; fi
fi
timeout -k 1 6 ros2 topic echo --once /joint_states >"$probe_log" 2>&1 || true
if grep -q 'panda_joint1' "$probe_log"; then echo M0_JOINT_STATES; fi
REMOTE

python3 - "$RUN_ID" "$raw_log" <<'PY'
import json, sys
from pathlib import Path
run_id, log = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
world = "M0_WORLD_SERVICE" in raw
arm = "M0_ARM_ACTION_SUCCEEDED" in raw
joints = "M0_JOINT_STATES" in raw
controllers = all(f"M0_CONTROLLER_ACTIVE:{name}" in raw for name in ("joint_state_broadcaster", "panda_arm_controller", "panda_hand_controller"))
blocked = any(marker in raw for marker in ("M1A_REMOTE_SIM_ALREADY_RUNNING", "M1A_M0_LAUNCH_FAILED"))
status = "PARTIAL_CONTROL_AND_PERCEPTION_VERIFIED" if world and controllers and arm and joints and not blocked else "BLOCKED_M0_SMOKE"
data = {"run_id": run_id, "status": status, "world_service": world, "controllers_active": controllers,
        "arm_action_succeeded": arm, "joint_states_received": joints, "m0_constrained_transfer_reproduced": False,
        "episode_recorded": False, "raw_log": log,
        "reason": "This M1A preflight rechecked controller-backed M0 smoke only; it did not rerun or overwrite the protected constrained-transfer episode."}
Path("reports/m1a-m0-smoke.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-m0-smoke.md").write_text(
    "# M1A bounded M0 smoke\n\n"
    f"- Status: `{status}`\n- World/controllers/arm/joint states: `{world}` / `{controllers}` / `{arm}` / `{joints}`\n"
    "- The protected M0 constrained-transfer evidence was not overwritten.\n"
)
PY
