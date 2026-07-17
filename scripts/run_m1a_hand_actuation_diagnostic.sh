#!/usr/bin/env bash
# Preserve Option 1 diagnostic evidence from a fresh remote simulator session.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
RUN_ID="${M1A_HAND_DIAGNOSTIC_RUN_ID:-m1a-hand-diagnostic-$(date +%Y%m%d-%H%M%S)}"
[[ "$RUN_ID" =~ ^[A-Za-z0-9-]+$ ]] || { echo "invalid M1A_HAND_DIAGNOSTIC_RUN_ID" >&2; exit 2; }
mkdir -p logs reports
log="logs/${RUN_ID}.log"
remote_log="/home/$SIM_USER/$PROJECT_REMOTE_ROOT/logs/${RUN_ID}.hand-diagnostic.remote.log"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" \
  "rm -f '$remote_log'; bash '/home/$SIM_USER/$PROJECT_REMOTE_ROOT/scripts/run_m1a_hand_actuation_diagnostic_remote.sh' '$PROJECT_REMOTE_ROOT' '$remote_log'" \
  >/dev/null 2>&1 || true
complete=false
for _ in $(seq 1 70); do
  marker="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "tail -n 1 '$remote_log' 2>/dev/null" || true)"
  if [[ "$marker" == M1A_HAND_DIAGNOSTIC_REMOTE_DONE:* ]]; then
    complete=true
    break
  fi
  sleep 3
done
scp -q -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST:$remote_log" "$log" || true
if [[ "$complete" != true ]]; then
  printf '%s\n' 'M1A_HAND_DIAGNOSTIC_REMOTE_DONE:TIMEOUT_OR_OUTPUT_UNAVAILABLE' >>"$log"
fi
python3 - "$RUN_ID" "$log" <<'PY'
import json
import sys
from pathlib import Path

run_id, log = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
payload = next((json.loads(line) for line in raw.splitlines()
                if line.startswith("{") and '"diagnostic_completed"' in line), None)
if payload is None:
    payload = {
        "status": "HAND_ACTUATION_DIAGNOSTIC_BLOCKED",
        "diagnostic_completed": False,
        "reason": "NO_STRUCTURED_RUNTIME_EVIDENCE",
    }
payload.update({"run_id": run_id, "raw_log": log})
Path("reports/m1a-hand-actuation-diagnostic.json").write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
conclusions = payload.get("conclusions", {})
Path("reports/m1a-hand-actuation-diagnostic.md").write_text(
    "# M1A Option 1 hand-actuation diagnostics\n\n"
    f"- Status: `{payload['status']}`.\n"
    f"- Run: `{run_id}`.\n"
    f"- Raw log: `{log}`.\n"
    f"- q1 world pose shows no close: `{conclusions.get('q1_world_pose_shows_no_close')}`.\n"
    f"- Right world pose matches asymmetric command: `{conclusions.get('right_world_pose_matches_0p005m_asymmetric_motion')}`.\n"
    f"- Changed files: `scripts/m1a_hand_actuation_diagnostic.py`, remote/local runners, this report.\n"
    "- Verification: fresh Gazebo session; explicit 1 mm hand-goal tolerance; spawned-SDF service dump.\n"
    "- Failure/blocker: no source-level repair conclusion is asserted by this diagnostic alone.\n"
    "- Next command: evaluate this report before the approved temporary mirror-axis overlay.\n",
    encoding="utf-8",
)
print(json.dumps({
    "status": payload["status"],
    "diagnostic_completed": payload.get("diagnostic_completed"),
    "q1_world_pose_shows_no_close": conclusions.get("q1_world_pose_shows_no_close"),
    "right_world_pose_matches_asymmetric": conclusions.get("right_world_pose_matches_0p005m_asymmetric_motion"),
}))
PY
