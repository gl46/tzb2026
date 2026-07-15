# M0-R rebaseline status

- Executed: 2026-07-16T00:41:13.523955+08:00
- Git worktree at report-generation time: `M reports/p0-simulation-status.json
 M reports/p0-simulation-status.md
 M scripts/audit_m0_completion.py`
- Prior M0 migration: no prior worktree was present; ADR-0000 records the rebaseline decision.
- P0: **VERIFIED_CONSTRAINED_P0_GATE** — controller/perception `VERIFIED_CONSTRAINED_P0_GATE`; constrained transfer `VERIFIED_CONSTRAINED_PICK_PLACE`.
- P1: **READY_FOR_HUMAN_DECISION** — metadata/adapter/bake-off scaffolding only; no model download or GPU inference.
- P2: **PARKED** — Cosmos3-Super remains research reference only.

## Hardware and platform evidence

- Local macOS host: ROS/Gazebo unavailable; code and contract verification only.
- node2 and chxy: Ubuntu 24.04 Jazzy/Harmonic runtime installed; both passed a bounded default-world headless start.
- node2 project workspace: five ROS packages built successfully. Its bounded project smoke verified Gazebo/world/robot spawn `True/True/True`.

## P0 runtime evidence

- Active arm/hand controllers: `True` / `True`; successful bounded arm/hand actions: `True` / `True`.
- RGB/depth/camera-info: `True` / `True` / `True`; joint state/TF: `True` / `True`.
- Verified ROS topics: `/joint_states, /tf, /xh/camera/rgbd/image, /xh/camera/rgbd/depth_image, /xh/camera/rgbd/camera_info`. Three physical props observed: `3`.
- Constrained pick-place: **True**; object inside bin after settle: **True**; EpisodeTransition recorded: **True**.
- This evidence is from explicit Gazebo DetachableJoint attachment and physical object/bin collision, not a verified finger-contact grasp.
- Empty-grasp failures: **20**; batch status: `VERIFIED_20_EMPTY_GRASP_FAILURE_TRAJECTORIES`. Each recorded trajectory deliberately omits attach and verifies that the cube is not in bin_a.
- Release-delay injection: `VERIFIED_RELEASE_DELAY_FAILURE`; hand-open did not release the detachable constraint until end-of-run cleanup, so it is recorded as a task failure.

## Protocol, B1, and Teacher

- All nine Pydantic/JSON-schema protocol contracts are generated and validated; Observation and simulator supervision remain separated.
- The Teacher-independent Student contract provides future-state/risk/progress/uncertainty outputs, candidate ranking and observation-only residual attribution; `SIM_ONLY` remains a complete data path.
- B1 deterministic rule/geometric entry is runnable, but its result is not a physical execution claim.
- B1 MoveIt evidence: `VERIFIED_MOTION_PLAN_ONLY`. It is an official Panda motion-plan response only and has not been dispatched to Gazebo.
- Nano is `CANDIDATE_MAPPING_UNVERIFIED`; BWM is `CANDIDATE_LICENSE_PENDING`; Super is `PARKED`.

## Validation

- pytest: PASS (24 passed)
- schema validation: PASS
- ruff: PASS
- git diff --check: PASS

## Unfinished / blockers

- The node2 constrained transfer and EpisodeTransition are verified, but the Panda-compatible primitive-inertia robot has no high-fidelity link collision model and its grasp is a Gazebo DetachableJoint constraint rather than verified finger contact; the temporary finger-contact experiment failed and is documented as such.
- A cube contact/collision sensor and 20 actual empty-grasp failure trajectories are now recorded, but failure diversity and recovery-policy evaluation remain future work; the earlier failed constrained-transfer experiment remains preserved as additional failure evidence.
- Teacher action-space mapping and BWM checkpoint license clearance remain required before activation; neither blocks P0 baseline.
- Teacher blocks P0: **False**.

## Unique next command

```bash
SIM_HOST=node2 SIM_USER=gl PROJECT_REMOTE_ROOT=xh-202607-world-agent bash scripts/run_sim_smoke_test.sh
```
