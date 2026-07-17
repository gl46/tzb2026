# M1B-alpha status — PARTIAL

`READY_FOR_M1B_BETA=false`.

## Evidence obtained

- Baseline tag/commit: `m1a-contact-gated-grasp` / `0709cc1`.
- `node2` has ROS 2 Jazzy, Gazebo Harmonic 8.11, MoveIt and A100 hardware.
- A new isolated remote Git worktree exists at
  `/home/gl/xh-202607-world-agent-codex-m1b`; the pre-existing non-Git remote
  deployment was not overwritten.
- `industrial_cylinder_v1.sdf` started headlessly on `node2` and advertised
  RGB-D image/depth/camera-info/points topics. A controller-backed Panda was
  successfully created and the joint, arm and hand controllers activated in
  `logs/m1b-alpha-industrial-panda-20260717-192700.log`.
- A real 26-frame RGB sequence and H.264 MP4 exist at
  `/home/gl/xh-202607-world-agent-codex-m1b/data/episodes/m1b-alpha-fixed-20260717/`.
- Local regression: `59 passed`; focused remote Alpha tests: `6 passed`.

## What is deliberately not claimed

There is no 150+ actual RGB-D dataset, 30-scene held-out evaluation, fully
synchronized ROS bag, open-vocabulary checkpoint, fine-tune, metrics or fused
live perception result. The manifest's 200 records validate seed splitting
only. Therefore the Beta gate is closed and no M1B-beta code/execution has
started.

## Oracle boundary

Online inputs/results reject undeclared truth fields. Entity routing is
actuation-internal and evaluator labels are private. No leakage was found in
the added tests; this is software-audit evidence, not a substitute for the
missing live perception evaluation.

## Dependencies and checks

Remote `/home/gl/xh-202607-world-agent-codex-m1b/.venv` received only the
project-declared editable runtime/dev dependencies, including numpy 2.5.1 and
pydantic 2.13.4. Full repository `ruff` remains red on three pre-existing M1A
script violations; focused new-path ruff is clean.

## Blockers and next command

The remaining blocker is engineering work, not missing host access: implement
the randomized 6–12 part generator and an RGB/depth/camera/TF/joint collector,
then capture/evaluate held-out seeds before allowing Beta.

```bash
ssh gl@node2 'source /opt/ros/jazzy/setup.bash; cd /home/gl/xh-202607-world-agent-codex-m1b; source robot_ws/install/setup.bash; ros2 launch xh_sim simulation.launch.py world_name:=industrial_cylinder_v1 world_file:=$PWD/robot_ws/install/xh_sim/share/xh_sim/worlds/industrial_cylinder_v1.sdf'
```
