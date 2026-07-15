# ADR-0004: ROS / Gazebo platform

Date checked: 2026-07-15 (Asia/Shanghai)

Target is Ubuntu 24.04 + ROS 2 Jazzy + Gazebo Harmonic + `ros_gz` + `gz_ros2_control` + MoveIt 2.
Official ROS Jazzy documentation supports Ubuntu Noble; Gazebo Harmonic documentation identifies
ROS 2 Jazzy binary integration through `ros_gz`. The two remote hosts are Ubuntu 24.04.2 and
24.04.4, so their OS is aligned. This macOS arm64 workstation has no `ros2` or `gz`, so local
simulation is `BLOCKED_SYSTEM_DEPENDENCY`; it was not force-installed.

On 2026-07-15, node2 and chxy were both provisioned with the Jazzy binary stack, `ros_gz`,
`gz_ros2_control`, MoveIt 2, and Panda resources. A bounded `gz sim -s -r --headless-rendering`
run of the packaged default world remained alive for eight seconds on each host. This verifies
the platform only, not this project's robot spawn, topics, control, pick-place, or recording.
The project must be deployed and built on one host under an explicit remote-write decision before
those claims can be made. Do not combine Humble and Jazzy packages silently.

That remote-write decision was granted later on 2026-07-15. The workspace was built successfully
on node2 (five packages). A bounded project smoke then spawned the controller-backed P0 arm,
loaded active `gz_ros2_control` joint-state, seven-joint trajectory, and two-finger trajectory
controllers, and observed successful conservative arm and gripper actions. It separately received
`/joint_states`, `/tf`, RGB, depth, and camera-info messages. The world scene service confirmed
the table, bin and three physical props.

The spawned robot retains Panda-compatible joint names, ranges and parallel-finger topology but
uses deliberately simple inertial primitives. Therefore this is **verified control-stack and
perception plumbing**, not a claim of high-fidelity Franka dynamics, reliable physical grasping,
object transfer, contact/collision supervision, or episode recording. Those claims remain false
until separate bounded evidence exists. The `gz_ros2_control` Jazzy documentation is recorded in
the upstream lock; it specifies the model plugin, `GazeboSimSystem` hardware interface and the
controller-manager integration used here.
