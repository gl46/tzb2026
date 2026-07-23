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
if ! python3 - "$RUN_ID" "$local_sha" <<'PY'
import json
import sys
from pathlib import Path

run_id, local_sha = sys.argv[1:]
path = Path("reports/m1a-contact-calibration.json")
s0 = json.loads(path.read_text()) if path.exists() else {}
ready = (
    s0.get("status") in {"CONTACT_TELEMETRY_PARTIAL", "CONTACT_TELEMETRY_CALIBRATED"}
    and s0.get("model_match") is True
    and s0.get("local_gazebo_urdf_sha256") == local_sha
)
if not ready:
    data = {
        "run_id": run_id,
        "motion_status": "BLOCKED_S0_RUNTIME_EVIDENCE_REQUIRED",
        "reason": "S1 requires current-model S0 runtime evidence (PARTIAL or CALIBRATED), not historical reports.",
        "local_gazebo_urdf_sha256": local_sha,
        "remote_gazebo_urdf_sha256": None,
        "model_match": False,
        "motion_trials": 0,
        "motion_successes": 0,
        "anti_teleport_verified_trials": 0,
        "controller_trajectory_dispatched": False,
        "planning_scene_objects": ["work_table", "bin_a", "object_red_cube"],
        "enabled_collision_pairs": [],
        "srdf_adjacent_self_pairs": [],
        "adjacent_self_pairs_expected": [],
        "adjacent_self_pairs_audit": "NOT_RUN",
        "segments": [],
    }
    Path("reports/m1a-motion-execution.json").write_text(json.dumps(data, indent=2) + "\n")
    Path("reports/m1a-motion-execution.md").write_text(
        "# M1A S1 MoveIt execution gate\n\n"
        "- Status: `BLOCKED_S0_RUNTIME_EVIDENCE_REQUIRED`\n"
        "- Run at least one current-model S0 calibration condition first.\n"
    )
raise SystemExit(0 if ready else 1)
PY
then
  exit 2
fi
collision_audit="$(python3 - <<'PY'
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

expected = [
    ["panda_link0", "panda_link1"], ["panda_link1", "panda_link2"],
    ["panda_link2", "panda_link3"], ["panda_link3", "panda_link4"],
    ["panda_link4", "panda_link5"], ["panda_link5", "panda_link6"],
    ["panda_link6", "panda_link7"], ["panda_link7", "panda_link8"],
    ["panda_link8", "panda_hand"], ["panda_hand", "panda_leftfinger"],
    ["panda_hand", "panda_rightfinger"],
]
srdf = ET.parse('robot_ws/src/xh_sim/config/m1a_panda.srdf').getroot()
actual = [
    [entry.attrib['link1'], entry.attrib['link2']]
    for entry in srdf.findall('disable_collisions')
]
policy = yaml.safe_load(Path('robot_ws/src/xh_sim/config/m1a_collision_policy.yaml').read_text())
canonical = lambda pairs: sorted(tuple(sorted(pair)) for pair in pairs)
result = 'PASS_EXACT_MATCH_TO_ADJACENT_SELF_PAIRS' if canonical(actual) == canonical(expected) else 'FAIL_SRDF_ADJACENT_SELF_PAIR_MISMATCH'
print(json.dumps({
    'enabled_collision_pairs': policy['enabled_robot_world_collision_pairs'],
    'srdf_adjacent_self_pairs': actual,
    'adjacent_self_pairs_expected': expected,
    'adjacent_self_pairs_audit': result,
}))
PY
)"

if ! python3 - "$RUN_ID" "$local_sha" "$collision_audit" <<'PY'
import json
import sys
from pathlib import Path

run_id, local_sha, audit_json = sys.argv[1:]
audit = json.loads(audit_json)
if audit['adjacent_self_pairs_audit'] == 'PASS_EXACT_MATCH_TO_ADJACENT_SELF_PAIRS':
    raise SystemExit(0)
data = {
    'run_id': run_id,
    'motion_status': 'BLOCKED_SRDF_ADJACENT_SELF_PAIR_AUDIT',
    'reason': 'S1 cannot run until SRDF disabled self-pairs exactly match ADJACENT_SELF_PAIRS.',
    'local_gazebo_urdf_sha256': local_sha,
    'remote_gazebo_urdf_sha256': None,
    'model_match': False,
    'motion_trials': 0,
    'motion_successes': 0,
    'anti_teleport_verified_trials': 0,
    'controller_trajectory_dispatched': False,
    'planning_scene_objects': ['work_table', 'bin_a', 'object_red_cube'],
    'segments': [],
    **audit,
}
Path('reports/m1a-motion-execution.json').write_text(json.dumps(data, indent=2) + '\n')
Path('reports/m1a-motion-execution.md').write_text(
    '# M1A S1 MoveIt execution gate\n\n'
    '- Status: `BLOCKED_SRDF_ADJACENT_SELF_PAIR_AUDIT`\n'
    f"- Audit: `{audit['adjacent_self_pairs_audit']}`\n"
)
raise SystemExit(1)
PY
then
  exit 2
fi

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
source /opt/ros/jazzy/setup.bash
source "$HOME/$root/robot_ws/install/setup.bash"
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then echo M1A_REMOTE_SIM_ALREADY_RUNNING; exit 0; fi
tmp=$(mktemp -d); launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py >"$launch_log" 2>&1 & pid=$!
launch_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
cleanup(){ kill -TERM -- "-$launch_pgid" 2>/dev/null || true; sleep 1; kill -KILL -- "-$launch_pgid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -f "$launch_log"; rmdir "$tmp" 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM
sleep 15
echo "M1A_S1_LAUNCH_PID:$pid"
echo "M1A_S1_LAUNCH_PGID:$launch_pgid"
printf 'REMOTE_GAZEBO_URDF_SHA256:'; sha256sum "$HOME/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf" | awk '{print $1}'
if ! kill -0 "$pid" 2>/dev/null; then echo M1A_S1_LAUNCH_FAILED; sed -n '1,220p' "$launch_log"; exit 0; fi
controller_action_ready=false
for _ in $(seq 1 60); do
  if ros2 control list_controllers 2>/dev/null | grep -q '^panda_arm_controller.*active' \
    && ros2 action list 2>/dev/null | grep -qx '/panda_arm_controller/follow_joint_trajectory'; then
    controller_action_ready=true
    break
  fi
  sleep 1
done
echo "M1A_S1_CONTROLLER_ACTION_READY:$controller_action_ready"
if [ "$controller_action_ready" != true ]; then
  echo M1A_S1_CONTROLLER_ACTION_UNAVAILABLE
  tail -n 160 "$launch_log"
  exit 0
fi
python3 "$HOME/$root/scripts/m1a_moveit_execution_client.py"
echo M1A_S1_LAUNCH_TAIL
tail -n 160 "$launch_log"
REMOTE

python3 - "$RUN_ID" "$raw_log" "$local_sha" "$collision_audit" <<'PY'
import json, sys
from pathlib import Path
run_id, log, local_sha, audit_json = sys.argv[1:]
audit = json.loads(audit_json)
raw = Path(log).read_text(errors="replace")
remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines() if line.startswith("REMOTE_GAZEBO_URDF_SHA256:")), None)
runtime = next((json.loads(line) for line in raw.splitlines() if line.startswith("{") and '"segments"' in line), None)
if runtime is None:
    status = "BLOCKED"
    reason = (
        "panda_arm_controller FollowJointTrajectory action server did not become ready."
        if "M1A_S1_CONTROLLER_ACTION_UNAVAILABLE" in raw
        else "No structured MoveIt execution evidence returned."
    )
    trials, successes, segments = 0, 0, []
else:
    status = runtime["status"]
    reason = f"{runtime['successful_trials']}/10 three-segment MoveIt trials passed all recorded gates."
    trials, successes = 10, runtime["successful_trials"]
    segments = []
    for segment in runtime["segments"]:
        summary = {key: value for key, value in segment.items() if key not in {"samples", "controller_samples"}}
        summary["joint_state_sample_excerpt"] = [
            segment["samples"][index] for index in (0, -1) if segment.get("samples")
        ]
        summary["controller_state_sample_excerpt"] = [
            segment["controller_samples"][index]
            for index in (0, -1)
            if segment.get("controller_samples")
        ]
        segments.append(summary)
data = {
    "run_id": run_id, "motion_status": status, "reason": reason,
    "local_gazebo_urdf_sha256": local_sha, "remote_gazebo_urdf_sha256": remote_sha,
    "moveit_uses_controlled_urdf": True, "moveit_uses_official_panda_resource": False,
    "model_match": remote_sha == local_sha, "motion_trials": trials, "motion_successes": successes,
    "anti_teleport_verified_trials": successes, "controller_trajectory_dispatched": any(s.get("dispatched") for s in segments),
    "planning_scene_objects": ["work_table", "bin_a", "object_red_cube"],
    "enabled_collision_pairs": audit["enabled_collision_pairs"],
    "srdf_adjacent_self_pairs": audit["srdf_adjacent_self_pairs"],
    "adjacent_self_pairs_expected": audit["adjacent_self_pairs_expected"],
    "adjacent_self_pairs_audit": audit["adjacent_self_pairs_audit"],
    "segments": segments, "raw_log": log,
}
Path("reports/m1a-motion-execution.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-motion-execution.md").write_text(
    "# M1A S1 MoveIt execution gate\n\n"
    f"- Status: `{status}`\n- Reason: {reason}\n- Same URDF sha256: `{local_sha}` / `{remote_sha}`\n"
    f"- Enabled robot/world collision pairs: `{data['enabled_collision_pairs']}`\n"
    f"- SRDF adjacent self-pairs: `{data['srdf_adjacent_self_pairs']}`\n"
    f"- ADJACENT_SELF_PAIRS audit: `{data['adjacent_self_pairs_audit']}`\n"
)
PY
