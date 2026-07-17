# NOTE-0008: Left-finger actuation runtime block

Date: 2026-07-16

## Decision

Do not modify the approved Panda URDF, world, joint limits, units, controller
interface, or contact gate without a human-approved ADR.  S3 is blocked and
the effective S0 state is `CONTACT_TELEMETRY_PARTIAL` until the two commanded
finger channels are verified in a fresh simulator session.

## Evidence

The isolated home-pose probe `m1a-20260716-hand-actuation-isolated-02` used no
arm motion and no object contact. `panda_finger_joint1` remained at `0.040 m`
for both the `[0.010, 0.040]` and `[0.010, 0.010]` commands, while
`panda_finger_joint2` reached `0.010 m`. Both command interfaces are exported
and claimed by `panda_hand_controller`; no finger contact pair was reported in
the failing windows.

Two temporary, non-persistent launch-overlay A/B probes were also negative:

- move only the palm collision box by `-0.05 m` in local x (launch SHA
  `54fbd1f8…`);
- reduce only the left-finger collision box to `1 mm` (launch SHA
  `36736721…`).

Both retained the same left-channel failure. The approved source and launch
overlay were restored to SHA
`2f77f5150f4e4a5a098ab59a56f98216622cfdfd54a0c79dedbe44e19352eff1`.

The follow-up probe `m1a-20260716-hand-controller-state-06` narrows the fault
past the action layer. For a `[0.010, 0.040]` command, the hand controller's
terminal reference and output were both `[0.010, 0.040]`, while feedback was
`[0.040, 0.040]`; its q1 error remained `-0.030 m`. The same happens for the
bilateral `[0.010, 0.010]` command. Thus the trajectory endpoint, command
interface and controller output are all present; Gazebo-side q1 actuation does
not reach the reported joint state.

The installed official Panda resource is an explicit compatibility reference:
`moveit_resources_panda_description/urdf/panda.urdf` defines q1 as the active
finger joint and q2 as q1's mimic, and its companion ros2_control definition
exports only q1's command interface. The current M1A model instead exports two
direct command interfaces and has the inverse runtime symptom (only q2 moves).

## Required ADR decision

Select a Panda-compatible left-finger actuation repair that preserves the
named seven-arm-joint protocol and explicitly states the two-finger controller
interface. The preferred direction is a verified independent q1
`gz_ros2_control`/transmission mapping, because S0's existing single-finger
calibration semantics require independently commanded pads. The official Panda
mimic model is a reference and a possible fallback only if a compatibility
adapter can retain that external action contract and the revised calibration
semantics receive explicit approval. The ADR must include a no-contact
two-channel probe as an acceptance criterion. After approval and
implementation, rerun S0, then S1, before any new S2 or S3 claim.
