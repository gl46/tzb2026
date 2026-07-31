#!/usr/bin/env python3
"""Merge the 13 isolated S0 runs and fail closed on incomplete evidence."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


EXPECTED_LABELS = [
    "left_1", "left_2", "left_3",
    "right_1", "right_2", "right_3",
    "bilateral_1", "bilateral_2", "bilateral_3",
    "object_environment_1", "object_environment_2", "table_1", "table_2",
]


def expected_kind(label: str) -> str:
    if label.startswith("left_"):
        return "left"
    if label.startswith("right_"):
        return "right"
    if label.startswith("bilateral_"):
        return "bilateral"
    if label.startswith("object_environment_"):
        return "target_equivalent_table_without_finger"
    if label.startswith("table_"):
        return "finger_table"
    raise ValueError(f"unknown calibration label: {label}")


def synthetic_failure(label: str, reason: str) -> dict:
    return {
        "label": label,
        "expected": expected_kind(label),
        "passed": False,
        "reason": reason,
    }


def structured_payload(path: Path) -> dict | None:
    raw = path.read_text(errors="replace") if path.exists() else ""
    for line in raw.splitlines():
        if line.startswith("{") and '"trials"' in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


def remote_hashes(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.split(":", 1)[1].strip()
        for line in path.read_text(errors="replace").splitlines()
        if line.startswith("REMOTE_GAZEBO_URDF_SHA256:")
    ]


def main() -> int:
    run_id, *log_names = sys.argv[1:]
    if not run_id or not log_names:
        raise SystemExit("usage: aggregate_isolated_contact_calibration.py RUN_ID LOG...")

    logs = [Path(name) for name in log_names]
    local_sha = hashlib.sha256(
        Path("robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_bytes()
    ).hexdigest()
    trials_by_label: dict[str, dict] = {}
    idle_sessions: list[dict] = []
    anomalies: list[str] = []
    all_remote_hashes: list[str] = []

    for log in logs:
        all_remote_hashes.extend(remote_hashes(log))
        payload = structured_payload(log)
        if payload is None:
            anomalies.append(f"MISSING_STRUCTURED_EVIDENCE:{log}")
            continue
        for trial in payload.get("trials", []):
            label = trial.get("label")
            if label == "idle":
                # Independent sessions naturally have different timestamps and
                # event counts.  Keep every baseline and require each to pass;
                # equality of their raw telemetry would be the wrong invariant.
                idle_sessions.append(trial)
                continue
            if label not in EXPECTED_LABELS:
                anomalies.append(f"UNEXPECTED_TRIAL_LABEL:{label}:{log}")
                continue
            if label in trials_by_label:
                anomalies.append(f"DUPLICATE_TRIAL_LABEL:{label}:{log}")
                continue
            trials_by_label[label] = trial

    if not idle_sessions:
        idle_sessions = [{
            "label": "idle",
            "expected": "none",
            "passed": False,
            "reason": "MISSING_IDLE_EVIDENCE",
        }]
        anomalies.append("MISSING_IDLE_EVIDENCE")

    trials = []
    for label in EXPECTED_LABELS:
        trials.append(
            trials_by_label.get(label, synthetic_failure(label, "MISSING_ISOLATED_CONDITION_EVIDENCE"))
        )
    missing_labels = [label for label in EXPECTED_LABELS if label not in trials_by_label]
    if missing_labels:
        anomalies.append("MISSING_CONDITION_LABELS:" + ",".join(missing_labels))
    if len(logs) != len(EXPECTED_LABELS):
        anomalies.append(f"EXPECTED_13_SOURCE_LOGS_GOT_{len(logs)}")

    model_match = (
        len(all_remote_hashes) == len(EXPECTED_LABELS)
        and all(remote_sha == local_sha for remote_sha in all_remote_hashes)
    )
    if not model_match:
        anomalies.append("URDF_HASH_MISMATCH_OR_MISSING_REMOTE_HASH")

    idle = idle_sessions[0]
    combined = [idle, *trials]
    positives = [trial for trial in trials if trial["expected"] in {"left", "right", "bilateral"}]
    passed_positives = sum(bool(trial.get("passed")) for trial in positives)
    calibrated = (
        not anomalies
        and all(bool(trial.get("passed")) for trial in idle_sessions)
        and all(bool(trial.get("passed")) for trial in trials)
    )
    status = "CONTACT_TELEMETRY_CALIBRATED" if calibrated else "CONTACT_TELEMETRY_PARTIAL"
    reason = (
        f"{sum(bool(trial.get('passed')) for trial in trials)}/13 approved conditions passed; "
        f"{passed_positives}/9 finger-target positive windows passed; "
        f"idle baselines passed {sum(bool(trial.get('passed')) for trial in idle_sessions)}/{len(idle_sessions)}."
    )
    if anomalies:
        reason += " Gate anomalies: " + "; ".join(anomalies) + "."

    data = {
        "run_id": run_id,
        "status": status,
        "reason": reason,
        "oracle_pose_source": "gz model runtime query before every motion trial",
        "listener_scope": "PER_TRIAL_FULL_ACTION_WINDOW",
        "session_isolation": "FRESH_GAZEBO_MOVEIT_SESSION_PER_CONDITION",
        "source_logs": [str(log) for log in logs],
        "source_log_count": len(logs),
        "local_gazebo_urdf_sha256": local_sha,
        "remote_gazebo_urdf_sha256": all_remote_hashes,
        "model_match": model_match,
        "aggregation_anomalies": anomalies,
        "idle_session_count": len(idle_sessions),
        "idle_sessions_all_passed": all(bool(trial.get("passed")) for trial in idle_sessions),
        "idle_evidence_by_session": idle_sessions,
        "calibration_trials_completed": len(trials_by_label),
        "trials": combined,
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/m1a-contact-calibration.json").write_text(json.dumps(data, indent=2) + "\n")
    Path("reports/m1a-contact-calibration.md").write_text(
        "# M1A S0 contact telemetry calibration\n\n"
        f"- Status: `{status}`\n- Reason: {reason}\n"
        f"- Completed isolated condition trials: `{len(trials_by_label)}/13`\n"
        f"- Model match: `{model_match}`; local URDF SHA-256: `{local_sha}`\n"
        "- Each condition used a fresh Gazebo/MoveIt session; every source log is listed in JSON.\n"
        "- No grasp is claimed by this calibration audit.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
