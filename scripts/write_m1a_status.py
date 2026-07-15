"""Compose M1A's honest final status from stage reports without changing M0 evidence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "reports" / name).read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    run_id = sys.argv[1]
    preflight = load("m1a-preflight.json")
    m0 = load("m1a-m0-smoke.json")
    s0 = load("m1a-contact-calibration.json")
    s1 = load("m1a-motion-execution.json")
    s2 = load("m1a-friction-trials.json")
    s3 = load("m1a-contact-gate.json")
    s4 = load("m1a-b1-oracle.json")
    status = "BLOCKED" if s1["motion_status"] == "BLOCKED" else "PARTIAL"
    report_files = [
        ROOT / "reports" / name
        for name in (
            "m1a-preflight.json", "m1a-m0-smoke.json", "m1a-contact-calibration.json", "m1a-motion-execution.json",
            "m1a-friction-trials.json", "m1a-contact-gate.json", "m1a-b1-oracle.json",
        )
    ]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    data = {
        "phase": "M1A", "run_id": run_id, "baseline_commit": "22ce578",
        "execution_baseline_commit": preflight["execution_baseline"], "baseline_branch": preflight["branch"],
        "baseline_origin_match": preflight["baseline_origin_match"], "m0_tag_status": preflight["m0_tag_status"],
        "started_at": preflight["started_at"], "completed_at": datetime.now(timezone.utc).isoformat(),
        "deadline": "2026-07-18T23:59:00+08:00", "status": status,
        "m0_reproducible": m0["m0_constrained_transfer_reproduced"],
        "m0_baseline_pytest_passed": 24, "m1a_current_pytest_passed": int(os.environ.get("M1A_PYTEST_PASSED", "0")),
        "m1a_current_pytest_failed": int(os.environ.get("M1A_PYTEST_FAILED", "0")),
        "approach_pose_source": "HARD_CODED_JOINT_TARGET", "contact_telemetry_status": s0["status"],
        "motion_status": s1["motion_status"], "motion_trials": s1["motion_trials"],
        "motion_successes": s1["motion_successes"], "anti_teleport_verified_trials": s1["anti_teleport_verified_trials"],
        "frictional_trials": s2["frictional_trials"], "frictional_successes": s2["frictional_successes"],
        "friction_failure_counts": s2["failure_counts"], "grasp_status": "BLOCKED",
        "contact_gated_trials": s3["contact_gated_trials"], "contact_gated_successes": s3["contact_gated_successes"],
        "release_verified_count": s3["release_verified_count"], "b1_status": s4["status"],
        "b1_trials": s4["b1_trials"], "b1_successes": s4["b1_successes"], "episodes_recorded": 0,
        "video_status": "VIDEO_NOT_AVAILABLE_NONBLOCKING", "teacher_blocked_m1a": False,
        "limitations": [s0["reason"], s1["reason"]], "blockers": preflight["blockers"] + [s1["motion_status"]],
        "next_command": "bash scripts/run_moveit_execution_gate.sh", "code_revision": revision,
    }
    (ROOT / "reports" / "m1a-runtime-grasp-status.json").write_text(json.dumps(data, indent=2) + "\n")
    (ROOT / "reports" / "m1a-runtime-grasp-status.md").write_text(
        "# M1A runtime grasp status\n\n"
        f"- Overall: `{status}`\n- S0: `{s0['status']}`\n- S1: `{s1['motion_status']}`\n"
        "- S2/S3/S4 were not started: S1 lacks verified MoveIt execution.\n"
        "- Teacher did not block M1A. `READY_FOR_M1B=false`.\n"
    )
    (ROOT / "reports" / "m1a-completion-audit.md").write_text(
        "# M1A completion audit\n\n"
        "M1A is not complete: no same-URDF MoveIt-to-Gazebo execution evidence exists, so no grasp or B1 result is claimed.\n"
    )
    manifest = {
        "schema_version": "m1a-runtime-grasp-v1", "run_id": run_id, "baseline_commit": "22ce578",
        "working_revision_or_diff_hash": revision, "episode_ids": [], "seeds": [], "mode": None,
        "motion_trials": 0, "motion_successes": 0, "frictional_trials": 0,
        "contact_gated_trials": 0, "b1_oracle_trials": 0,
        "file_hashes": {str(path.relative_to(ROOT)): digest(path) for path in report_files},
    }
    (ROOT / "data/manifests/m1a-runtime-grasp-v1.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
