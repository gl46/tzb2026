#!/usr/bin/env bash
# ADR-0008 physical-layer audit. This never sends an arm or hand action.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_HAND_MIMIC_AUDIT_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-hand-mimic-physical-audit.log"
local_sha="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" \
  "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_HAND_MIMIC_AUDIT_PREEXISTING_SIM
  exit 0
fi
tmp=$(mktemp -d)
launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=false >"$launch_log" 2>&1 & pid=$!
launch_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
cleanup() {
  kill -TERM -- "-$launch_pgid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$launch_pgid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM
sleep 20
echo "M1A_HAND_MIMIC_AUDIT_SOURCE_URDF_SHA256:$(sha256sum "/home/$USER/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf" | awk '{print $1}')"
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_HAND_MIMIC_AUDIT_LAUNCH_FAILED
  sed -n '1,260p' "$launch_log"
  exit 0
fi
echo M1A_HAND_MIMIC_AUDIT_LAUNCH_STARTED
ros2 control list_hardware_interfaces 2>&1 || true
if grep -q "Joint 'panda_finger_joint1'is mimicking joint 'panda_finger_joint2'" "$launch_log"; then
  echo M1A_HAND_MIMIC_DECLARATION_LOADED
fi
if grep -q 'does not support mimic constraints, so no constraint will be created' "$launch_log"; then
  echo M1A_HAND_MIMIC_PHYSICAL_CONSTRAINT_DECLINED
else
  echo M1A_HAND_MIMIC_PHYSICAL_CONSTRAINT_NOT_DECLINED
fi
grep -E 'mimic constraint|is mimicking joint' "$launch_log" || true
REMOTE

python3 - "$RUN_ID" "$raw_log" "$local_sha" <<'PY'
import json
import re
import sys
from pathlib import Path

run_id, raw_log, local_sha = sys.argv[1:]
raw = Path(raw_log).read_text(errors="replace")
normalized = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines()
                   if line.startswith("M1A_HAND_MIMIC_AUDIT_SOURCE_URDF_SHA256:")), None)
q1_command = "panda_finger_joint1/position [available] [claimed]" in raw
q2_command = "panda_finger_joint2/position [available] [claimed]" in raw
q1_state = "panda_finger_joint1/position" in raw
q2_state = "panda_finger_joint2/position" in raw
physical_declined = (
    "M1A_HAND_MIMIC_PHYSICAL_CONSTRAINT_DECLINED" in raw
    or "does not support mimic constraints, so no constraint will be created" in normalized
)
status = (
    "HAND_MIMIC_PHYSICAL_CONSTRAINT_VERIFIED"
    if (
        "M1A_HAND_MIMIC_PHYSICAL_CONSTRAINT_NOT_DECLINED" in raw
        and "is mimicking joint 'panda_finger_joint2'" in normalized
        and not q1_command and q2_command and q1_state and q2_state
        and remote_sha == local_sha
    ) else "HAND_MIMIC_PHYSICAL_CONSTRAINT_BLOCKED"
)
data = {
    "run_id": run_id,
    "status": status,
    "reason": (
        "The installed DART plugin declined the SDF mimic constraint. "
        "Controller-side mirroring is retained as evidence but is not a physical-SDF substitute."
        if physical_declined else "The full generated-SDF physical-mimic acceptance set was not observed."
    ),
    "local_gazebo_urdf_sha256": local_sha,
    "remote_gazebo_urdf_sha256": remote_sha,
    "model_match": remote_sha == local_sha,
    "master_joint": "panda_finger_joint2",
    "follower_joint": "panda_finger_joint1",
    "sdf_mimic_declaration_loaded": "is mimicking joint 'panda_finger_joint2'" in normalized,
    "sdf_mimic_physical_constraint_declined": physical_declined,
    "hardware_interfaces": {
        "q1_position_command_exported": q1_command,
        "q2_position_command_exported": q2_command,
        "q1_position_state_exported": q1_state,
        "q2_position_state_exported": q2_state,
    },
    "joint_states_double_report_verified_by": "m1a-hand-actuation-probe.json q2-master no-contact probe",
    "raw_log": raw_log,
}
Path("reports/m1a-hand-mimic-physical-audit.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-hand-mimic-physical-audit.md").write_text(
    "# M1A hand physical-mimic audit\n\n"
    f"- Status: `{status}`\n- Reason: {data['reason']}\n"
    f"- SHA-256 local / remote: `{local_sha}` / `{remote_sha}`\n"
    f"- q1 command / q2 command interfaces: `{q1_command}` / `{q2_command}`\n"
    f"- q1 state / q2 state interfaces: `{q1_state}` / `{q2_state}`\n"
    f"- Raw log: `{raw_log}`\n"
    "- S0 is blocked unless this audit is `HAND_MIMIC_PHYSICAL_CONSTRAINT_VERIFIED`.\n"
)
print(json.dumps({"status": status, "physical_constraint_declined": physical_declined}))
PY
