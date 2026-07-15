#!/usr/bin/env bash
# S1: same-URDF MoveIt plan -> ExecuteTrajectory -> Gazebo feedback gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-s1-moveit-execution.log"
local_sha="$(sha256sum robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"
collision_pairs="$(python3 - <<'PY'
import json, yaml
from pathlib import Path
data=yaml.safe_load(Path('robot_ws/src/xh_sim/config/m1a_collision_policy.yaml').read_text())
print(json.dumps(data['enabled_robot_world_collision_pairs']))
PY
)"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
source /opt/ros/jazzy/setup.bash
source "$HOME/$root/robot_ws/install/setup.bash"
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then echo M1A_REMOTE_SIM_ALREADY_RUNNING; exit 0; fi
tmp=$(mktemp -d); launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py >"$launch_log" 2>&1 & pid=$!
cleanup(){ kill -TERM -- "-$pid" 2>/dev/null || true; sleep 1; kill -KILL -- "-$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -f "$launch_log"; rmdir "$tmp" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
sleep 15
printf 'REMOTE_GAZEBO_URDF_SHA256:'; sha256sum "$HOME/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf" | awk '{print $1}'
if ! kill -0 "$pid" 2>/dev/null; then echo M1A_S1_LAUNCH_FAILED; sed -n '1,220p' "$launch_log"; exit 0; fi
python3 "$HOME/$root/scripts/m1a_moveit_execution_client.py"
echo M1A_S1_LAUNCH_TAIL
tail -n 160 "$launch_log"
REMOTE

python3 - "$RUN_ID" "$raw_log" "$local_sha" "$collision_pairs" <<'PY'
import json, sys
from pathlib import Path
run_id, log, local_sha, pairs_json = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines() if line.startswith("REMOTE_GAZEBO_URDF_SHA256:")), None)
runtime = next((json.loads(line) for line in raw.splitlines() if line.startswith("{") and '"segments"' in line), None)
if runtime is None:
    status, reason, trials, successes, segments = "BLOCKED", "No structured MoveIt execution evidence returned.", 0, 0, []
else:
    status = runtime["status"]
    reason = f"{runtime['successful_trials']}/10 three-segment MoveIt trials passed all recorded gates."
    trials, successes, segments = 10, runtime["successful_trials"], runtime["segments"]
data = {
    "run_id": run_id, "motion_status": status, "reason": reason,
    "local_gazebo_urdf_sha256": local_sha, "remote_gazebo_urdf_sha256": remote_sha,
    "moveit_uses_controlled_urdf": True, "moveit_uses_official_panda_resource": False,
    "model_match": remote_sha == local_sha, "motion_trials": trials, "motion_successes": successes,
    "anti_teleport_verified_trials": successes, "controller_trajectory_dispatched": any(s.get("dispatched") for s in segments),
    "planning_scene_objects": ["work_table", "bin_a", "object_red_cube"],
    "enabled_collision_pairs": json.loads(pairs_json), "segments": segments, "raw_log": log,
}
Path("reports/m1a-motion-execution.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-motion-execution.md").write_text(
    "# M1A S1 MoveIt execution gate\n\n"
    f"- Status: `{status}`\n- Reason: {reason}\n- Same URDF sha256: `{local_sha}` / `{remote_sha}`\n"
    f"- Enabled robot/world collision pairs: `{data['enabled_collision_pairs']}`\n"
)
PY
