#!/usr/bin/env bash
# S3 remains fail-closed: no attach is attempted without S0 and S1 evidence.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - <<'PY'
import json
from pathlib import Path
s0 = json.loads(Path("reports/m1a-contact-calibration.json").read_text())
s1 = json.loads(Path("reports/m1a-motion-execution.json").read_text())
data = {"status": "NOT_RUN_PREREQUISITES_NOT_MET", "contact_gated_trials": 0, "contact_gated_successes": 0,
        "release_verified_count": 0, "attach_events": [],
        "reason": f"S0={s0['status']}; S1={s1['motion_status']}. No DetachableJoint attach request was sent."}
Path("reports/m1a-contact-gate.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-gate.md").write_text(f"# M1A S3 contact-gated constraint\n\n- Status: `{data['status']}`\n- {data['reason']}\n")
PY
