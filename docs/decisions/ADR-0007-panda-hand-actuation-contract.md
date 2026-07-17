# ADR-0007: Restore the Panda two-finger actuation contract

Date: 2026-07-16 (Asia/Shanghai)
Status: **CLOSED — Option 1 did not identify a viable repair within its approved timebox**

## Context

The approved M1A URDF SHA-256 is
`2f77f5150f4e4a5a098ab59a56f98216622cfdfd54a0c79dedbe44e19352eff1`.
It exports `panda_finger_joint1` and `panda_finger_joint2` as independent
prismatic position-command interfaces to `panda_hand_controller`. The M1A S0
calibration contract requires both bilateral and labelled single-finger contact
conditions, so the existing external two-name hand action is a protocol
invariant unless this ADR explicitly changes it.

The isolated no-contact runtime probe records that q1 does not close:

| Command (m) | q1 feedback (m) | q2 feedback (m) | Controller terminal reference/output |
| --- | ---: | ---: | --- |
| `[0.010, 0.040]` | `0.040` | `0.040` | `[0.010, 0.040]` |
| `[0.040, 0.010]` | `0.040` | `0.010` | reaches q2 target |
| `[0.010, 0.010]` | `0.040` | `0.010` | `[0.010, 0.010]` |

There was no finger/object/table contact in those home-pose windows. Both
ros2_control command interfaces were available and claimed. Two temporary,
fully reverted launch-overlay A/B tests—moving the palm collision box and
reducing the left-finger collision box to 1 mm—retained the same fault. The
controller therefore supplies q1's position target; the loss is at the
Gazebo-side q1 physical actuation/feedback mapping.

The installed URDF's generated SDF independently confirms that both finger
joints exist as prismatic physics joints with the intended common origin,
opposed axes, and `[0, 0.04] m` limits.  q1 can move from its `0.02 m`
initial state to the `0.04 m` open target, but does not move from `0.04 m`
toward a `0.01 m` closed target even while the controller state reports that
target as both its reference and output.  This directional runtime evidence
rules out a missing q1 entity or a generic inability to actuate q1; it does
not identify a safe source-level repair by itself.

A bare `FollowJointTrajectory` CLI request can still report success because it
does not supply an endpoint tolerance.  The probe's explicit `1 mm` goal
tolerances and independently sampled joint state are therefore the governing
acceptance evidence; an unconstrained action-success string cannot clear this
gate.

For comparison, the installed official Panda description keeps the same two
joint names, directions and `[0, 0.04] m` limits but makes q2 mimic q1 and
exports only q1's command interface. That is physically Panda-compatible, but
does not by itself preserve the M1A labelled single-finger calibration action
semantics.

## Options

1. **Independent-actuation repair — recommended.** Keep both finger joint
   names, limits, metres, collision/sensor geometry and the current two-name
   `panda_hand_controller/follow_joint_trajectory` action. Repair or replace
   the Gazebo/ros2_control q1 transmission mapping so the q1 reference/output
   reaches q1 feedback in a no-contact probe. This keeps S0's existing
   single-finger and bilateral test definitions valid.
2. **Official-Panda mimic plus compatibility adapter.** Make q2 mimic q1 and
   adopt q1 as the physical command joint, as in the official resource. An
   adapter would have to retain the current external two-name action and
   explicitly define/reapprove what single-finger calibration means. This is
   not a silent simplification and is not approved by this proposal.

## Approved decision and outcome

The human approver selected option 1. Before a persistent repair is made, the
implementation must identify a concrete Gazebo-side mechanism and source/launch
SHA pair. The repair must not weaken collision policy, adjust
friction/mass/solver settings, use an object pose write, or introduce privileged
simulator truth into policy inputs.

The approved diagnostic sequence is, in this order:

1. Record Gazebo's left-finger world pose beside joint-state during a close
   command; this distinguishes a physics actuator failure from a state-readout
   failure.
2. Diff the actual spawned SDF joint blocks against the source conversion and
   enumerate every plugin reference to each finger link or joint.
3. Issue the asymmetric `[0.015, 0.035] m` command and retain both per-channel
   controller and physical evidence, to detect command cross-wiring.
4. If still necessary, run a temporary, fully reverted mirror-axis overlay for
   q1 with mirrored geometry. It preserves joint names, limits, metres, and the
   external semantic `positive value = open` while testing the signed-axis
   conversion path.

This diagnostic phase was time-boxed to three engineering hours from the first
diagnostic run. The world-pose and asymmetric tests established that q1's
physical link does not close, while q2's physical link follows its own
asymmetric target; command cross-wiring is therefore not supported by the
evidence. The temporary mirror-axis overlay also left q1 at `0.040 m` for the
`[0.010, 0.040] m` command while q2 continued to behave normally. It did not
identify a concrete Option 1 repair.

The temporary overlay's source and launch SHA was
`84e213f849c16bb294e65c63a45a9c217f8a88e292969528bdc1d1c17033ab2c`.
Both remote source and installed launch overlays were restored to the approved
`2f77f5150f4e4a5a098ab59a56f98216622cfdfd54a0c79dedbe44e19352eff1`
before this ADR was closed. No persistent model or controller change was made.

Per the approval condition, no more unbounded Option 1 diagnosis is authorized.
The only remaining candidate is Option 2 under a separate human-approved ADR
that explicitly redefines and reapproves single-finger calibration semantics.

## Acceptance and mandatory revalidation

Before changing S0 status, a fresh simulator session on the new SHA must show:

1. q1-only, q2-only and bilateral commands all reach their commanded values
   within the 1 mm controller tolerance, with no object contact;
2. controller reference, output and feedback are retained as evidence for
   both channels; and
3. the 13 S0 calibration conditions are rerun and pass before S1's ten
   MoveIt-plan → execute → FK trials are rerun.

S2/S3/S4 remain blocked until those S0 and S1 results are current. No historical
grasp, video, calibration or B1 result may be relabelled as evidence for the
changed hand actuation chain.

## Approval record

- Human approver: **project user, 2026-07-16 (Asia/Shanghai)**
- Chosen option: **Option 1 — independent-actuation repair**
- Diagnostic timebox: **three engineering hours from first logged diagnostic run**
- S2 allocation after repair SHA: **RESET to 3 classes × 5 attempts = 15**.
  The previously spent 15-attempt allocation was consumed with the q1 actuator
  defect present and is recorded as invalid for friction evaluation; this is an
  explicit approval-record change, not a silent quota change.
- Implementation SHA: **NONE — Option 1 diagnostic failed; approved SHA restored**
