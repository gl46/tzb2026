# Simulation host

Use one supported Ubuntu 24.04 host with a compatible Jazzy/Harmonic installation. node2 and
chxy passed the bounded default-world headless smoke on 2026-07-15. The local Mac is a code/test
host only; the desktop RTX 4060 is optional and not a P0 dependency.

Project sync/build is deliberately gated because the original goal defaults to no remote project
writes. After an explicit decision, use `ALLOW_REMOTE_WRITE=1 REMOTE_HOST=node2
REMOTE_USER=gl bash scripts/deploy_remote_p0.sh`, then run `SIM_HOST=node2 SIM_USER=gl
PROJECT_REMOTE_ROOT=xh-202607-world-agent bash scripts/run_sim_smoke_test.sh`. The second command
is bounded, uses a separate session/process group, and removes its own launch processes. It does
not require a GUI or a persistent Gazebo process.

The gate was approved and exercised on node2 on 2026-07-15. The build passed and the smoke test
verified the `xh_p0_pick_place` Gazebo world, three props and RGB-D sensor; it also spawned the
controller-backed Panda-compatible arm, observed active arm/hand controllers, succeeded at
conservative arm and two-finger trajectories, and received joint-state, TF, RGB, depth and camera
info messages. The same command remains the reproducible bounded check. It still reports
**pick-place, physical grasp/release, object transfer, supervision, and episode recording as
unverified**.

For planning-only evidence, `MOVEIT_HOST=node2 MOVEIT_USER=gl
PROJECT_REMOTE_ROOT=xh-202607-world-agent make moveit-plan-smoke` starts a no-GUI official Panda
MoveIt server in a bounded session and requests one joint-space plan. It verifies a non-empty
motion plan only; it neither shares a planning scene with the Gazebo world nor executes a robot
trajectory there.
