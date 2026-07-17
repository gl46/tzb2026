#!/usr/bin/env bash
# Run and preserve an isolated no-contact diagnosis for both hand channels.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
RUN_ID="${M1A_HAND_PROBE_RUN_ID:-m1a-hand-actuation-$(date +%Y%m%d-%H%M%S)}"
REPORT_STEM="${M1A_HAND_PROBE_REPORT_STEM:-m1a-hand-actuation-probe}"
EXPERIMENT_LABEL="${M1A_HAND_PROBE_EXPERIMENT_LABEL:-APPROVED_MODEL}"
[[ "$REPORT_STEM" =~ ^[A-Za-z0-9-]+$ ]] || { echo "invalid M1A_HAND_PROBE_REPORT_STEM" >&2; exit 2; }
mkdir -p logs reports
log="logs/${RUN_ID}.log"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" \
  "bash '/home/$SIM_USER/$PROJECT_REMOTE_ROOT/scripts/run_m1a_hand_actuation_probe_remote.sh' '$PROJECT_REMOTE_ROOT'" \
  >"$log" 2>&1 || true
python3 - "$RUN_ID" "$log" "$REPORT_STEM" "$EXPERIMENT_LABEL" <<'PY'
import json
import sys
from pathlib import Path

run_id, log, report_stem, experiment_label = sys.argv[1:]
raw = Path(log).read_text(errors="replace")
payload = next((json.loads(line) for line in raw.splitlines()
                if line.startswith("{") and '"controls_verified"' in line), None)
if payload is None:
    payload = {
        "status": "HAND_ACTUATION_PROBE_BLOCKED",
        "controls_verified": False,
        "reason": "NO_STRUCTURED_RUNTIME_EVIDENCE",
    }
payload.update({
    "run_id": run_id,
    "raw_log": log,
    "experiment_label": experiment_label,
})
Path(f"reports/{report_stem}.json").write_text(json.dumps(payload, indent=2) + "\n")
Path(f"reports/{report_stem}.md").write_text(
    "# M1A hand actuation probe\n\n"
    f"- Status: `{payload['status']}`; controls verified: `{payload.get('controls_verified')}`.\n"
    f"- Scope: `{payload.get('scope', 'UNAVAILABLE')}`.\n"
    f"- Experiment label: `{experiment_label}`.\n"
    f"- Raw log: `{log}`.\n"
)
print(json.dumps({"status": payload["status"], "controls_verified": payload.get("controls_verified")}))
PY
