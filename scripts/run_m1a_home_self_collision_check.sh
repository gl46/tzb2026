#!/usr/bin/env bash
# Required ADR-0006 pre-S0 gate: query MoveIt's collision model without motion.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-home-self-collision.log"
local_sha="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
source /opt/ros/jazzy/setup.bash
source "$HOME/$root/robot_ws/install/setup.bash"
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_REMOTE_SIM_ALREADY_RUNNING
  exit 0
fi
tmp=$(mktemp -d)
launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py >"$launch_log" 2>&1 & pid=$!
cleanup(){
  kill -TERM -- "-$pid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
sleep 15
printf 'REMOTE_GAZEBO_URDF_SHA256:'
sha256sum "$HOME/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf" | awk '{print $1}'
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_HOME_GATE_LAUNCH_FAILED
  sed -n '1,220p' "$launch_log"
  exit 0
fi
python3 "$HOME/$root/scripts/m1a_home_self_collision_client.py"
echo M1A_HOME_GATE_LAUNCH_TAIL
tail -n 160 "$launch_log"
REMOTE

python3 - "$RUN_ID" "$raw_log" "$local_sha" <<'PY'
import json
import sys
import time
from pathlib import Path

run_id, raw_log, local_sha = sys.argv[1:]
raw = Path(raw_log).read_text(errors="replace")
remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines()
                   if line.startswith("REMOTE_GAZEBO_URDF_SHA256:")), None)
runtime = next((json.loads(line) for line in raw.splitlines()
                if line.startswith("{") and '"HOME_SELF_COLLISION_' in line), None)
if runtime is None:
    status = "HOME_SELF_COLLISION_BLOCKED"
    reason = "No structured check_state_validity response returned."
else:
    status = runtime["status"]
    reason = "MoveIt reports the approved home state as collision-free." if runtime.get("valid") else "MoveIt rejected the approved home state."
data = {
    "run_id": run_id,
    "status": status,
    "reason": reason,
    "started_at_unix_s": time.time(),
    "local_gazebo_urdf_sha256": local_sha,
    "remote_gazebo_urdf_sha256": remote_sha,
    "model_match": local_sha == remote_sha,
    "runtime": runtime,
    "raw_log": raw_log,
    "next_gate": "S0_ONLY_IF_HOME_SELF_COLLISION_VERIFIED_AND_MODEL_MATCH",
}
Path("reports/m1a-home-self-collision.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-home-self-collision.md").write_text(
    "# M1A approved-model home self-collision gate\n\n"
    f"- Status: `{status}`\n- {reason}\n"
    f"- Same URDF SHA-256: `{local_sha}` / `{remote_sha}`\n"
    "- Method: MoveIt `check_state_validity`, with no motion command.\n"
    "- Changed files: no source files; this is runtime evidence for the approved URDF/SRDF.\n"
    "- Tests: same-URDF hash comparison and `panda_arm` state-validity query at the SRDF home posture.\n"
    "- Failures: see the immutable run-specific raw log; a non-verified result blocks S0.\n"
    f"- Blocker: `{'NONE' if status == 'HOME_SELF_COLLISION_VERIFIED' and local_sha == remote_sha else 'HOME_SELF_COLLISION_GATE_NOT_SATISFIED'}`.\n"
    f"- Next command: `{'scripts/run_isolated_contact_calibration.sh' if status == 'HOME_SELF_COLLISION_VERIFIED' and local_sha == remote_sha else 'fix the reported collision or model mismatch, then rerun this gate'}`.\n"
)
PY
