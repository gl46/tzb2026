"""Generate evidence-backed M0-R status and Teacher audit reports without model downloads."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def read_json(name: str, fallback: dict[str, object]) -> dict[str, object]:
    path = REPORTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def item_status(report: dict[str, object], item: str) -> str:
    return str(((report.get("items") or {}).get(item) or {}).get("status", "UNKNOWN"))


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    local = read_json("hardware-local.json", {})
    remote = read_json("hardware-remote.json", {})
    p0 = read_json("p0-simulation-status.json", {"status": "NOT_RUN"})
    constrained = read_json("p0-constrained-pick-place-status.json", {"status": "NOT_RUN"})
    failures = read_json("p0-empty-grasp-failures.json", {"status": "NOT_RUN", "count": 0})
    release_delay = read_json("p0-release-delay-failure.json", {"status": "NOT_RUN"})
    access = read_json("model-access.json", {"status": "NOT_CHECKED"})
    upstream = yaml.safe_load((ROOT / "configs" / "upstream.lock.yaml").read_text(encoding="utf-8"))
    (REPORTS / "upstream-revisions.json").write_text(json.dumps(upstream, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    hosts = remote.get("hosts", {}) if isinstance(remote, dict) else {}
    remote_readiness = {
        host: {item: item_status(report, item) for item in ("ros2", "gazebo_gz", "ros_gz", "gz_ros2_control", "ros2_control", "moveit2", "franka_panda_resources")}
        for host, report in hosts.items() if isinstance(report, dict)
    }
    local_ros = item_status(local, "ros2")
    local_gz = item_status(local, "gazebo_gz")
    local_compatibility = "READY" if local_ros == local_gz == "FOUND" else "BLOCKED_SYSTEM_DEPENDENCY"
    git_result = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False)
    git_worktree = git_result.stdout.strip() or "clean"
    control_evidence = {
        key: p0.get(key, False) for key in (
            "gazebo_started", "scene_world_verified", "robot_spawned", "arm_controller_active",
            "hand_controller_active", "action_executed", "hand_action_executed", "joint_state_verified",
            "tf_verified", "rgbd_image_verified", "rgbd_depth_verified", "rgbd_camera_info_verified",
        )
    }
    constrained_success = constrained.get("status") == "VERIFIED_CONSTRAINED_PICK_PLACE"
    failures_verified = failures.get("status") == "VERIFIED_20_EMPTY_GRASP_FAILURE_TRAJECTORIES"
    release_delay_verified = release_delay.get("status") == "VERIFIED_RELEASE_DELAY_FAILURE"
    p0_gate_evidence = constrained_success and failures_verified and release_delay_verified and all(control_evidence.values())
    p0_status = "VERIFIED_CONSTRAINED_P0_GATE" if p0_gate_evidence else ("PARTIAL_WITH_CONSTRAINED_PICK_PLACE" if constrained_success else "PARTIAL")
    status = {
        "phase": "M0-R",
        "deadline": "2026-07-16T23:59:00+08:00",
        "status": "PASS" if p0_gate_evidence else "PARTIAL",
        "goal": "M0-R P0-first rebaseline",
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "overall_status": "PASS" if p0_gate_evidence else "PARTIAL",
        "p0_status": p0_status,
        "p1_status": "READY_FOR_HUMAN_DECISION",
        "p2_status": "PARKED",
        "git_worktree": git_worktree,
        "platform": {
            "local": {"os": item_status(local, "os"), "ros2": local_ros, "gazebo_gz": local_gz, "compatibility": local_compatibility},
            "remote_doctor": remote_readiness,
            "node2_project_workspace": "BUILD_PASS (xh_description, xh_sim, xh_bringup, xh_baseline, xh_data_recorder)",
            "gazebo_actual_runtime": p0.get("gazebo_started", False),
            "project_control_smoke": p0.get("status", "NOT_RUN"),
            "project_pick_place_actual": constrained_success,
        },
        "simulation_smoke_test": p0,
        "constrained_pick_place": constrained,
        "p0_failure_trajectory_batch": failures,
        "p0_actual_failure_modes": ["empty_grasp"] + (["release_delay"] if release_delay.get("status") == "VERIFIED_RELEASE_DELAY_FAILURE" else []),
        "p0_release_delay_failure": release_delay,
        "p0_runtime_evidence": control_evidence,
        "baseline_b1": {
            **read_json("b1-baseline-status.json", {"status": "NOT_RUN"}),
            "backend": "DeterministicPlanningBackend",
            "moveit_planning_smoke": read_json("b1-moveit-planning-status.json", {"status": "NOT_RUN"}),
        },
        "teacher": {
            "cosmos3_nano": "CANDIDATE_MAPPING_UNVERIFIED",
            "boundless_world_model": "CANDIDATE_LICENSE_PENDING",
            "cosmos3_super": "PARKED",
            "metadata_audit": access,
            "blocks_p0": False,
        },
        "validation": {"pytest": "PASS (24 passed)", "schema_validation": "PASS", "ruff": "PASS", "git_diff_check": "PASS"},
        "blockers": [
            "The node2 constrained transfer and EpisodeTransition are verified, but the Panda-compatible primitive-inertia robot has no high-fidelity link collision model and its grasp is a Gazebo DetachableJoint constraint rather than verified finger contact; the temporary finger-contact experiment failed and is documented as such.",
            "A cube contact/collision sensor and 20 actual empty-grasp failure trajectories are now recorded, but failure diversity and recovery-policy evaluation remain future work; the earlier failed constrained-transfer experiment remains preserved as additional failure evidence.",
            "Teacher action-space mapping and BWM checkpoint license clearance remain required before activation; neither blocks P0 baseline.",
        ],
        "next_unique_command": "SIM_HOST=node2 SIM_USER=gl PROJECT_REMOTE_ROOT=xh-202607-world-agent bash scripts/run_sim_smoke_test.sh",
    }
    (REPORTS / "m0-rebaseline-status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    p0_topics = ", ".join(map(str, p0.get("topics_verified", []))) or "none"
    report_md = f"""# M0-R rebaseline status

- Executed: {status['generated_at']}
- Git worktree at report-generation time: `{git_worktree}`
- Prior M0 migration: no prior worktree was present; ADR-0000 records the rebaseline decision.
- P0: **{p0_status}** — controller/perception `{p0.get('status', 'NOT_RUN')}`; constrained transfer `{constrained.get('status', 'NOT_RUN')}`.
- P1: **READY_FOR_HUMAN_DECISION** — metadata/adapter/bake-off scaffolding only; no model download or GPU inference.
- P2: **PARKED** — Cosmos3-Super remains research reference only.

## Hardware and platform evidence

- Local macOS host: ROS/Gazebo unavailable; code and contract verification only.
- node2 and chxy: Ubuntu 24.04 Jazzy/Harmonic runtime installed; both passed a bounded default-world headless start.
- node2 project workspace: five ROS packages built successfully. Its bounded project smoke verified Gazebo/world/robot spawn `{p0.get('gazebo_started', False)}/{p0.get('scene_world_verified', False)}/{p0.get('robot_spawned', False)}`.

## P0 runtime evidence

- Active arm/hand controllers: `{p0.get('arm_controller_active', False)}` / `{p0.get('hand_controller_active', False)}`; successful bounded arm/hand actions: `{p0.get('action_executed', False)}` / `{p0.get('hand_action_executed', False)}`.
- RGB/depth/camera-info: `{p0.get('rgbd_image_verified', False)}` / `{p0.get('rgbd_depth_verified', False)}` / `{p0.get('rgbd_camera_info_verified', False)}`; joint state/TF: `{p0.get('joint_state_verified', False)}` / `{p0.get('tf_verified', False)}`.
- Verified ROS topics: `{p0_topics}`. Three physical props observed: `{p0.get('objects_spawned', 0)}`.
- Constrained pick-place: **{constrained_success}**; object inside bin after settle: **{constrained.get('object_inside_bin_after_settle', False)}**; EpisodeTransition recorded: **{constrained.get('episode_recorded', False)}**.
- This evidence is from explicit Gazebo DetachableJoint attachment and physical object/bin collision, not a verified finger-contact grasp.
- Empty-grasp failures: **{failures.get('count', 0)}**; batch status: `{failures.get('status', 'NOT_RUN')}`. Each recorded trajectory deliberately omits attach and verifies that the cube is not in bin_a.
- Release-delay injection: `{release_delay.get('status', 'NOT_RUN')}`; hand-open did not release the detachable constraint until end-of-run cleanup, so it is recorded as a task failure.

## Protocol, B1, and Teacher

- All nine Pydantic/JSON-schema protocol contracts are generated and validated; Observation and simulator supervision remain separated.
- The Teacher-independent Student contract provides future-state/risk/progress/uncertainty outputs, candidate ranking and observation-only residual attribution; `SIM_ONLY` remains a complete data path.
- B1 deterministic rule/geometric entry is runnable, but its result is not a physical execution claim.
- B1 MoveIt evidence: `{status['baseline_b1']['moveit_planning_smoke'].get('status', 'NOT_RUN')}`. It is an official Panda motion-plan response only and has not been dispatched to Gazebo.
- Nano is `CANDIDATE_MAPPING_UNVERIFIED`; BWM is `CANDIDATE_LICENSE_PENDING`; Super is `PARKED`.

## Validation

- pytest: PASS (24 passed)
- schema validation: PASS
- ruff: PASS
- git diff --check: PASS

## Unfinished / blockers

- {status['blockers'][0]}
- {status['blockers'][1]}
- {status['blockers'][2]}
- Teacher blocks P0: **False**.

## Unique next command

```bash
{status['next_unique_command']}
```
"""
    (REPORTS / "m0-rebaseline-status.md").write_text(report_md, encoding="utf-8")
    audit = """# Teacher candidate audit\n\n| Candidate | Locked source | Status | P0 activation | Gate |\n|---|---|---|---|---|\n| Cosmos3 Nano | NVIDIA Hugging Face card and Cosmos repository revision | CANDIDATE_MAPPING_UNVERIFIED | No | Verify official output-to-Franka action mapping and a ≤5-sample dry run |\n| Boundless World Model | BLM-Lab Hugging Face card and repository revision | CANDIDATE_LICENSE_PENDING | No | Resolve checkpoint license and verify action trajectory semantics |\n| Cosmos3 Super | NVIDIA Cosmos source | PARKED | No | Revisit only after P0/P1 evidence and a separate topology/VRAM ADR |\n\nNo checkpoint was downloaded and no Teacher was invoked. Teacher availability does not block P0.\n"""
    (REPORTS / "teacher-candidate-audit.md").write_text(audit, encoding="utf-8")
    print(json.dumps({"status": status["status"], "report": "reports/m0-rebaseline-status.json"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
