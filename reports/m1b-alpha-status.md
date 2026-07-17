# M1B-alpha status — PASS_M1B_ALPHA_WITH_LIMITATIONS

`READY_FOR_M1B_BETA=true`.

## Evidence obtained

- Baseline tag/commit: `m1a-contact-gated-grasp` / `0709cc1`.
- `node2` ran ROS 2 Jazzy, Gazebo Harmonic 8.11, MoveIt and an A100. The
  `IndustrialCylinderBenchmarkV1` Panda scene started headlessly with its
  controllers active.
- A synchronized RGB/depth/camera-info/TF/joint snapshot and rosbag exist at
  `/home/gl/xh-202607-world-agent-codex-m1b/data/episodes/m1b-alpha-sync-tight-20260717/`;
  maximum stream skew is 53 ms. The fixed-scene MP4/image evidence is retained
  alongside that episode.
- The revised non-overlapping V2 generator captured 200 real Gazebo RGB-D
  scenes, split by scene seed as 140/30/30. Its worst accepted RGB/depth/camera
  skew was 198 ms. Transient DDS/sensor startup failures were logged and
  retried under isolated partitions; no incomplete frame entered the manifest.
- The online `geometric_rgbd_v1 + color_prototype_adapter_v1` consumes only
  RGB-D and public calibration. Train split threshold calibration selected
  RGB cosine similarity 0.95; validation count error median was 0.0.
- On the independent 30-scene test split, calibration improved count error
  6.0 → 0.0 and matched-track recall 39.0% → 91.5%. The calibrated pipeline
  achieved 96.7% valid output, 96.7% public-calibration leftmost-target
  selection, and 2.17 cm median 3D position error.

## Oracle boundary

Online inputs/results reject undeclared truth fields. The inference path reads
only RGB, depth and camera intrinsics. Fixed camera calibration and simulator
labels are loaded only after predictions by the offline evaluator. Entity
routing stays actuation-internal. Automated audit and unit tests found no
Oracle leakage.

## Dependencies and checks

The project runtime uses its declared dependencies. A separate remote
`.venv-m1b-ov` installed CPU PyTorch 2.13.0, torchvision 0.28.0,
Transformers 5.14.1 and Pillow 12.3.0 without changing system CUDA. The
GroundingDINO-tiny configuration endpoint timed out after 15 seconds, so no
weight, revision or open-vocabulary prediction is claimed.

Local regression is `68 passed`; focused Ruff for M1B paths and shell syntax
checks pass. Repository-wide Ruff still reports three pre-existing M1A script
violations outside this goal.

## Limitations and next command

Uniform cylinders make normal/inverted visually ambiguous and the measured
orientation-state accuracy is 37.1%. GroundingDINO is installed but has no
downloaded weight because the official source was unreachable. M1B-beta must
use the calibrated RGB-D fallback, treat orientation as low confidence, and
re-perceive after each action.

```bash
bash scripts/run_m1b_beta_validation.sh
```
