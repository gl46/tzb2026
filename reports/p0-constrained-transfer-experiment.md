# P0 constrained-transfer experiment — failed / not a pick-place result

Date: 2026-07-15, Asia/Shanghai

An isolated node2 experiment used Gazebo Sim 8's official `DetachableJoint` system outside the
normal P0 smoke configuration. Its attach/detach state topic emitted `detached` and `attached`,
and the approach arm trajectory returned `SUCCEEDED`. The subsequent place trajectory did not
complete within its bound; after release the red cube was observed below the work surface rather
than in `bin_a`.

Result: **FAILED_CONSTRAINED_TRANSFER**.

This does not establish a finger-contact grasp, collision-safe transport, placement success,
contact/collision supervision, or an episode. The experimental plugin was removed from the normal
P0 robot description so the verified controller/perception smoke remains a clean scene test.
