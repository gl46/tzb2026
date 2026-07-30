#!/usr/bin/env python3
"""Offline-only S0-style M1B tolerance versus perception reachability gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.grasp.tolerance_envelope import perception_axis_audit, reachability_gate


def measured_tolerance_envelope(payload: dict[str, object]) -> dict[str, float | None]:
    """Accept only the complete, immutable 81-trial campaign summary.

    The first version of this tool accepted a legacy list of synthetic
    ``OffsetTrialV1`` records.  The real campaign instead emits a signed,
    monotonic summary after validating every raw record against its immutable
    worklist.  Recomputing from a lossy summary would both fail on its schema
    and weaken that validation boundary.
    """
    accepted_schemas = {
        "M1BToleranceEnvelopeV1",
        # ADR-0016's fallback-hand campaign preserves the same required
        # status/count/envelope contract but carries hand-model provenance in
        # its measured-evidence V2 schema. Treating it as a format error
        # would incorrectly prevent the unchanged p90 comparison.
        "M1BADR0016ToleranceEnvelopeEvidenceV2",
    }
    if payload.get("schema_version") not in accepted_schemas:
        raise ValueError("tolerance evidence has an unsupported measured-envelope schema")
    if payload.get("status") != "COMPLETE_CALIBRATION_ONLY":
        raise ValueError("tolerance campaign is not complete")
    if payload.get("trial_count") != 81:
        raise ValueError("tolerance campaign must contain exactly 81 trials")
    envelope = payload.get("tolerance_envelope_m")
    if not isinstance(envelope, dict) or set(envelope) != {"x", "y", "z"}:
        raise ValueError("tolerance campaign has invalid per-axis envelope")
    return {
        axis: None if envelope[axis] is None else float(envelope[axis])
        for axis in ("x", "y", "z")
    }


def actual_perception_errors(payload: dict[str, object]) -> list[tuple[float, float, float]]:
    """Reject manifest-only perception evidence before calculating p90."""
    if payload.get("status") != "ACTUAL_GAZEBO_RGBD_FRAMES_EVALUATED":
        raise ValueError("perception evidence is not an actual Gazebo RGB-D evaluation")
    matches = payload.get("matches")
    if not isinstance(matches, list) or not matches:
        raise ValueError("perception evidence contains no matched RGB-D tracks")
    return [tuple(float(value) for value in record["error_world_xyz_m"]) for record in matches]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tolerance-trials", required=True, type=Path)
    parser.add_argument("--perception-errors", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw_trials = json.loads(args.tolerance_trials.read_text(encoding="utf-8"))
    raw_errors = json.loads(args.perception_errors.read_text(encoding="utf-8"))
    envelope = measured_tolerance_envelope(raw_trials)
    errors = actual_perception_errors(raw_errors)
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
