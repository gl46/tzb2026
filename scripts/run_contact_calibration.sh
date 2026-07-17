#!/usr/bin/env bash
# S0: runtime-oracle geometry -> MoveIt -> controllers -> per-trial contacts/FK.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
CALIBRATION_SCOPE="${M1A_CALIBRATION_SCOPE:-full}"
CALIBRATION_REPETITION="${M1A_CALIBRATION_REPETITION:-1}"
CALIBRATION_LABEL="${M1A_CALIBRATION_LABEL:-}"
mkdir -p logs reports
raw_log="logs/${RUN_ID}-s0-contact-calibration.log"
local_sha="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"
local_generator_sha="$(shasum -a 256 robot_ws/src/xh_sim/scripts/generate_panda_spawn_sdf.py | awk '{print $1}')"

# ADR-0009's current five-gate audit contains the action-level physical-mimic
# proof (GATE2).  The former DART-era static log check is historical evidence,
# not a second authority: it cannot observe the now-required q1
# ``mimic=\"false\"`` ros2_control opt-out.
if ! python3 - "$RUN_ID" "$local_sha" "$local_generator_sha" <<'PY'
import json
import sys
from pathlib import Path

run_id, local_sha, local_generator_sha = sys.argv[1:]
bullet_path = Path("reports/m1a-bullet-capability-audit.json")
bullet = json.loads(bullet_path.read_text()) if bullet_path.exists() else {}
valid = (
    bullet.get("status") == "M1A_BULLET_CAPABILITY_VERIFIED"
    and bullet.get("local_gazebo_urdf_sha256") == local_sha
    and bullet.get("generated_manifest", {}).get("hashes", {}).get("generator_sha256") == local_generator_sha
    and bullet.get("gates", {}).get("physical_mimic") is True
    and bullet.get("hand_probe", {}).get("controls_verified") is True
)
if not valid:
    payload = {
        "run_id": run_id,
        "status": "CONTACT_TELEMETRY_BLOCKED_BULLET_CAPABILITY_AUDIT",
        "reason": "ADR-0009 requires the current five-gate Bullet capability audit before S0.",
        "physical_mimic_gate": bullet.get("hand_probe", {}),
        "bullet_capability_audit": bullet,
        "local_generator_sha256": local_generator_sha,
        "trials": [],
    }
    Path("reports/m1a-contact-calibration.json").write_text(json.dumps(payload, indent=2) + "\n")
    Path("reports/m1a-contact-calibration.md").write_text(
        "# M1A S0 contact telemetry calibration\n\n"
        "- Status: `CONTACT_TELEMETRY_BLOCKED_BULLET_CAPABILITY_AUDIT`\n"
        "- Run the current five-gate Bullet capability audit and resolve its result before S0.\n"
    )
raise SystemExit(0 if valid else 1)
PY
then
  exit 2
fi

# ADR-0006 requires a same-URDF, MoveIt-checked home state before any new S0
# session can consume simulation time. A historical S0 cannot satisfy this.
if ! python3 - "$RUN_ID" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

run_id = sys.argv[1]
report_path = Path("reports/m1a-home-self-collision.json")
urdf_path = Path("robot_ws/src/xh_sim/urdf/panda_controlled.urdf")
data = json.loads(report_path.read_text()) if report_path.exists() else {}
valid = (
    data.get("status") == "HOME_SELF_COLLISION_VERIFIED"
    and data.get("model_match") is True
    and data.get("local_gazebo_urdf_sha256") == hashlib.sha256(urdf_path.read_bytes()).hexdigest()
)
if not valid:
    payload = {
        "run_id": run_id,
        "status": "CONTACT_TELEMETRY_BLOCKED_HOME_SELF_COLLISION_GATE",
        "reason": "ADR-0006 requires a current same-URDF HOME_SELF_COLLISION_VERIFIED report before S0.",
        "home_gate": data,
        "trials": [],
    }
    Path("reports/m1a-contact-calibration.json").write_text(json.dumps(payload, indent=2) + "\n")
    Path("reports/m1a-contact-calibration.md").write_text(
        "# M1A S0 contact telemetry calibration\n\n"
        "- Status: `CONTACT_TELEMETRY_BLOCKED_HOME_SELF_COLLISION_GATE`\n"
        "- Run `scripts/run_m1a_home_self_collision_check.sh` against the current URDF first.\n"
    )
raise SystemExit(0 if valid else 1)
PY
then
  exit 2
fi

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT' '$CALIBRATION_SCOPE' '$CALIBRATION_REPETITION' '$CALIBRATION_LABEL'" >"$raw_log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
scope="$2"
repetition="$3"
label="$4"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
set -u
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_REMOTE_SIM_ALREADY_RUNNING
  exit 0
fi
tmp=$(mktemp -d)
calibration_world="/home/$USER/$root/robot_ws/install/xh_sim/share/xh_sim/worlds/m1a_contact_calibration.sdf"
pid=""; launch_pgid=""; launch_log=""
stop_session() {
  if [ -n "$launch_pgid" ]; then
    kill -TERM -- "-$launch_pgid" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-$launch_pgid" 2>/dev/null || true
  fi
  [ -z "$pid" ] || wait "$pid" 2>/dev/null || true
  pid=""; launch_pgid=""
}
cleanup() { stop_session; rm -rf "$tmp"; }
trap cleanup EXIT HUP INT TERM
start_session() {
  local session_label="$1"
  launch_log="$tmp/${session_label}.launch.log"
  setsid ros2 launch xh_sim moveit_execution.launch.py world_file:="$calibration_world" calibration_mode:=true >"$launch_log" 2>&1 & pid=$!
  launch_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  sleep 15
  echo "M1A_S0_LAUNCH_LABEL:$session_label"
  echo "M1A_S0_LAUNCH_PGID:$launch_pgid"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "M1A_S0_LAUNCH_FAILED:$session_label"
    sed -n '1,220p' "$launch_log"
    return 1
  fi
  return 0
}
run_isolated_label() {
  local trial_label="$1" output runtime
  if ! start_session "$trial_label"; then
    printf 'M1A_S0_TRIAL:%s:{"status":"CONTACT_TELEMETRY_BLOCKED","trials":[]}\n' "$trial_label"
    stop_session
    return
  fi
  output="$(M1A_CALIBRATION_SCOPE=one M1A_CALIBRATION_LABEL="$trial_label" python3 "/home/$USER/$root/scripts/m1a_contact_calibration_client.py" 2>&1 || true)"
  runtime="$(printf '%s\n' "$output" | tail -n 1)"
  printf 'M1A_S0_TRIAL:%s:%s\n' "$trial_label" "$runtime"
  stop_session
}
printf 'REMOTE_GAZEBO_URDF_SHA256:'
sha256sum "/home/$USER/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf" | awk '{print $1}'
if [ "$scope" = full ]; then
  # A label is a calibration experiment.  It must not inherit the preceding
  # label's arm pose, contact force, cube state, or topic history.
  for trial_label in left_1 left_2 left_3 right_1 right_2 right_3 bilateral_1 bilateral_2 bilateral_3 object_environment_1 object_environment_2 table_1 table_2; do
    run_isolated_label "$trial_label"
  done
else
  start_session "${scope}_${label:-$repetition}" || exit 0
  M1A_CALIBRATION_SCOPE="$scope" M1A_CALIBRATION_REPETITION="$repetition" M1A_CALIBRATION_LABEL="$label" \
    python3 "/home/$USER/$root/scripts/m1a_contact_calibration_client.py"
fi
REMOTE

python3 - "$RUN_ID" "$raw_log" "$local_sha" <<'PY'
import json
import sys
from pathlib import Path

run_id, log, local_sha = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines()
                   if line.startswith("REMOTE_GAZEBO_URDF_SHA256:")), None)
isolated = []
for line in raw.splitlines():
    if not line.startswith("M1A_S0_TRIAL:"):
        continue
    _, trial_label, payload = line.split(":", 2)
    try:
        evidence = json.loads(payload)
    except json.JSONDecodeError:
        continue
    trial = next((item for item in evidence.get("trials", []) if item.get("label") == trial_label), None)
    if trial is not None:
        trial["isolation"] = {"fresh_simulation_session": True, "label": trial_label}
        isolated.append(trial)
runtime = next(
    (json.loads(line) for line in raw.splitlines() if line.startswith("{") and '"trials"' in line),
    None,
)
if isolated:
    status = "CONTACT_TELEMETRY_CALIBRATED" if len(isolated) == 13 and all(
        item.get("passed") is True for item in isolated
    ) else "CONTACT_TELEMETRY_PARTIAL"
    reason = f"{sum(item.get('passed') is True for item in isolated)}/13 independently reset approved conditions passed."
    data = {
        "run_id": run_id, "status": status, "reason": reason, "trials": isolated,
        "oracle_pose_source": "gz model runtime query before every isolated label",
        "calibration_initialization": "CALIBRATION_ONLY_INITIALIZATION_PER_LABEL",
        "target_policy": "STATIC_SINGLE_PAD_AND_FREE_DYNAMIC_BILATERAL",
    }
elif runtime is None:
    status = "CONTACT_TELEMETRY_BLOCKED"
    if "M1A_REMOTE_SIM_ALREADY_RUNNING" in raw:
        reason = "A pre-existing simulation was running; the bounded calibration did not attach to it."
    elif "M1A_S0_LAUNCH_FAILED" in raw:
        reason = "The bounded MoveIt/Gazebo calibration launch did not remain alive."
    else:
        reason = "No structured runtime-oracle contact calibration evidence returned."
    data = {"run_id": run_id, "status": status, "reason": reason, "raw_log": log, "trials": []}
else:
    data = {"run_id": run_id, **runtime, "raw_log": log}
    status, reason = data["status"], data["reason"]
data.update(
    {
        "minimum_contact_rate_hz": 20.0,
        "required_overlap_s": 0.1,
        "required_consecutive_samples": 3,
        "calibration_trials_completed": (
            len(data.get("trials", [])) if isolated else max(0, len(data.get("trials", [])) - 1)
        ),
        "use_sim_time": True,
        "listener_scope": "PER_TRIAL_FULL_ACTION_WINDOW",
        "local_gazebo_urdf_sha256": local_sha,
        "remote_gazebo_urdf_sha256": remote_sha,
        "model_match": remote_sha == local_sha,
    }
)
Path("reports/m1a-contact-calibration.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-calibration.md").write_text(
    "# M1A S0 contact telemetry calibration\n\n"
    f"- Status: `{status}`\n- Reason: {reason}\n"
    f"- Runtime oracle pose source: `{data.get('oracle_pose_source')}`\n"
    f"- Completed condition trials: `{data['calibration_trials_completed']}/13`\n"
    "- Every motion trial records cube pose, MoveIt/IK result, finger action, pad FK, minimum AABB separation, and raw contact pairs.\n"
    "- Full S0 runs reset Gazebo and the calibration target before every labelled condition.\n"
    "- No grasp is claimed by this calibration audit.\n"
)
PY
