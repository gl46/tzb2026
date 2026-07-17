#!/usr/bin/env bash
# S2: bounded, unconstrained friction trials; no attach request is permitted.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
local_sha="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"
stage_started_epoch="$(date +%s)"

if ! python3 - "$RUN_ID" "$local_sha" <<'PY'
import json
import os
import sys
from pathlib import Path

run_id, local_sha = sys.argv[1:]
def load(name):
    path = Path("reports") / name
    return json.loads(path.read_text()) if path.exists() else {}
s0, s1 = load("m1a-contact-calibration.json"), load("m1a-motion-execution.json")
ready = (
    s0.get("status") == "CONTACT_TELEMETRY_CALIBRATED"
    and s0.get("model_match") is True
    and s0.get("local_gazebo_urdf_sha256") == local_sha
    and s1.get("motion_status") == "VERIFIED_MOVEIT_EXECUTION"
    and s1.get("model_match") is True
    and s1.get("local_gazebo_urdf_sha256") == local_sha
)
if not ready:
    data = {
        "status": "FRICTION_TRIALS_BLOCKED_REVALIDATION_REQUIRED",
        "run_id": run_id,
        "frictional_trials": 0,
        "frictional_successes": 0,
        "failure_counts": {},
        "trials": [],
        "detachable_joint_used": False,
        "early_stop": False,
        "reason": "S2 requires current-model calibrated S0 and verified S1 evidence.",
        "local_gazebo_urdf_sha256": local_sha,
    }
    Path("reports/m1a-friction-trials.json").write_text(json.dumps(data, indent=2) + "\n")
    Path("reports/m1a-friction-trials.md").write_text(
        "# M1A S2 friction trials\n\n- Status: `FRICTION_TRIALS_BLOCKED_REVALIDATION_REQUIRED`\n"
    )
raise SystemExit(0 if ready else 1)
PY
then
  exit 2
fi

# ADR-0007/0008/0009 explicitly authorize a fresh 3×5 S2 allocation after the
# repaired actuation SHA has passed GATE1–5, S0, and S1.  Older-SHA trials are
# retained as history but cannot consume this new, provenance-bound window.
read -r prior_count remaining_attempts < <(python3 - "$local_sha" <<'PY'
import json
import sys
from pathlib import Path

path = Path("reports/m1a-friction-trials.json")
if not path.exists():
    print("0 15")
    raise SystemExit(0)
report = json.loads(path.read_text())
all_trials = report.get("trials", [])
trials = [trial for trial in all_trials if trial.get("diagnostic_subclass") != "RUNTIME_EVIDENCE_MISSING"]
if trials and report.get("local_gazebo_urdf_sha256") != sys.argv[1]:
    print("0 15")
    raise SystemExit(0)
if len(trials) > 15:
    raise SystemExit("existing S2 report already exceeds the hard cap")
print(len(trials), 15 - len(trials))
PY
)
if (( remaining_attempts == 0 )); then
  if [[ "${M1A_S2_RECONCILE_ONLY:-0}" != "1" ]]; then
    echo "S2_CAP_ALREADY_CONSUMED:$prior_count"
    exit 0
  fi
fi
continuation_attempts="${M1A_S2_CONTINUATION_ATTEMPT_LIMIT:-$remaining_attempts}"
if [[ "${M1A_S2_RECONCILE_ONLY:-0}" == "1" ]]; then
  continuation_attempts=0
fi
if ! [[ "$continuation_attempts" =~ ^[0-9]+$ ]] || (( continuation_attempts > remaining_attempts )); then
  echo "M1A_S2_INVALID_CONTINUATION_ATTEMPT_LIMIT:$continuation_attempts/$remaining_attempts" >&2
  exit 2
fi

config_json="$(python3 - <<'PY'
import json
from pathlib import Path
import yaml

data = yaml.safe_load(Path("configs/m1a_friction_trials.yaml").read_text())
config = dict(data["orientation_recovery_configuration"])
config["grasp_orientation_families"] = data["grasp_orientation_families"]
print(json.dumps(config, separators=(",", ":")))
PY
)"
declare -a logs=()
new_approach_failures=0
early_stop_reason=""
if (( continuation_attempts > 0 )); then
for attempt in $(seq 1 "$continuation_attempts"); do
  # Continue the approved candidate sequence across invocations; otherwise a
  # bounded retry would silently repeat candidate 1 and waste the new-SHA cap.
  candidate_sequence_index=$((prior_count + attempt))
  attempt_config_json="$(python3 - "$config_json" "$candidate_sequence_index" <<'PY'
import json
import sys

config = json.loads(sys.argv[1])
attempt = int(sys.argv[2])
candidates = [
    candidate for candidate in config["grasp_orientation_families"]["candidates"]
    if "minimum_target_center_above_table_m" not in candidate
]
config["preferred_candidate_id"] = candidates[(attempt - 1) % len(candidates)]["id"]
print(json.dumps(config, separators=(",", ":")))
PY
)"
  config_b64="$(printf '%s' "$attempt_config_json" | base64 | tr -d '\n')"
  log="logs/${RUN_ID}-s2-orientation-recovery-${attempt}.log"
  logs+=("$log")
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "bash -s -- '$PROJECT_REMOTE_ROOT' '$config_b64'" >"$log" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
config_json="$(printf '%s' "$2" | base64 -d)"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
set -u
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_REMOTE_SIM_ALREADY_RUNNING
  exit 0
fi
tmp="$(mktemp -d)"
launch_log="$tmp/launch.log"
base_world="/home/$USER/$root/robot_ws/install/xh_sim/share/xh_sim/worlds/p0_pick_place.sdf"
configured_world="$tmp/s2-configured-world.sdf"
python3 - "$base_world" "$configured_world" "$config_json" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET

base, output, config_json = sys.argv[1:]
config = json.loads(config_json)
tree = ET.parse(base)
cube = tree.find(".//model[@name='object_red_cube']")
mass = cube.find("./link/inertial/mass") if cube is not None else None
if mass is None:
    raise SystemExit("S2 cube mass element not found")
mass.text = str(config["object_mass_kg"])
tree.write(output, encoding="unicode")
PY
world_sha="$(sha256sum "$configured_world" | awk '{print $1}')"
setsid ros2 launch xh_sim moveit_execution.launch.py world_file:="$configured_world" calibration_mode:=true >"$launch_log" 2>&1 & pid=$!
launch_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
cleanup() {
  kill -TERM -- "-$launch_pgid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$launch_pgid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log" "$configured_world"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM
sleep 15
echo "M1A_S2_LAUNCH_PID:$pid"
echo "M1A_S2_LAUNCH_PGID:$launch_pgid"
echo "M1A_S2_WORLD_SHA256:$world_sha"
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_S2_LAUNCH_FAILED
  sed -n '1,220p' "$launch_log"
  exit 0
fi
M1A_S2_CONFIGURATION_JSON="$config_json" M1A_S2_WORLD_SHA256="$world_sha" \
  python3 "/home/$USER/$root/scripts/m1a_friction_trial_client.py"
echo M1A_S2_LAUNCH_TAIL
tail -n 160 "$launch_log"
REMOTE
  failure="$(python3 - "$log" <<'PY'
import json
import sys
from pathlib import Path
payload = next((json.loads(line) for line in Path(sys.argv[1]).read_text(errors="replace").splitlines()
                if line.startswith("{") and '"primary_failure_class"' in line), {})
print(payload.get("primary_failure_class", "RUNTIME_EVIDENCE_MISSING"))
PY
)"
  if [[ "$failure" == "APPROACH_ALIGNMENT_FAILURE" ]]; then
    new_approach_failures=$((new_approach_failures + 1))
  fi
  if [[ "$failure" == "RUNTIME_EVIDENCE_MISSING" ]]; then
    early_stop_reason="RUNTIME_EVIDENCE_MISSING"
    break
  fi
  # The eight historic failures were a now-explained side-grasp geometry
  # defect.  This applies §9.5 only to the corrected pose family itself.
  if (( new_approach_failures >= 3 )); then
    early_stop_reason="THREE_APPROACH_ALIGNMENT_FAILURES_IN_ORIENTATION_RECOVERY"
    break
  fi
done
fi

stage_finished_epoch="$(date +%s)"
aggregation_args=(python3 - "$RUN_ID" "$local_sha" "$stage_started_epoch" "$stage_finished_epoch" "$early_stop_reason" "$prior_count")
if (( ${#logs[@]} > 0 )); then
  aggregation_args+=("${logs[@]}")
fi
"${aggregation_args[@]}" <<'PY'
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

run_id, local_sha, started, finished, early_stop_reason, prior_count, *logs = sys.argv[1:]
prior_path = Path("reports/m1a-friction-trials.json")
prior = json.loads(prior_path.read_text()) if prior_path.exists() else {}
prior_all_trials = list(prior.get("trials", []))
same_allocation_sha = prior.get("local_gazebo_urdf_sha256") == local_sha
historical_trials = [*prior.get("historical_trials", [])]
if not same_allocation_sha:
    historical_trials.extend(prior_all_trials)
prior_runtime_blocked = [
    *prior.get("runtime_blocked_attempts", []),
    *[
    trial for trial in prior_all_trials
    if trial.get("diagnostic_subclass") == "RUNTIME_EVIDENCE_MISSING"
    ],
]
runtime_blocked_logs = [
    {
        "raw_log": path,
        "diagnostic_subclass": "RUNTIME_EVIDENCE_MISSING",
        "reason": "NO_STRUCTURED_RUNTIME_EVIDENCE",
    }
    for path in os.environ.get("M1A_S2_RUNTIME_BLOCKED_LOGS", "").split(":") if path
]
prior_trials = [
    trial for trial in prior_all_trials
    if trial.get("diagnostic_subclass") != "RUNTIME_EVIDENCE_MISSING"
] if same_allocation_sha else []
if len(prior_trials) != int(prior_count):
    raise SystemExit("S2 report changed during continuation; refusing to discard evidence")
new_trials = []
for offset, path in enumerate(logs, 1):
    raw = Path(path).read_text(errors="replace")
    payload = next((json.loads(line) for line in raw.splitlines()
                    if line.startswith("{") and '"primary_failure_class"' in line), None)
    if payload is None:
        payload = {
            "status": "FRICTION_TRIAL_FAILED",
            "primary_failure_class": "APPROACH_ALIGNMENT_FAILURE",
            "diagnostic_subclass": "RUNTIME_EVIDENCE_MISSING",
            "reason": "NO_STRUCTURED_RUNTIME_EVIDENCE",
            "detachable_joint_used": False,
        }
    new_trials.append({"trial_id": f"{run_id}-trial-{len(prior_trials) + offset}", **payload, "raw_log": path})
new_physical_trials = [
    trial for trial in new_trials
    if trial.get("diagnostic_subclass") != "RUNTIME_EVIDENCE_MISSING"
]
trials = [*prior_trials, *new_physical_trials]
counts = Counter(trial.get("primary_failure_class") for trial in trials)
by_configuration = defaultdict(list)
for trial in trials:
    by_configuration[trial.get("configuration", {}).get("id", "unknown")].append(trial)
configuration_summary = {
    config_id: {
        "trials": len(items),
        "frictional_successes": sum(item.get("status") == "FRICTIONAL_GRASP_VERIFIED" for item in items),
        "failure_counts": dict(Counter(item.get("primary_failure_class") for item in items)),
        "parameters": items[0].get("configuration", {}),
    }
    for config_id, items in by_configuration.items()
}
orientation_summary = defaultdict(Counter)
for trial in trials:
    approach = trial.get("approach", {})
    selected = approach.get("selected_candidate_id")
    for item in approach.get("candidate_evaluations", []):
        candidate_id = item.get("candidate_id", "unknown")
        if not item.get("eligible", False):
            orientation_summary[candidate_id][item.get("reason", "INELIGIBLE")] += 1
        elif item.get("collision_checked_ik_solved"):
            orientation_summary[candidate_id]["COLLISION_CHECKED_IK_SOLVED"] += 1
        else:
            error = item.get("collision_checked_ik_error") or {}
            orientation_summary[candidate_id][f"COLLISION_CHECKED_IK_REJECTED_{error.get('code')}"] += 1
        if candidate_id == selected:
            orientation_summary[candidate_id]["SELECTED_FOR_EXECUTION"] += 1
    contacts = trial.get("contacts", {})
    if selected and contacts.get("left_target") and contacts.get("right_target"):
        orientation_summary[selected]["BILATERAL_TARGET_CONTACT"] += 1
    if selected and trial.get("gripper_frame_corridor_evidence", {}).get("target_in_grasp_corridor"):
        orientation_summary[selected]["GRIPPER_FRAME_CORRIDOR_PASS"] += 1
verified = any(summary["frictional_successes"] >= 4 for summary in configuration_summary.values())
runtime_evidence_missing = any(
    trial.get("diagnostic_subclass") == "RUNTIME_EVIDENCE_MISSING" for trial in new_trials
)
status = (
    "FRICTION_TRIALS_BLOCKED_RUNTIME_EVIDENCE" if runtime_evidence_missing
    else "FRICTIONAL_GRASP_VERIFIED" if verified else "FRICTIONAL_GRASP_NOT_VERIFIED"
)
reason = (
    "At least one bounded configuration achieved four complete real frictional grasps."
    if verified else "No configuration met the 4/5 complete real-friction-grasp threshold."
)
if runtime_evidence_missing:
    reason = "No structured S2 runtime evidence was produced; this continuation is not a physical-trial result."
if early_stop_reason:
    reason += f" Early stop: {early_stop_reason}; unused attempt capacity: {15 - len(trials)}."
data = {
    "status": status,
    "run_id": run_id,
    "frictional_trials": len(trials),
    "frictional_successes": sum(item.get("status") == "FRICTIONAL_GRASP_VERIFIED" for item in trials),
    "failure_counts": {key: counts.get(key, 0) for key in (
        "APPROACH_ALIGNMENT_FAILURE", "CONTACT_CLOSURE_FAILURE",
        "HOLD_TRANSPORT_FAILURE", "RELEASE_PLACEMENT_FAILURE",
    )},
    "configuration_summary": configuration_summary,
    "orientation_candidate_summary": {key: dict(value) for key, value in orientation_summary.items()},
    "trials": trials,
    "historical_trials": historical_trials,
    "allocation_reset": {
        "approved_by": "ADR-0007/ADR-0008/ADR-0009",
        "allocation_urdf_sha256": local_sha,
        "historical_trial_count": len(historical_trials),
        "current_window_max_trials": 15,
    },
    "runtime_blocked_attempts": [
        *prior_runtime_blocked,
        *runtime_blocked_logs,
        *[trial for trial in new_trials if trial.get("diagnostic_subclass") == "RUNTIME_EVIDENCE_MISSING"],
    ],
    "noncanonical_preflight_sessions": [
        {
            "raw_log": path,
            "reason": "INTERRUPTED_BEFORE_CORRECTED_CORRIDOR_IMPLEMENTATION_DEPLOYED",
        }
        for path in os.environ.get("M1A_S2_NONCANONICAL_LOGS", "").split(":") if path
    ],
    "detachable_joint_used": False,
    "early_stop": bool(early_stop_reason),
    "early_stop_reason": early_stop_reason or None,
    "stage_started_epoch": int(started),
    "stage_finished_epoch": int(finished),
    "stage_duration_s": int(finished) - int(started),
    "stage_timebox_s": 120 * 60,
    "timebox_reached": int(finished) - int(started) >= 120 * 60,
    "resume_prior_trial_count": len(prior_trials),
    "continuation_trial_count": len(new_physical_trials),
    "remaining_attempt_capacity": 15 - len(trials),
    "reason": reason,
    "local_gazebo_urdf_sha256": local_sha,
}
Path("reports/m1a-friction-trials.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-friction-trials.md").write_text(
    "# M1A S2 friction trials\n\n"
    f"- Status: `{status}`\n- Trials: `{len(trials)}/15`; continuation: `{len(new_physical_trials)}`; duration: `{data['stage_duration_s']} s`\n"
    f"- Failure counts: `{data['failure_counts']}`\n"
    f"- Early stop: `{data['early_stop']}`; reason: `{data['early_stop_reason']}`\n"
    f"- Runtime-blocked non-physical sessions: `{len(data['runtime_blocked_attempts'])}`; interrupted preflight sessions: `{len(data['noncanonical_preflight_sessions'])}`.\n"
    f"- Orientation candidate evidence: `{data['orientation_candidate_summary']}`.\n"
    f"- Historical prior-SHA trials retained separately: `{len(historical_trials)}`; current approved window is bound to `{local_sha}`.\n"
    "- No DetachableJoint attach request was sent in any S2 trial.\n"
)
PY
