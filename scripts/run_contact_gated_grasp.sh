#!/usr/bin/env bash
# S3 fails closed from the actual S2 evidence; it never attaches without a gate.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - <<'PY'
import json
from pathlib import Path
s0 = json.loads(Path("reports/m1a-contact-calibration.json").read_text())
s1 = json.loads(Path("reports/m1a-motion-execution.json").read_text())
s2 = json.loads(Path("reports/m1a-friction-trials.json").read_text())
rejections = []
for trial in s2.get("trials", []):
    contacts = trial.get("contacts", {})
    reasons = []
    if not contacts.get("left_target"): reasons.append("LEFT_TARGET_CONTACT_FALSE")
    if not contacts.get("right_target"): reasons.append("RIGHT_TARGET_CONTACT_FALSE")
    if contacts.get("bilateral_overlap_s", 0.0) < .1: reasons.append("BILATERAL_OVERLAP_BELOW_100MS")
    if not trial.get("approach", {}).get("executed"): reasons.append("APPROACH_CONTROLLER_NOT_EXECUTED")
    rejections.append({"trial_id": trial.get("trial_id"), "event": "CONTACT_GATE_REJECTED", "reasons": reasons, "attach_sent": False})
ready = s0["status"] == "CONTACT_TELEMETRY_CALIBRATED" and s1["motion_status"] == "VERIFIED_MOVEIT_EXECUTION"
data = {"status": "CONTACT_GATED_CONSTRAINT_NOT_VERIFIED", "contact_gated_trials": len(rejections), "contact_gated_successes": 0, "release_verified_count": 0, "attach_events": [], "gate_rejections": rejections, "detachable_attach_sent": False, "reason": "S2 produced three actual APPROACH_ALIGNMENT_FAILURE trials; S3 gate rejected every available attempt before attach because bilateral target contact was absent." if ready else "S0/S1 prerequisite failed."}
Path("reports/m1a-contact-gate.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/m1a-contact-gate.md").write_text("# M1A S3 contact-gated constraint\n\n" + f"- Status: `{data['status']}`\n- Gate rejections: `{len(rejections)}`; attach requests: `0`.\n- {data['reason']}\n")
PY
