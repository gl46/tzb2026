# System v1

`TaskSpec → Observation → candidate skills → Student outcome prediction + uncertainty → ranking /
gate → short action → new observation → residual attribution → recovery`. B1 is a deterministic
P0 fallback that produces skills but does not replace Student prediction in the target system.

The ROS layer exposes joint state, trajectory and gripper command, TF, RGB/depth/camera info,
object tracks, contact/collision, supervision-only object ground truth, episode lifecycle and
failure-injection configuration. Franka Panda plus parallel gripper is the initial embodiment;
the embodiment adapter stays independent of any Teacher.
