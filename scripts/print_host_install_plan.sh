#!/usr/bin/env bash
set -euo pipefail
cat <<'PLAN'
Human-review-only installation plan for Ubuntu 24.04 simulation host (not executed):
1. Review ROS 2 Jazzy Ubuntu 24.04 installation instructions:
   https://docs.ros.org/en/jazzy/Installation/Alternatives/Ubuntu-Install-Binary.html
2. Install the approved ROS 2 Jazzy desktop/base package through your organisation process.
3. Install the approved Jazzy bridge/control/motion packages, e.g. ros-jazzy-ros-gz,
   ros-jazzy-gz-ros2-control, ros-jazzy-ros2-control, and a Jazzy MoveIt 2 package.
4. Confirm `ros2`, `gz`, `ros2 pkg list | grep ros_gz`, and `gz_ros2_control` are present.
5. Build robot_ws with colcon, source its install setup, then run scripts/run_sim_smoke_test.sh.

No sudo, apt, container pull, model download, or configuration action is performed by this script.
PLAN
