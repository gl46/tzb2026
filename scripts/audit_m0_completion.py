"""Evidence-only audit of the explicit M0-R completion conditions."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def load(name: str) -> dict[str, object]:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> int:
    report = load("m0-rebaseline-status.json")
    constrained = load("p0-constrained-pick-place-status.json")
    failures = load("p0-empty-grasp-failures.json")
    release_delay = load("p0-release-delay-failure.json")
    checks = {
        "rebaseline_adr": (ROOT / "docs/decisions/ADR-0000-rebaseline-project-priorities.md").is_file(),
        "agents_p0_policy": (ROOT / "AGENTS.md").is_file(),
        "super_parked": report["p2_status"] == "PARKED",
        "student_sim_only_boundary": (ROOT / "src/xh_agent/world_state/student.py").is_file(),
        "schemas_and_tests": report["validation"]["schema_validation"] == "PASS",
        "both_remote_doctors": set(report["platform"]["remote_doctor"]) == {"node2", "chxy"},
        "robot_workspace": (ROOT / "robot_ws/src/xh_sim/worlds/p0_pick_place.sdf").is_file(),
        "p0_control_perception": (
            report["simulation_smoke_test"]["status"] == "VERIFIED_CONSTRAINED_P0_GATE"
            and report["simulation_smoke_test"]["initial_control_perception_smoke_status"]
            == "PARTIAL_CONTROL_AND_PERCEPTION_VERIFIED"
            and report["simulation_smoke_test"]["pick_place_completed"] is True
            and report["simulation_smoke_test"]["episode_recorded"] is True
        ),
        "p0_constrained_pick_place": constrained["status"] == "VERIFIED_CONSTRAINED_PICK_PLACE",
        "episode_recorded": constrained["episode_recorded"] is True,
        "contact_supervision": constrained["object_contact_supervision_observed"] is True,
        "twenty_actual_failures": failures["status"] == "VERIFIED_20_EMPTY_GRASP_FAILURE_TRAJECTORIES" and failures["count"] >= 20,
        "second_actual_failure": release_delay["status"] == "VERIFIED_RELEASE_DELAY_FAILURE",
        "b1_entry": report["baseline_b1"]["status"] == "READY",
        "teacher_audit": report["teacher"]["metadata_audit"].get("metadata_only") is True and len(report["teacher"]["metadata_audit"].get("models", {})) == 3,
        "no_teacher_p0_block": report["teacher"]["blocks_p0"] is False,
        "full_test_validation": report["validation"]["pytest"].startswith("PASS") and report["validation"]["ruff"] == "PASS",
    }
    passed = all(checks.values())
    result = {
        "status": "PASS" if passed else "PARTIAL",
        "checks": checks,
        "limitations": [
            "P0 grasp is a labelled Gazebo DetachableJoint constraint, not verified frictional finger contact.",
            "The controller robot is a primitive-inertia, collision-simplified Panda-compatible model.",
        ],
    }
    (REPORTS / "m0-completion-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# M0-R completion audit", "", f"- Status: **{result['status']}**", ""]
    lines.extend(f"- {name}: **{value}**" for name, value in checks.items())
    lines.extend(["", "## Scoped limitations", *[f"- {item}" for item in result["limitations"]]])
    (REPORTS / "m0-completion-audit.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": result["status"], "checks": len(checks)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
