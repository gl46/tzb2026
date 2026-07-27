# M1B Isaac Sim official Franka dual-RTX-3080 benchmark

Date: 2026-07-27 (Asia/Shanghai)

Status: **DATASET PIPELINE PASS; NATIVE ISAAC CONTACT/ATTACH PASS**

## Scope

- Isaac Sim image: `nvcr.io/nvidia/isaac-sim:6.0.1`
- Robot asset: NVIDIA Isaac Sim 6 official Franka Panda USD:
  `Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd`
- Local simplified robot used for rendering: **false**
- Workers: one independent Isaac process per physical RTX 3080
- Cameras per worker: 3 at 640x480
- Modalities: RGB, distance-to-camera depth, semantic segmentation, instance segmentation
- Capture steps per worker: 100
- Sensor frames per worker: 300
- Privileged labels: offline dataset supervision only, not policy input

## Asset authenticity boundary

- Every Isaac robot visual, collision, articulation, joint, and finger shape is
  composed from NVIDIA's official Franka Panda USD. There is no locally
  authored or simplified robot geometry in the Isaac stage.
- The selected official variants are `Gripper=AlternateFinger` and
  `Mesh=Performance`, matching NVIDIA's Isaac Sim 6 Franka controller example.
- `panda_controlled.urdf` is used only as a hash-bound control/base-pose
  contract. It is never referenced as Isaac visual or collision geometry.
- The cylinders, work table, incoming-zone markings, and partition bin are
  task-scene geometry generated from the accepted M1B SDF. They are not robot
  substitutes and must remain dimensionally tied to the task contract.

The source M1B SDF and control-contract URDF remained hash-bound. The primary
dataset camera was rotated 180 degrees around the target, per review, and is
explicitly marked as a dataset view rather than a policy input.

The legacy `panda_controlled.urdf` is verified only as the accepted M1B
control-contract reference. It is not referenced into the Isaac stage and
contributes no visual or collision geometry to this benchmark.

## Native physics-stage audit

A render-free physical USDC was exported from generated scene seed 3000:

- Stage: `/var/tmp/m1b-isaac-clean-physics-usdc-20260728/output/m1b_physics_scene.usdc`
- SHA-256: `5e2e3f179c237e4bd40f922ac9835746b3798db7bd98226a697fab4bcd9eb11b`
- Size: 12 MiB
- Official robot base pose: `(-0.35, 0.0, 0.45)` metres, parsed from the
  hash-bound production URDF
- Dynamic objects: 11 cylinders at 0.045 kg each
- Task collision primitives: 13
- Render products in the physical stage: none
- Local simplified robot geometry: false

The official hand exposes two PhysX collision shapes on each finger and the
probe created eleven object filters per finger. The physical scene therefore
does not silently omit official finger collisions.

## Native contact/attach probe

The calibration-only probe used the official USD's driven
`panda_finger_joint1` plus its authored PhysX mimic joint, a 0.0-metre closed
target, 60 Hz physics, and the unchanged ADR-0013 broker requirement: at least
three samples and at least 100 ms of bilateral contact with the same entity.

Measured result: **PASS**, reproduced after removing zero-force filter pairs.

- A 200 mm free-close control reached approximately
  `0.00000013/0.0 m` with no cylinder contact. This proves the official drive
  and mimic topology close correctly when the fingertips are clear.
- At the 105 mm contact centreline, the official fingers stopped at
  `15.466/15.827 mm` around the 30 mm cylinder.
- The correct dynamic-object filter is the rigid-body prim
  `/World/M1B/cylinder_XX/link`. The earlier collision-prim filter was valid
  for NVIDIA's static-ground example but returned no dynamic-object forces.
- Strictly positive tensor contact force was observed for `cylinder_01` in
  230 left-finger and 227 right-finger frames. Zero-force pair-count artifacts
  were excluded.
- The existing broker measured 227 paired bilateral samples over
  3.7667 seconds and selected only `cylinder_01`.
- The fixed joint attached `cylinder_01`; the object lifted 164.727 mm with
  1.072 mm hand/object follow error.
- After joint removal and opening, detached object motion during retreat was
  0.0 mm, below the unchanged 10 mm non-coupling limit.

Remote evidence:

- Root:
  `/var/tmp/m1b-isaac-body-filter-positive-force-repro-20260728`
- Probe SHA-256:
  `a3bd1c87769898f6769c8d20a7afa0abdedf7cb67da956284dd89accf38843f7`

## Measured results

| Metric | GPU 0 / worker 0 | GPU 1 / worker 1 |
|---|---:|---:|
| Status | PASS | PASS |
| Benchmark wall time | 48.816983 s | 48.748803 s |
| Sensor frames | 300 | 300 |
| Sensor frames/s | 6.145402 | 6.153997 |
| Capture-step p50 | 0.148195 s | 0.149466 s |
| Capture-step p90 | 0.156246 s | 0.156300 s |
| Readback/write p50 | 0.336570 s | 0.334096 s |
| Readback/write p90 | 0.348132 s | 0.344586 s |
| Peak VRAM | 2200 MiB | 2062 MiB |
| Mean VRAM | 2150.29 MiB | 2010.96 MiB |
| Peak GPU utilization | 59% | 61% |
| P90 GPU utilization | 56% | 57% |
| Mean GPU utilization | 18.77% | 22.02% |
| Peak power | 103.11 W | 103.07 W |
| Output bytes before metrics | 426,039,864 | 426,092,654 |
| Official Franka semantic pixels | 5,482,171 | 5,466,039 |

Combined concurrent result:

- 600 sensor frames in 48.816983 seconds
- 12.290805 sensor frames/s
- 852,132,518 output bytes before metrics (about 812.66 MiB)
- RGB 600, depth 600, semantic 600, instance 600, label JSON 12

The relatively low mean GPU utilization and the 0.334-0.337 second median
readback/write time show that PNG encoding, NumPy depth writes, and host
readback dominate this small benchmark more than RTX rendering.

## Runtime validation

- Official Panda DOF indices were exactly 0 through 8:
  seven revolute arm joints and two translational finger joints.
- The action protocol was explicit: named Panda joint frame, arm radians,
  finger metres, dimension 9, 30 Hz, no normalization.
- Both workers passed exact file-count checks, finite-depth checks, label
  presence checks, and nonzero rendered-pixel checks for both
  `industrial_cylinder` and `panda_robot`.
- Both GPUs returned to idle after completion: 171 MiB / 32 MiB and 0% use.

Remote evidence:

- Root:
  `/var/tmp/m1b-isaac-official-dual-workers-retry4-20260727`
- Worker 0 metrics SHA-256:
  `82c44824c4f2460946933b8d0fef2c3c234935222e33740406c3be5182874487`
- Worker 1 metrics SHA-256:
  `c816e00b957de9add0890d61deba809cbb67742c4fd10e1e19c056300be688b3`

## Failures retained

1. The first preflight used the image's default streaming entrypoint instead
   of `/isaac-sim/python.sh`; it was stopped and produced no data.
2. The next preflight failed closed because the output mount was not writable.
3. The original geometry traversal check reported zero because the official
   USD uses instances/payloads. It was replaced with stronger runtime gates:
   exact articulation DOFs plus actual semantic pixels.
4. Simultaneously starting two Kit processes caused a Kit crash or partial
   extension imports. IPC and network changes alone were insufficient.
5. The final setup serialized Kit/asset initialization with READY files and
   released both 100-frame loops through one START barrier. This preserved
   fully concurrent measured capture while avoiding initialization races.
6. Expanding every official USD instance made the finger collision prims
   editable but crashed Isaac 6.0.1 while creating the RTX SyntheticData
   graph. The exported physical layer was tested independently, then this
   route was discarded because rigid-body tensor filters work without
   de-instancing.

## Verification commands

```text
uv run --isolated --with 'pytest>=8,<9' --with 'pydantic>=2.7,<3' \
  --with 'PyYAML>=6,<7' --with 'jsonschema>=4,<5' \
  --with 'numpy>=1.26,<3' --with 'eval-type-backport>=0.2' \
  pytest -q tests/unit/test_isaac_m1b_scene.py tests/unit/test_m1b_beta_protocol.py
```

Current result: `67 passed in 5.09s`.

```text
.venv/bin/ruff check src/xh_agent/data/isaac_m1b.py \
  scripts/isaac_m1b_dataset_benchmark.py \
  tests/unit/test_isaac_m1b_scene.py
```

Result: `All checks passed!`

## Blockers

None for the requested 100-frame dual-GPU sensor benchmark.

The single calibration-only Isaac grasp/attach/detach path now passes. Full
M1B migration still requires reset/repetition gates, public RGB-D-driven target
selection, the Student world-model protocol boundary, and end-to-end held-out
rollouts. This report does not claim those gates yet.

The generated dataset is a throughput/format validation set, not yet a
diverse training corpus: scene randomization, calibrated sensor noise,
lighting/material domains, and train/validation split generation remain the
next data-engineering step.

## Next command

```text
ssh root@labserver \
  'jq "{status,contact_feedback,attached_follow,detached_noncoupling}" \
  /var/tmp/m1b-isaac-body-filter-positive-force-repro-20260728/output/actuation-probe.json'
```
