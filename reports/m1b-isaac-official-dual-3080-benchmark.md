# M1B migration to Isaac Sim 6.0.1

Date: 2026-07-29 (Asia/Shanghai)

Status: **MIGRATION PASS, with dynamic-visibility limitations retained**

This report closes the requested M1B Isaac migration scope: official robot
assets, source-bound task geometry, native contact/attach/reset, a complete
Isaac tolerance envelope, dual-RTX real-frame dataset generation,
Teacher-free transition assembly, and an independent static RGB-D perception
gate. It does not replace the already-accepted Gazebo M1B-beta evidence, and it
does not claim that the current public detector has production-grade recall in
long dynamic sequences.

The machine-readable summary is
`reports/m1b-isaac-migration-evidence.json`.

## Result summary

| Gate | Result | Measured evidence |
|---|---|---|
| Official robot asset | **PASS** | Isaac 6 official Franka Panda USD; `Gripper=Default`, `Mesh=Performance`; local simplified robot `false` |
| Physics-stage translation | **PASS** | source-bound 30 mm cylinders, table and bin; clean stage SHA-256 `4ead233e…facfa23a` |
| Native contact/attach/release | **PASS** | 3/3 fresh stages across upright and inverted cylinders |
| Same-process physical reset | **PASS** | hand jog 28.393 mm, all objects 0 mm, attachment absent |
| 81-trial tolerance campaign | **PASS** | 81/81 valid; X/Y/Z envelope = 10/15/10 mm |
| Dual RTX 3080 dataset benchmark | **PASS** | 2 workers × 100 steps × 4 cameras = 800 sensor frames; 12.62695 sensor-frames/s |
| Teacher-free transition protocol | **PASS** | `TeacherResponse` non-null = 0; policy segmentation URI non-null = 0 |
| Independent static RGB-D gate | **GO** | p90 X/Y/Z = 5.381/2.162/3.802 mm versus 6/9/6 mm limits |
| Dynamic five-scene diagnostic | **NO_GO retained** | 8.931/21.420/13.124 mm; unsupported tilted cylinders roll during the sequence |
| Local verification | **PASS** | scoped Ruff, `git diff --check`, 163 tests, `validate_project` |

## Official-asset boundary

- Isaac image: `nvcr.io/nvidia/isaac-sim:6.0.1`.
- Robot:
  `Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd`.
- Provenance:
  `NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD`.
- Selected official variants:
  `Gripper=Default`, `Mesh=Performance`.
- Every Isaac robot visual, collision, articulation, joint and finger shape is
  composed from NVIDIA's official USD. No locally authored or simplified
  robot geometry is referenced into the stage.
- `panda_controlled.urdf` is only the hash-bound action/base-pose contract. It
  does not provide Isaac visual or collision geometry.
- Task cylinders, table, incoming markings and partition bin remain tied to
  the accepted M1B SDF. Cylinder radius is 15 mm and length is 80 mm.

The clean render-free physics stage is:

- `/var/tmp/m1b-isaac-production-parity-stage-build-20260729/output/m1b_physics_scene.usdc`
- SHA-256
  `4ead233e4e9b4f84b64eee262f4bb91931590409c2bb737ea7ee37a4facfa23a`
- size 9,974,959 bytes
- official robot base pose `(-0.35, 0.0, 0.45)` m
- local simplified robot geometry `false`
- render products in this physical layer: none

## Native contact, attach and reset

The native probe uses the official USD's driven
`panda_finger_joint1`, authored PhysX mimic, official finger collisions, and
the unchanged ADR-0013 broker rule: at least three samples and at least
100 ms of bilateral contact with the same entity.

Three fresh-stage runs passed:

1. `cylinder_01`: 227 paired bilateral samples over 3.7667 s,
   164.727 mm lift, 1.072 mm hand/object follow error.
2. Upright `cylinder_04`: 229 samples over 3.8 s, 163.443 mm lift,
   1.928 mm follow error, 0.00003 mm detached motion.
3. Inverted `cylinder_02`: 178 samples over 2.95 s, 166.917 mm lift,
   1.137 mm follow error, 0.004773 mm detached motion.

Evidence SHA-256 values are respectively:

- `a3bd1c87769898f6769c8d20a7afa0abdedf7cb67da956284dd89accf38843f7`
- `005dee57dba9a3487728ee89859d3ee12c707f8181127809cc149f44c65390b2`
- `f696f715994c133cdbaf52933ccbd90113dc33c0ce9df7d140eb72d2db37f508`

The production-parity same-process reset also passed. After the required
settling window, maximum quiet displacement was 0.001947 mm; the production
IK jog moved the hand 28.393 mm while every object moved 0 mm. The attachment
prim was absent before and after the jog. Evidence:

- `/var/tmp/m1b-isaac-production-parity-cylinder_04-reset-h-20260729/actuation-probe.json`
- SHA-256
  `bc08bbf74b94af727dd11f082098c236949bd38c890f365bc9a904e70e981df1`

## Complete tolerance envelope

The official `Default` hand completed the immutable 81-trial,
calibration-only campaign:

- evidence:
  `/var/tmp/m1b-isaac-tolerance-production-parity-r3-20260729/m1b-isaac-tolerance-envelope.json`
- status: `COMPLETE_CALIBRATION_ONLY`
- valid/expected trials: 81/81
- envelope X/Y/Z: `0.010 / 0.015 / 0.010 m`
- envelope SHA-256:
  `25e3c99f01de176e5d646a01d03b23a8717f6966ebd685c33003447274b4b9ff`
- worklist SHA-256:
  `3bd0bf6427fc797ea8a4fd829a9972bcd37db31b2efc3dbe11df2837b5d9f904`
- local simplified robot used: `false`

## Dual RTX 3080 real-frame benchmark

The final throughput run serialized Kit initialization and then released both
workers through a shared START barrier. Each worker used one physical RTX
3080, 100 capture steps and four 640×480 cameras. Every camera wrote RGB,
metric distance-to-image-plane depth, semantic segmentation and instance
segmentation.

| Metric | GPU 0 / worker 0 | GPU 1 / worker 1 |
|---|---:|---:|
| Sensor frames | 400 | 400 |
| Benchmark wall time | 63.356548 s | 62.848260 s |
| Sensor frames/s | 6.313475 | 6.364536 |
| Peak VRAM | 2635 MiB | 2495 MiB |
| Peak GPU utilization | 67% | 67% |
| Peak power | 102.97 W | 123.36 W |

Combined:

- 800 sensor frames in 63.356548 s
- 12.626950524 sensor frames/s
- summary:
  `/var/tmp/m1b-isaac-dual100-final-20260729/dual-benchmark-summary.json`
- summary SHA-256:
  `bf5250308399f719125eb92de2afd9842b522b1fc7e787cc5f39985fb4da55b0`
- worker metric SHA-256:
  `15af08286dbb525b63965409890969b7b3d26fec28ba33111594bb40510281d1`
  and
  `3d6961c30e60e0e721fce123865eb244e4260f576bee2b010d50dc01a0a1c41e`

The low mean utilization is not evidence that RTX was unused. Peak
utilization was 67% on both GPUs, while PNG encoding, depth-array writes and
host readback dominate this small four-camera workload.

## Dataset and action protocol

Every capture writes physically separate streams:

- `runtime_frames.jsonl`: public policy RGB-D calibration/URIs, measured
  nine-DOF Franka state, end-effector pose, gripper state and commanded action.
- `supervision_frames.jsonl`: offline-only simulator object poses and labels.

`scripts/build_isaac_m1b_transitions.py` runs public RGB-D perception before
the offline supervision join. Its `ObservationV0` contains neither simulator
entity IDs nor semantic/instance label images. `TeacherResponse` is always
null.

The action protocol is explicit:

- frame: Panda joint order by name
- dimensions: 9
- units: arm radians and finger metres
- frequency: 30 Hz
- normalization: identity/none
- action source in this benchmark: deterministic dataset excitation, not a
  learned policy

The Student path therefore remains Teacher-independent and never receives
privileged simulator truth at test time.

## Independent static perception gate

The original ADR work item specifies a static RGB-D audit. A first dynamic
five-scene run exposed that the generated 31° tilted cylinders are not static:
they roll to horizontal and can eventually leave the finite table. That
diagnostic is retained below.

For the actual static audit, the benchmark:

1. exports the unmodified production physics stage;
2. marks only cylinder rigid bodies kinematic by their public stage paths;
3. never reads supervision coordinates to perform the freeze;
4. labels the capture `CALIBRATION_ONLY_STATIC_PERCEPTION`;
5. sets `training_eligible=false`;
6. requires the evaluator to fail closed unless all inputs carry that mode.

Five new, previously unseen test scenes were used:
4057, 4058, 4059, 4077 and 4078. They contain 41 distinct cylinders and all
three source orientation classes. Across five frames per scene, every object
had exactly 0 m displacement.

Evidence:

- capture root:
  `/var/tmp/m1b-isaac-static-audit-heldout5-v1-20260729`
- gate:
  `/var/tmp/m1b-isaac-perception-gate-static-heldout5-v1-20260729/m1b-isaac-public-perception-gate.json`
- gate SHA-256:
  `15e7c2ad043aa363efbcc902718bd8aafa58aedcb1716d514bd9a453c86bd456`

Measured result:

| Axis | Median absolute error | p90 absolute error | `0.6 ×` envelope limit | Result |
|---|---:|---:|---:|---|
| X | 2.039 mm | 5.381 mm | 6 mm | PASS |
| Y | 0.969 mm | 2.162 mm | 9 mm | PASS |
| Z | 1.291 mm | 3.802 mm | 6 mm | PASS |

Overall status: **GO**.

The evaluator matched 65 public detections against 205 truth instances over
25 frames. Matched precision was 71.43%, truth recall 31.71%, and global
leftmost-target accuracy 60%. Those are recorded limitations, not hidden by
the p90 pass. The accepted gate compares localization error on matched public
detections to the measured grasp envelope; it is not a detector-recall gate.

## Retained failures and limitations

1. **Dynamic five-scene perception diagnostic: NO_GO.** On scenes
   4017/4018/4019/4037/4038, p90 X/Y/Z was
   8.931/21.420/13.124 mm against 6/9/6 mm. The vertical classes separately
   passed; failures were dominated by tilted objects rolling during frames
   1–4 and becoming occluded or end-on. Evidence SHA-256:
   `db6f67971fa3386e00cd3cd0308e5cac388351c6a10e3a98724092f48dd0ec1c`.
2. **Source tilted pose is physically unsupported.** A 32 s natural-gravity
   audit measured `cylinder_03` total displacement 76.336 m after it left the
   finite table; final 0.5 s displacement was 9.129 m. Gravity, velocities and
   sleep threshold were not modified. This is a source-scene modeling issue,
   not an official-hand or GPU failure. Changing the physical scene requires
   a human ADR; no hidden support was added.
3. **Visibility remains weak.** Static matched truth recall is 31.71% and
   leftmost selection is 60%. A production corpus should improve camera
   coverage and the public detector before treating every generated frame as
   a task-success sample.
4. **One Isaac 6.0.1 cold start segfaulted** while creating the SyntheticData
   graph. It wrote no metrics and was excluded. A fresh output on the other GPU
   passed, and all subsequent held-out captures passed.
5. **Full-repository Ruff is polluted by unrelated pre-existing artifacts.**
   `ruff check .` reports 95 errors in Teacher snapshots, QRM artifacts and old
   diagnostic scripts that were present before this migration. The scoped
   migration files pass Ruff. These unrelated files were not modified.

None of these failures is converted into a relaxed threshold. The dynamic
diagnostic remains NO_GO, while the separately specified static calibration
gate is the one that legitimately returns GO.

## Teacher and truth boundary

- Nano remains `CANDIDATE`.
- BWM remains `CANDIDATE_LICENSE_PENDING`.
- Super remains `PARKED`.
- No Teacher was loaded, replaced, upgraded or called.
- Teacher kill-rule events: **none**, because no Teacher participated.
- Simulator truth is stored only in the offline supervision stream.
- Semantic and instance segmentation are dataset labels, never policy input.

## Changed files

- `src/xh_agent/data/isaac_m1b.py`
- `src/xh_agent/data/isaac_m1b_episode.py`
- `src/xh_agent/grasp/free_gap.py`
- `scripts/isaac_m1b_dataset_benchmark.py`
- `scripts/isaac_m1b_actuation_probe.py`
- `scripts/run_isaac_m1b_tolerance_campaign.py`
- `scripts/run_isaac_m1b_dual_benchmark.py`
- `scripts/build_isaac_m1b_transitions.py`
- `scripts/evaluate_isaac_m1b_perception_gate.py`
- `tests/unit/test_isaac_m1b_scene.py`
- `pyproject.toml`
- `uv.lock`
- this report and `reports/m1b-isaac-migration-evidence.json`

Unrelated dirty hardware probes, Teacher/QRM artifacts and the challenge PDF
were preserved and are not part of this migration.

## Verification

```text
uv run ruff check \
  src/xh_agent/data/isaac_m1b.py \
  src/xh_agent/data/isaac_m1b_episode.py \
  src/xh_agent/grasp/free_gap.py \
  scripts/isaac_m1b_dataset_benchmark.py \
  scripts/isaac_m1b_actuation_probe.py \
  scripts/run_isaac_m1b_tolerance_campaign.py \
  scripts/run_isaac_m1b_dual_benchmark.py \
  scripts/build_isaac_m1b_transitions.py \
  scripts/evaluate_isaac_m1b_perception_gate.py \
  tests/unit/test_isaac_m1b_scene.py
```

Result: `All checks passed!`

```text
git diff --check
```

Result: PASS.

```text
uv run pytest -q
```

Result: `163 passed in 18.60s`.

```text
uv run python scripts/validate_project.py
```

Result:
`{"status":"PASS","schemas":9,"root_import":"CPU_ONLY"}`.

## Blockers

There is no blocker for using the official Isaac adapter or generating
Teacher-free dynamic training data. There is one explicit blocker to claiming
robust dynamic tilted-object tracking: the unsupported source tilted pose and
low public-detector recall. A physical scene correction needs a human ADR;
detector/camera improvements do not authorize privileged truth input.

## Next command

Generate a larger dynamic corpus into a new immutable output root, while
keeping the static calibration outputs excluded from training:

```text
ssh root@labserver '
  cd /var/tmp/m1b-isaac-damped-project-20260729 &&
  python3 scripts/generate_industrial_scenes.py \
    --template robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf \
    --output-dir /var/tmp/m1b-isaac-training-scenes-v1 \
    --count 150 \
    --seed-start 5000
'
```
