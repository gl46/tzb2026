#!/usr/bin/env bash
# S3: a bounded real contact-gated DetachableJoint fallback.
#
# Every episode starts a fresh Gazebo/MoveIt session.  The remote client may
# publish the DetachableJoint attach topic only after it records every numeric
# gate input; neither this runner nor S2 ever sends an attach request.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_S3_RUN_ID:-m1a-s3-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
EPISODE_LIMIT="${M1A_S3_EPISODE_LIMIT:-10}"
EPISODE_START="${M1A_S3_EPISODE_START:-1}"
PREVIOUS_LOGS="${M1A_S3_PREVIOUS_LOGS:-}"
RECONCILE_ONLY="${M1A_S3_RECONCILE_ONLY:-0}"
PREFERRED_CANDIDATE_ID="${M1A_S3_PREFERRED_CANDIDATE_ID:-fingertip_down_close_world_y}"
CLOSE_COMMAND_PER_FINGER_M="${M1A_S3_CLOSE_COMMAND_PER_FINGER_M:-0.033}"
mkdir -p logs reports
if ! [[ "$EPISODE_LIMIT" =~ ^[0-9]+$ && "$EPISODE_START" =~ ^[0-9]+$ ]] || \
   { [[ "$RECONCILE_ONLY" != "1" ]] && (( EPISODE_LIMIT < 1 || EPISODE_START < 1 || EPISODE_START + EPISODE_LIMIT - 1 > 10 )); } || \
   { [[ "$RECONCILE_ONLY" == "1" && "$EPISODE_LIMIT" != "0" ]]; }; then
  echo "M1A_S3 episode range must be a non-empty subset of 1..10" >&2
  exit 2
fi
if ! python3 - "$CLOSE_COMMAND_PER_FINGER_M" <<'PY'
import sys

value = float(sys.argv[1])
raise SystemExit(0 if 0.0 <= value <= 0.04 else 1)
PY
then
  echo "M1A_S3_CLOSE_COMMAND_PER_FINGER_M must be within [0.0, 0.04]" >&2
  exit 2
fi

local_sha="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"
stage_started_epoch="${M1A_S3_STAGE_STARTED_EPOCH:-$(date +%s)}"

if ! python3 - "$local_sha" <<'PY'
import json
import sys
from pathlib import Path

local_sha = sys.argv[1]
def load(name):
    return json.loads((Path("reports") / name).read_text())
s0, s1, s2 = load("m1a-contact-calibration.json"), load("m1a-motion-execution.json"), load("m1a-friction-trials.json")
hand = load("m1a-hand-actuation-probe.json")
bullet = load("m1a-bullet-capability-audit.json")
hand_verified = bool(hand.get("controls_verified")) or (
    bullet.get("status") == "M1A_BULLET_CAPABILITY_VERIFIED"
    and bullet.get("local_gazebo_urdf_sha256") == local_sha
    and bullet.get("hand_probe", {}).get("controls_verified") is True
)
ready = (
    s0.get("status") == "CONTACT_TELEMETRY_CALIBRATED"
    and hand_verified
    and s1.get("motion_status") == "VERIFIED_MOVEIT_EXECUTION"
    and s2.get("status") in {"FRICTIONAL_GRASP_NOT_VERIFIED", "FRICTIONAL_GRASP_VERIFIED"}
    and s0.get("local_gazebo_urdf_sha256") == local_sha
    and s1.get("local_gazebo_urdf_sha256") == local_sha
)
raise SystemExit(0 if ready else 1)
PY
then
  if [[ "$(python3 - <<'PY'
import json
from pathlib import Path
print(str(bool(json.loads(Path('reports/m1a-hand-actuation-probe.json').read_text()).get('controls_verified'))).lower())
PY
)" != "true" ]]; then
    echo "S3_HAND_ACTUATION_CHANNELS_NOT_VERIFIED" >&2
  fi
  echo "S3_PREREQUISITES_NOT_CURRENT" >&2
  exit 2
fi

protocol_json="$(M1A_S3_PREFERRED_CANDIDATE_ID="$PREFERRED_CANDIDATE_ID" python3 - <<'PY'
import json
import os
from pathlib import Path
import yaml

families = yaml.safe_load(Path("configs/m1a_friction_trials.yaml").read_text())["grasp_orientation_families"]
preferred = os.environ["M1A_S3_PREFERRED_CANDIDATE_ID"]
candidate_ids = {candidate["id"] for candidate in families["candidates"]}
if preferred not in candidate_ids:
    raise SystemExit(f"M1A_S3_UNKNOWN_PREFERRED_CANDIDATE:{preferred}")
print(json.dumps({
    "grasp_orientation_families": families,
    "preferred_candidate_id": preferred,
}, separators=(",", ":")))
PY
)"

declare -a logs=()
if [[ -n "$PREVIOUS_LOGS" ]]; then
  IFS=':' read -r -a prior_logs <<< "$PREVIOUS_LOGS"
  for log in "${prior_logs[@]}"; do
    [[ -s "$log" ]] || { echo "M1A_S3_PREVIOUS_LOG_MISSING:$log" >&2; exit 2; }
    logs+=("$log")
  done
fi
if [[ "$RECONCILE_ONLY" != "1" ]]; then
for episode in $(seq "$EPISODE_START" "$((EPISODE_START + EPISODE_LIMIT - 1))"); do
  config_json="$(python3 - "$protocol_json" "$RUN_ID" "$episode" "$CLOSE_COMMAND_PER_FINGER_M" <<'PY'
import json
import sys

protocol, run_id, episode, close_command = sys.argv[1:]
data = json.loads(protocol)
data.update({
    "run_id": run_id,
    "episode_id": f"{run_id}-episode-{int(episode):02d}",
    "seed": int(episode),
    "mode": "CONTACT_GATED_CONSTRAINED_GRASP",
    # Each finger collision board is 18 mm thick.  At q=0.033 m the inner
    # clearance is 2q - 0.018 = 0.048 m: a 2 mm contact preload on the 5 cm
    # cube, rather than the old 1 cm command that pushed it through the pads.
    # The gate still uses only the *observed* joint positions.
    "close_command_per_finger_m": float(close_command),
    "preferred_candidate_id": data["preferred_candidate_id"],
})
print(json.dumps(data, separators=(",", ":")))
PY
)"
  config_b64="$(printf '%s' "$config_json" | base64 | tr -d '\n')"
  log="logs/${RUN_ID}-s3-episode-${episode}.log"
  logs+=("$log")
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" \
    "bash '/home/$SIM_USER/$PROJECT_REMOTE_ROOT/scripts/run_m1a_s3_remote_episode.sh' '$PROJECT_REMOTE_ROOT' '$config_b64'" \
    >"$log" 2>&1 || true
done
fi

stage_finished_epoch="$(date +%s)"
python3 - "$RUN_ID" "$local_sha" "$stage_started_epoch" "$stage_finished_epoch" "${logs[@]}" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

run_id, local_sha, started, finished, *logs = sys.argv[1:]
historical = json.loads(Path("reports/m1a-contact-gate.json").read_text()) if Path("reports/m1a-contact-gate.json").exists() else {}
historical_batches = list(historical.get("historical_s3_batches", []))
if historical.get("episodes"):
    historical_batches.append({
        "run_id": historical.get("run_id"),
        "status": historical.get("status"),
        "contact_gated_trials": historical.get("contact_gated_trials"),
        "contact_gated_successes": historical.get("contact_gated_successes"),
        "release_verified_count": historical.get("release_verified_count"),
        "failure_counts": historical.get("failure_counts", {}),
        "raw_logs": [item.get("raw_log") for item in historical.get("episodes", [])],
        "reason": historical.get("reason"),
    })
episodes, runtime_blocked = [], []
for path in logs:
    raw = Path(path).read_text(errors="replace")
    payload = next((json.loads(line) for line in raw.splitlines()
                    if line.startswith("{") and '"episode_id"' in line and '"gate"' in line), None)
    if payload is None:
        runtime_blocked.append({
            "raw_log": path,
            "reason": "NO_STRUCTURED_S3_RUNTIME_EVIDENCE",
        })
        continue
    payload["raw_log"] = path
    episodes.append(payload)
successes = [episode for episode in episodes if episode.get("status") == "CONTACT_GATED_PICK_PLACE_VERIFIED"]
gate_rejections = [
    {
        "episode_id": episode.get("episode_id"),
        "event": "CONTACT_GATE_REJECTED",
        "reasons": episode.get("gate", {}).get("reasons", []),
        "gate_input": episode.get("gate", {}).get("input", {}),
        "attach_sent": bool(episode.get("attach", {}).get("sent")),
    }
    for episode in episodes if not episode.get("gate", {}).get("passed")
]
attach_events = [episode.get("attach") for episode in episodes if episode.get("attach", {}).get("sent")]
release_count = sum(bool(episode.get("release", {}).get("passed")) for episode in episodes)
all_ten_actual = len(episodes) == 10 and not runtime_blocked
status = (
    "CONTACT_GATED_CONSTRAINT_VERIFIED" if all_ten_actual and len(successes) >= 8
    else "CONTACT_GATED_CONSTRAINT_RUNTIME_BLOCKED" if runtime_blocked
    else "CONTACT_GATED_CONSTRAINT_NOT_VERIFIED"
)
failure_counts = Counter(episode.get("primary_failure_class", "UNKNOWN") for episode in episodes)
reason = (
    "At least 8 of 10 real reset episodes met the gate, sent an observed constraint attach, "
    "executed the collision-checked transfer, and positively verified release/bin settling."
    if status == "CONTACT_GATED_CONSTRAINT_VERIFIED" else
    "At least one episode did not emit structured runtime evidence; no completion claim is allowed."
    if runtime_blocked else
    "Fewer than 8 of 10 real S3 episodes completed the full contact-gated constrained pick/place sequence."
)
data = {
    "status": status,
    "run_id": run_id,
    "mode": "CONTACT_GATED_CONSTRAINED_GRASP",
    "contact_gated_trials": len(episodes),
    "contact_gated_successes": len(successes),
    "release_verified_count": release_count,
    "episodes": episodes,
    "attach_events": attach_events,
    "detachable_attach_sent": bool(attach_events),
    "gate_rejections": gate_rejections,
    "runtime_blocked_attempts": runtime_blocked,
    "historical_s3_batches": historical_batches,
    "historical_s2_evaluations": historical.get("gate_rejections", []),
    "failure_counts": dict(failure_counts),
    "local_gazebo_urdf_sha256": local_sha,
    "stage_started_epoch": int(started),
    "stage_finished_epoch": int(finished),
    "stage_duration_s": int(finished) - int(started),
    "stage_timebox_s": 150 * 60,
    "timebox_reached": int(finished) - int(started) >= 150 * 60,
    "reason": reason,
}
Path("reports/m1a-contact-gate.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-gate.md").write_text(
    "# M1A S3 contact-gated constraint\n\n"
    f"- Status: `{status}`; mode: `CONTACT_GATED_CONSTRAINED_GRASP`.\n"
    f"- Real reset episodes: `{len(episodes)}/10`; successes: `{len(successes)}`; release verified: `{release_count}`.\n"
    f"- Gate rejections: `{len(gate_rejections)}`; attach requests: `{len(attach_events)}`; runtime-blocked sessions: `{len(runtime_blocked)}`.\n"
    f"- Preserved prior S3 batches: `{len(historical_batches)}`.\n"
    f"- {reason}\n"
    "- Each attach event is emitted by the remote client only after its recorded gate passes; no Gazebo object pose write is used.\n"
)
print(json.dumps({"status": status, "episodes": len(episodes), "successes": len(successes), "runtime_blocked": len(runtime_blocked)}))
PY
