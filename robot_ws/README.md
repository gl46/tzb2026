# ROS 2 workspace skeleton

The workspace owns description, scene/failure configuration, bringup, recorder and B1 package
boundaries. The local macOS host has no ROS/Gazebo, so a compatible remote host must build and run
this workspace.

`xh_sim` starts the table, three physical props, a bin and the fixed RGB-D camera fixture. It then
spawns `panda_controlled.urdf` through `ros_gz_sim`, starts `gz_ros2_control`, a joint-state
broadcaster, a 7-joint trajectory controller and a two-finger trajectory controller. The model
preserves Panda joint naming/ranges and gripper topology but intentionally uses simple inertial
primitives; it validates the ROS/Gazebo control path and is not a claim of high-fidelity Panda
contact dynamics. The bounded smoke test records each separately verified capability.
