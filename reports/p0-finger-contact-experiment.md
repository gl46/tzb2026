# P0 finger-contact grasp experiment — failed / not a grasp result

Date: 2026-07-15, Asia/Shanghai

On node2, the normal controller model was temporarily run with collision shapes retained only
for `panda_leftfinger` and `panda_rightfinger`. Gazebo contact telemetry continued to report the
red cube's contact with the work table. After both a nominal and a pose-corrected approach, a
hand close followed by an arm lift left the cube at its table pose; no cube-finger contact or
object lift was observed.

Result: **FAILED_FINGER_CONTACT_GRASP**.

The temporary collision-model change was removed. The P0 success report therefore remains an
explicit `GAZEBO_DETACHABLE_JOINT_CONSTRAINT` transfer and does not claim a frictional
finger-contact grasp.
