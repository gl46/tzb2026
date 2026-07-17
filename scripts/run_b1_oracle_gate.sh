#!/usr/bin/env bash
# S4: execute a fresh B1 oracle-geometric batch using the verified final
# contact-gated grasp mode.  This is intentionally not a relabel of S1 or S3:
# the invoked runner starts ten new reset sessions and each client queries the
# live Gazebo cube pose before it constructs its collision-checked approach.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_S4_RUN_ID:-m1a-s4-$(date +%Y%m%d-%H%M%S)}"
EPISODE_LIMIT="${M1A_S4_EPISODE_LIMIT:-10}"
started="$(date +%s)"

if ! [[ "$EPISODE_LIMIT" =~ ^[0-9]+$ ]] || (( EPISODE_LIMIT != 10 )); then
  echo "M1A_S4_EPISODE_LIMIT must be exactly 10 for the B1 repeated gate" >&2
  exit 2
fi

python3 - <<'PY'
import json
from pathlib import Path

s3 = json.loads((Path("reports") / "m1a-contact-gate.json").read_text())
if s3.get("status") != "CONTACT_GATED_CONSTRAINT_VERIFIED":
    raise SystemExit("S4_FINAL_GRASP_MODE_NOT_VERIFIED")
PY

# Do not reuse the prior S3 records.  The S3 runner supplies the real remote
# Gazebo execution protocol, including explicit detach/reset, per-episode
# oracle pose read, contact gate, controller-driven motions, and positive
# release/bin-settle verification.  Its run ID makes this an independent S4
# batch; the old S3 report is retained in historical_s3_batches by the runner.
M1A_S3_RUN_ID="$RUN_ID" \
M1A_S3_EPISODE_LIMIT="$EPISODE_LIMIT" \
bash scripts/run_contact_gated_grasp.sh

finished="$(date +%s)"
python3 - "$RUN_ID" "$started" "$finished" <<'PY'
import json
import sys
from pathlib import Path

run_id, started, finished = sys.argv[1:]
reports = Path("reports")
s0 = json.loads((reports / "m1a-contact-calibration.json").read_text())
s1 = json.loads((reports / "m1a-motion-execution.json").read_text())
s2 = json.loads((reports / "m1a-friction-trials.json").read_text())
s4_execution = json.loads((reports / "m1a-contact-gate.json").read_text())
episodes = s4_execution.get("episodes", [])
fresh_run = s4_execution.get("run_id") == run_id
trials = len(episodes)
successes = sum(
    item.get("status") == "CONTACT_GATED_PICK_PLACE_VERIFIED" for item in episodes
)
oracle_per_episode = all(
    item.get("initial_cube_pose", {}).get("source", "").startswith("gz model runtime oracle")
    and item.get("cube_pose_before_close", {}).get("source", "").startswith("/xh/supervision/dynamic_pose")
    and item.get("direct_object_pose_write") is False
    for item in episodes
)
release_verified = sum(bool(item.get("release", {}).get("passed")) for item in episodes)
verified = (
    fresh_run
    and s4_execution.get("status") == "CONTACT_GATED_CONSTRAINT_VERIFIED"
    and trials == 10
    and successes >= 8
    and release_verified >= successes
    and oracle_per_episode
)
status = "B1_ORACLE_EXECUTION_VERIFIED" if verified else "B1_ORACLE_BLOCKED"
reason = (
    "A fresh 10-reset B1 batch used the runtime Gazebo pose only as oracle task geometry, "
    "then collision-checked IK and controller execution; at least 8 episodes completed contact-gated "
    "pick/place and positive release."
    if verified else
    "The fresh B1 batch did not satisfy its explicit 10-episode, >=8-success, oracle-per-episode, "
    "or positive-release requirement; no B1 success claim is made."
)
data = {
    "status": status,
    "run_id": run_id,
    "b1_trials": trials,
    "b1_successes": successes,
    "mode": "B1_GROUND_TRUTH_POSE_BASELINE",
    "final_grasp_mode": "CONTACT_GATED_CONSTRAINED_GRASP",
    "s4_execution_report": "reports/m1a-contact-gate.json",
    "s4_execution_run_id": s4_execution.get("run_id"),
    "s0_status": s0.get("status"),
    "s1_status": s1.get("motion_status"),
    "s2_status": s2.get("status"),
    "source_s3_status": s4_execution.get("status"),
    "oracle_pose_in_observation": False,
    "oracle_pose_used_for_task_geometry": True,
    "oracle_pose_evidence_per_episode": oracle_per_episode,
    "direct_object_pose_write": False,
    "release_verified_count": release_verified,
    "episode_ids": [item.get("episode_id") for item in episodes],
    "raw_logs": [item.get("raw_log") for item in episodes],
    "stage_started_epoch": int(started),
    "stage_finished_epoch": int(finished),
    "stage_duration_s": int(finished) - int(started),
    "stage_timebox_s": 105 * 60,
    "timebox_reached": int(finished) - int(started) >= 105 * 60,
    "reason": reason,
}
(reports / "m1a-b1-oracle.json").write_text(json.dumps(data, indent=2) + "\n")
(reports / "m1a-b1-oracle.md").write_text(
    "# M1A S4 B1 Oracle\n\n"
    f"- Status: `{status}`\n"
    f"- Fresh B1 reset episodes: `{trials}/10`; successes: `{successes}`; positive releases: `{release_verified}`.\n"
    f"- Runtime oracle was task geometry only, not an Observation field: `{oracle_per_episode}`.\n"
    f"- {reason}\n"
)
(reports / "b1-baseline-status.json").write_text(json.dumps({
    "status": status,
    "baseline": "B1_GROUND_TRUTH_POSE_BASELINE",
    "run_id": run_id,
    "trials": trials,
    "successes": successes,
    "oracle_pose_in_observation": False,
    "reason": reason,
}, indent=2) + "\n")
PY
