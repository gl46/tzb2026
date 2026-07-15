#!/usr/bin/env bash
# S1 fails before motion if MoveIt and Gazebo do not use the same robot model.
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

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eu
root="$1"
cd "$HOME/$root"
printf 'REMOTE_GAZEBO_URDF_SHA256:'
sha256sum robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}'
if grep -q 'MoveItConfigsBuilder("moveit_resources_panda")' robot_ws/src/xh_sim/launch/moveit_planning_smoke.launch.py; then
  echo MOVEIT_MODEL_SOURCE:OFFICIAL_MOVEIT_RESOURCES_PANDA
fi
if grep -q 'panda_controlled.urdf' robot_ws/src/xh_sim/launch/moveit_planning_smoke.launch.py; then
  echo MOVEIT_MODEL_SOURCE:CONTROLLED_URDF
fi
REMOTE

python3 - "$RUN_ID" "$raw_log" "$local_sha" <<'PY'
import json, sys
from pathlib import Path
run_id, log, local_sha = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines() if line.startswith("REMOTE_GAZEBO_URDF_SHA256:")), None)
controlled = "MOVEIT_MODEL_SOURCE:CONTROLLED_URDF" in raw
official = "MOVEIT_MODEL_SOURCE:OFFICIAL_MOVEIT_RESOURCES_PANDA" in raw
model_match = controlled and remote_sha == local_sha
if model_match:
    status, reason = "PLAN_ONLY", "Model hashes match, but no MoveIt-to-Gazebo ExecuteTrajectory bridge has yet been demonstrated."
else:
    status, reason = "BLOCKED", "MoveIt is configured with the official Panda resource rather than the Gazebo-controlled panda_controlled.urdf; no unsafe S1 trajectory was dispatched."
data = {
    "run_id": run_id, "motion_status": status, "reason": reason,
    "local_gazebo_urdf_sha256": local_sha, "remote_gazebo_urdf_sha256": remote_sha,
    "moveit_uses_controlled_urdf": controlled, "moveit_uses_official_panda_resource": official,
    "model_match": model_match, "motion_trials": 0, "motion_successes": 0,
    "anti_teleport_verified_trials": 0, "controller_trajectory_dispatched": False,
    "raw_log": log,
}
Path("reports/m1a-motion-execution.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-motion-execution.md").write_text(
    "# M1A S1 MoveIt execution gate\n\n"
    f"- Status: `{status}`\n- Reason: {reason}\n"
    f"- Gazebo URDF sha256 (local/remote): `{local_sha}` / `{remote_sha}`\n"
    "- No controller trajectory is counted as MoveIt execution until the models and standard action chain are unified.\n"
)
PY
