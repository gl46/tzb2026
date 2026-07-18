#!/usr/bin/env python3
"""Offline-only S0-style M1B tolerance versus perception reachability gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.grasp.tolerance_envelope import OffsetTrialV1, perception_axis_audit, reachability_gate, tolerance_envelope


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tolerance-trials", required=True, type=Path)
    parser.add_argument("--perception-errors", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw_trials = json.loads(args.tolerance_trials.read_text(encoding="utf-8"))
    trials = [OffsetTrialV1(**record) for record in raw_trials["trials"]]
    raw_errors = json.loads(args.perception_errors.read_text(encoding="utf-8"))
    errors = [tuple(float(value) for value in record["error_world_xyz_m"]) for record in raw_errors["matches"]]
    envelope = tolerance_envelope(trials)
    audit = perception_axis_audit(errors)
    status, reasons = reachability_gate(envelope, audit)
    payload = {
        "schema_version": "M1BPerceptionReachabilityGateV1",
        "status": status,
        "reasons": list(reasons),
        "tolerance_envelope_m": envelope,
        "perception_axis_audit_m": audit,
        "criterion": "per_axis_p90_m <= 0.6 * measured_tolerance_m",
        "truth_boundary": "tolerance truth is calibration_only; perception truth is offline_evaluation_only",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "reasons": payload["reasons"]}))
    return 0 if status == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
