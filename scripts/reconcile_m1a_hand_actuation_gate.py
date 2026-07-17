#!/usr/bin/env python3
"""Reconcile S0 calibration status with the isolated hand-actuation gate."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
S0_PATH = ROOT / "reports" / "m1a-contact-calibration.json"
HAND_PATH = ROOT / "reports" / "m1a-hand-actuation-probe.json"


def main() -> int:
    s0 = json.loads(S0_PATH.read_text())
    hand = json.loads(HAND_PATH.read_text())
    prior_status = s0.get("status")
    controls_verified = bool(hand.get("controls_verified"))
    reconciliation = {
        "hand_actuation_probe_status": hand.get("status"),
        "hand_actuation_controls_verified": controls_verified,
        "hand_actuation_raw_log": hand.get("raw_log"),
        "hand_actuation_probe_run_id": hand.get("run_id"),
        "historical_s0_status_before_reconciliation": prior_status,
    }
    if not controls_verified:
        anomaly = "HAND_ACTUATION_CHANNELS_NOT_VERIFIED: S0 contact positives cannot establish bilateral commanded closure"
        anomalies = list(s0.get("aggregation_anomalies", []))
        if anomaly not in anomalies:
            anomalies.append(anomaly)
        s0.update({
            "status": "CONTACT_TELEMETRY_PARTIAL",
            "reason": (
                "The isolated home-pose probe found panda_finger_joint1 cannot close from 0.040 m to 0.010 m "
                "without object contact. Historical S0 positive contacts therefore do not prove bilateral commanded closure."
            ),
            "aggregation_anomalies": anomalies,
            "hand_actuation_reconciliation": reconciliation,
        })
    else:
        s0["hand_actuation_reconciliation"] = reconciliation
    S0_PATH.write_text(json.dumps(s0, indent=2) + "\n")
    (ROOT / "reports" / "m1a-contact-calibration.md").write_text(
        "# M1A S0 contact telemetry calibration\n\n"
        f"- Status: `{s0['status']}`\n"
        f"- Reason: {s0['reason']}\n"
        f"- Historical isolated condition trials: `{s0.get('calibration_trials_completed')}/13`; "
        f"model match: `{s0.get('model_match')}`.\n"
        f"- Hand actuation probe: `{hand.get('status')}`; controls verified: `{controls_verified}`.\n"
        f"- Raw hand-actuation evidence: `{hand.get('raw_log')}`.\n"
        "- No grasp is claimed by this calibration audit.\n"
        "- Changed files: `reports/m1a-contact-calibration.json`, `reports/m1a-contact-calibration.md`.\n"
        "- Tests: `pytest -q tests/unit/test_m1a_gates.py`; failures/blockers: left finger actuation is not verified.\n"
        "- Next command: approve and implement a formal left-finger actuation ADR, then rerun S0 followed by S1.\n"
    )
    print(json.dumps({
        "status": s0["status"],
        "hand_actuation_controls_verified": controls_verified,
        "prior_status": prior_status,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
