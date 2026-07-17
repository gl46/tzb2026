# ADR-0008: Panda mimic hand with a fail-closed compatibility adapter

Date: 2026-07-16 (Asia/Shanghai)
Status: **ACCEPTED — approved 2026-07-16 (Asia/Shanghai)**

Implementation state: **PARTIAL — q2-master controller and fail-closed public
adapter passed their no-contact probe; required spawned-SDF physical mimic
constraint is unavailable in the installed DART plugin. S0 remains blocked.**

## Context

ADR-0007 Option 1 was approved with a three-hour diagnostic timebox. The
world-pose, spawned-SDF, asymmetric-command, and temporary mirror-axis tests
did not identify a viable independent-q1 repair. Its complete outcome is in
[NOTE-0009](NOTE-0009-option1-mirror-axis-diagnostic.md).

The installed official Panda description is the remaining compatibility
reference: q1 is the physical command joint and q2 mimics q1. That removes the
unverified independent actuation contract, but it cannot silently preserve the
old meaning of a q1-only or q2-only close command.

## Proposed physical and interface contract

1. Start with `panda_finger_joint1` as the sole physical position command
   joint and make `panda_finger_joint2` mimic it. Preserve both joint names, metres,
   `[0, 0.04] m` limits, contact sensors, collision geometry, and `positive
   value = open`.
2. Retain the external two-name hand action endpoint with a compatibility
   adapter in front of the one-joint physical controller. It must accept only
   symmetric commands within `1 mm`, translate them to the active master, and reject every
   asymmetric request with an explicit result. It must never silently average,
   choose one entry, or pretend two physical actuators exist.
3. Reapprove S0's labelled single-pad conditions as **pose-induced,
   fixed-aperture contact**: a lateral arm approach contacts the named left or
   right pad while the mimicked hand remains symmetric. They remain sensor-label
   calibration tests, not independent-finger-closure tests. Bilateral
   conditions remain symmetric close commands.

The proposed 13-condition matrix is deliberately the same label count as the
S0 aggregation contract, but with explicit new meanings:

| Labels | Count | Required action | Expected contact |
| --- | ---: | --- | --- |
| `left_1..3` | 3 | Runtime-oracle pad-to-cube left-side approach at a fixed symmetric aperture | Left pad only |
| `right_1..3` | 3 | Runtime-oracle pad-to-cube right-side approach at a fixed symmetric aperture | Right pad only |
| `bilateral_1..3` | 3 | Symmetric mimic close after collision-checked approach | Both pads, same target, ≥100 ms |
| `object_environment_1..2` | 2 | No finger target contact | Target-equivalent/table evidence only |
| `table_1..2` | 2 | No target contact | Finger/table evidence only |

The pad target pose must be computed from the runtime-oracle cube pose and the
current gripper geometry; it must not reinstate hard-coded arm joint vectors.

## Pre-implementation action contract

The eventual implementation must make the following boundary observable before
it is considered a repair:

| Endpoint / component | Joints | Behaviour |
| --- | --- | --- |
| Public `/panda_hand_controller/follow_joint_trajectory` adapter | q1, q2 | Validates two named positions and rejects `abs(q1-q2) > 0.001 m` with `INVALID_GOAL` and `ASYMMETRIC_MIMIC_COMMAND_REJECTED`. |
| Private physical trajectory controller | active master only | Receives the accepted symmetric position exactly once; its follower is never a command interface. |
| `joint_states` and controller evidence | q1, q2 | Retains both positions, proving the follower's state follows the active master within 1 mm. |
| S0 left/right pose-induced runs | q1=q2 fixed aperture | Retains pad world pose, cube world pose, minimum pad/cube separation, and the named sensor contact window. |

The adapter must reject malformed joint order/name sets and goals with more than
one point unless the approved implementation explicitly defines their
interpolation semantics. It must not use Gazebo pose/joint writes or simulator
truth in the task-time control path.

## Approved decisions

The human approver accepted all of the following on 2026-07-16
(Asia/Shanghai):

- Pose-induced, fixed-aperture labelled single-pad contact replaces the former
  independent-finger closure claim.
- The public two-name endpoint fails closed: asymmetric requests terminate with
  `INVALID_GOAL` and `ASYMMETRIC_MIMIC_COMMAND_REJECTED`; no physical command
  may be emitted for them.
- The revised 13-condition S0 matrix is approved. It must run in full before
  S0 can advance, followed by a new 10-trial S1 gate.

### Pre-authorized master-joint flip

The first no-contact acceptance probe is the active-joint decision experiment:
q1 is commanded, q2 is physically mimicked, and both reported positions must
track to `1 mm`. If q1 still cannot close, no additional diagnostic timebox or
third approval is required. The implementation must immediately invert only
the master/follower relation to q2-active/q1-mimic, retaining the adapter,
symmetry rule, 13-condition matrix, names, limits, metres, and
`positive = open` semantics. The implementation-SHA record must then contain
the literal marker `PANDA_MIMIC_Q2_MASTER` and explain the departure from the
official q1-master convention.

This pre-authorization is only for that first, bounded no-contact probe. It
does not authorize further model/controller alternatives, S0 promotion, or S2
execution.

## Acceptance and revalidation

Before any S0 status upgrade on the new implementation SHA:

1. The active-master physical command and follower state track within `1 mm` in a
   no-contact probe, with controller reference/output/feedback and direct
   Gazebo link poses retained;
2. the adapter accepts symmetric requests and fail-closed rejects asymmetric
   requests, with no physical command emitted for rejected requests;
3. the spawned SDF contains the selected follower `<axis><mimic>` constraint,
   that follower exports state but no command interface, and `joint_states` still reports
   both finger joints; and
4. all 13 newly approved S0 conditions pass; then S1's 10 MoveIt plan →
   execute → FK trials pass; and
5. only after S0/S1 pass, reset S2 to its explicitly approved 3 × 5 allocation
   under the new SHA. Historical attempts remain recorded but are not used for
   friction evaluation.

S2/S3/S4/B1 remain blocked until the preceding evidence is current.

## Approval record

- Human approver: **APPROVED 2026-07-16 (Asia/Shanghai)**
- Pose-induced single-pad semantics: **APPROVED**
- Asymmetric public-action rejection: **APPROVED**
- Revised S0 13-condition matrix: **APPROVED**
- First-probe master-joint decision: **APPROVED q1 master; one-time q2-master
  fallback pre-authorized on q1 no-contact close failure**
- SDF mimic / interface visibility audit: **REQUIRED before S0**
- S2 allocation after current SHA S0+S1 success: **APPROVED reset to 3 × 5**
- Active-master decision: **PANDA_MIMIC_Q2_MASTER** — q1-master probe
  `m1a-20260716-adr0008-q1-master-02` recorded q1 feedback at `0.040 m` for
  a `0.010 m` close reference (30 mm error), so the pre-authorized flip was
  invoked. The generated-SDF physical-constraint audit remains a blocking
  acceptance item.
- Implementation SHA: **`28c13961245e192984b5ab483da732b29bcd7af66eb65b12542932388af7295d`
  — `PANDA_MIMIC_Q2_MASTER` controller/adapter functionally verified, but not
  accepted for S0 because the physical-SDF mimic audit is blocked.**
- Current controlled-URDF SHA: **`cf941d903468d45e2fa0ff103e1371dfac144558445002f5f76ce44c278239a9`**
  — q2 was declared before the q1 follower solely as a bounded importer-order
  check. The temporary Bullet launch still reported an empty mimic leader, and
  no no-contact probe claims are made for this SHA. It is not eligible for S0.
