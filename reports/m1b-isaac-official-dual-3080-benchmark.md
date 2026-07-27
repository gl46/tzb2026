# M1B Isaac Sim official Franka dual-RTX-3080 benchmark

Date: 2026-07-27 (Asia/Shanghai)

Status: **PASS**

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

The source M1B SDF and control-contract URDF remained hash-bound. The primary
dataset camera was rotated 180 degrees around the target, per review, and is
explicitly marked as a dataset view rather than a policy input.

The legacy `panda_controlled.urdf` is verified only as the accepted M1B
control-contract reference. It is not referenced into the Isaac stage and
contributes no visual or collision geometry to this benchmark.

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

## Verification commands

```text
uv run --isolated --with 'pytest>=8,<9' --with 'pydantic>=2.7,<3' \
  --with 'PyYAML>=6,<7' --with 'jsonschema>=4,<5' \
  --with 'numpy>=1.26,<3' --with 'eval-type-backport>=0.2' \
  pytest -q tests/unit/test_isaac_m1b_scene.py tests/unit/test_m1b_beta_protocol.py
```

Result: `64 passed in 4.59s`.

```text
.venv/bin/ruff check src/xh_agent/data/isaac_m1b.py \
  scripts/isaac_m1b_dataset_benchmark.py \
  tests/unit/test_isaac_m1b_scene.py
```

Result: `All checks passed!`

## Blockers

None for the requested 100-frame dual-GPU benchmark.

The generated dataset is a throughput/format validation set, not yet a
diverse training corpus: scene randomization, calibrated sensor noise,
lighting/material domains, and train/validation split generation remain the
next data-engineering step.

## Next command

```text
ssh root@labserver \
  'jq "{status,robot_asset,output_counts,sensor_frames_per_s,semantic_pixel_counts}" \
  /var/tmp/m1b-isaac-official-dual-workers-retry4-20260727/worker0/output/metrics.json'
```
