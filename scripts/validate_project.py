from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from xh_agent.contracts.models import CONTRACT_MODELS  # noqa: E402


REQUIRED = [
    "AGENTS.md", "README.md", "LICENSES.md", ".gitignore", ".env.example", "pyproject.toml", "Makefile",
    "configs/project.example.yaml", "configs/platform-detected.yaml", "configs/nodes.example.yaml",
    "configs/teacher-candidates.yaml", "configs/teacher-bakeoff.example.yaml", "configs/upstream.lock.yaml",
    "docs/decisions/ADR-0000-rebaseline-project-priorities.md", "docs/decisions/ADR-0004-ros-gazebo-platform.md",
    "docs/legal/bwm-license-inquiry-draft.md", "scripts/doctor_local.sh", "scripts/doctor_remote.sh",
    "scripts/run_sim_smoke_test.sh", "scripts/run_pick_place_baseline.sh", "scripts/download_teacher_candidate.sh",
    "scripts/run_moveit_planning_smoke.sh",
    "configs/m1a_execution_gate.yaml", "configs/m1a_contact_gate.yaml", "configs/m1a_friction_trials.yaml",
    "scripts/run_m1a_preflight.sh", "scripts/run_contact_calibration.sh", "scripts/run_moveit_execution_gate.sh",
    "scripts/run_friction_grasp_trials.sh", "scripts/run_contact_gated_grasp.sh", "scripts/run_b1_oracle_gate.sh",
    "scripts/run_m1a_validation.sh", "scripts/write_m1a_status.py",
    "scripts/run_m1a_m0_smoke.sh",
    "scripts/sample_panda_fk_workspace.py",
]


def main() -> int:
    root = Path(__file__).parents[1]
    missing = [name for name in REQUIRED if not (root / name).exists()]
    schema_errors = []
    for filename in CONTRACT_MODELS:
        path = root / "schemas" / filename
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # verification needs concise diagnostics
            schema_errors.append(f"{filename}: {exc}")
    yaml.safe_load((root / "configs" / "teacher-candidates.yaml").read_text(encoding="utf-8"))
    importlib.import_module("xh_agent")
    if missing or schema_errors:
        print(json.dumps({"status": "FAIL", "missing": missing, "schema_errors": schema_errors}))
        return 1
    print(json.dumps({"status": "PASS", "schemas": len(CONTRACT_MODELS), "root_import": "CPU_ONLY"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
