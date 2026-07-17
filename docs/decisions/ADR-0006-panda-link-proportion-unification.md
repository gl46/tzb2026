# ADR-0006: 机器人连杆比例统一到 Panda 运动学量级，场景与限位不变

Date: 2026-07-16 (Asia/Shanghai)
Status: **ACCEPTED — 2026-07-16 (Asia/Shanghai)**

## Context

The controlled robot keeps Panda joint names, limits, units and controller
interfaces, but its arm-and-wrist joint-origin translations sum to 1.98 m. Its
kinematic size is therefore inconsistent with the Panda-scale tabletop task.
The S2 dynamic-world trials all failed before contact:
`APPROACH_ALIGNMENT_FAILURE`. The calibrated finger contact sensors are a
valuable M1A asset and are out of scope for this proposal.

The initial requested remedy was to retain the base and scene, scale the arm
links to a nominal 0.85 m total fingertip reach, and preserve all joint
protocols and the end effector. Before any simulator change, an offline
URDF-origin FK sample was required. That uniform-scale remedy is not the
approved candidate: it preserves the current, non-Panda joint-origin directions
and does not establish target reach under the existing base placement in the
required sampling/refinement evidence.

## Evidence before decision

[`reports/m1a-fk-workspace-sampling.json`](../../reports/m1a-fk-workspace-sampling.json)
records a deterministic 100,000-configuration uniform sample of the seven arm
joints (seed `20260716`) against the dynamic-world cube target
`[0.22, 0.12, 0.475]` m. It uses collision-centre fingertip points, holds both
finger joints at 0.02 m, and runs no ROS, Gazebo, collision, contact or grasp
operation. The report is bound to source-URDF SHA-256
`e017d82f218578603078fd5da73cdba88ed47fef2f5ed57cf9f01f5c666fb096`.

The original uniform candidate scales only `panda_joint1`…`panda_joint7` and
`panda_hand_joint` origins by 0.371212121. It leaves `world_to_panda`, the two
finger joints, hand/finger geometry and finger collision-centre offsets
unchanged. That gives 0.85 m nominal total reach: 0.735 m scaled arm/wrist
serial translation plus 0.115 m unchanged end-effector extension.

An additional candidate uses the joint origins and fixed wrist transforms from
the installed node2 `moveit_resources_panda_description` file
`/opt/ros/jazzy/share/moveit_resources_panda_description/urdf/panda.urdf.xacro`
(SHA-256 `c8ee3bad4d89ad9bf4af717037418a3e6b046d47df6375a92a912a901d256a34`).
It retains the current project's *soft* limits rather than importing the
resource's hard limits, retains the world/base transform and all finger
geometry/sensors, and adds only Panda's fixed `panda_link8` / `panda_joint8`.
The candidate arm origins are:

```text
j1 [0, 0, .333]             j2 [0, 0, 0]
j3 [0, -.316, 0]            j4 [.0825, 0, 0]
j5 [-.0825, .384, 0]        j6 [0, 0, 0]
j7 [.088, 0, 0]             fixed j8 [0, 0, .107]
hand fixed transform: xyz [0, 0, 0], yaw -pi/4
```

| FK model | Random closest pad centre | 3 cm density | 5 cm density | Position-only refined distance |
| --- | ---: | ---: | ---: | ---: |
| Current controlled URDF | 2.66 cm | 1/200,000 (0.0005%) | 6/200,000 (0.0030%) | 0.000000053 m |
| Uniform 0.85 m candidate | 14.23 cm | 0/200,000 | 0/200,000 | 0.126863353 m |
| Official Panda-origin candidate | 1.96 cm | 7/200,000 (0.0035%) | 25/200,000 (0.0125%) | 0.000000017 m |

The position refinement starts from each nearest random sample, obeys the
current seven-arm-joint limits, and solves only pad-centre position. It does
not solve orientation, check collisions, establish a collision-free approach,
or establish a grasp. It is nevertheless sufficient to distinguish the
official-origin candidate from the uniformly shrunk candidate in the required
target neighbourhood. No URDF, scene, controller or end-effector change has
been made by this ADR or the sampling run.

## Decision

The human approver accepted **the official Panda-origin candidate described
above**, subject to the bin-reachability, home-state collision and S1 collision
audit conditions below. The uniform 0.85 m scale candidate is explicitly
rejected by its 12.7 cm position-only residual in the deterministic bounded
refinement and must not be implemented.

Approval covers the exact origin table, retained base transform `[-.35, 0,
.45]`, unchanged dynamic cube pose `[.22, .12, .475]`, the revised bin centre
`[.217366447885, -.249990627453, .45]`, its pre-place target
`[.217366447885, -.249990627453, .60]`, the cited source report and both URDF
revisions. The implementation must make the arm
visual/collision primitives consistent with these transforms; merely changing
joint origins while leaving the old oversized colliders would not meet this
decision. The existing hand/finger collision geometry and sensors must not be
altered. This ADR title describes the requested direction; its current status
is not authorization to alter the model.

## Invariants for any approved implementation

An approved implementation must preserve all of the following:

1. `panda_joint1`…`panda_joint7` and both finger joint names, lower/upper
   limits, radians/metres units and controller action interfaces;
2. the calibrated hand, fingers, finger collision geometry and contact sensor
   topic names; and
3. the controller/MoveIt same-URDF requirement, explicit collision policy and
   SRDF collision-pair reporting.

`panda_link8` / `panda_joint8` may be added only as the fixed, unactuated
Panda wrist transform stated above. It must not appear in an arm controller,
trajectory goal, the seven-actuated-joint contract or the test-time policy
action vector.

## Implementation-readiness audit

This is a read-only audit of the current M1A configuration, not an
implementation authorization. Once approved, the expected impact is narrowly
bounded:

| Surface | Required change after approval | Must remain unchanged |
| --- | --- | --- |
| `panda_controlled.urdf` | Replace the arm/wrist transforms with the approved table; add fixed `panda_link8` / `panda_joint8`; resize arm visual/collision primitives consistently. | The base transform, nine actuated joint names/limits/interfaces, hand/finger links, finger collision geometry and contact sensor topics. |
| `m1a_panda.srdf` | Replace adjacent pair `panda_link7`–`panda_hand` with `panda_link7`–`panda_link8` and `panda_link8`–`panda_hand`. | The arm chain remains `panda_link0` to `panda_hand`; no robot/world collision is disabled. |
| `m1a_collision_policy.yaml` and S1 evidence | Add `panda_link8`–`work_table` to the explicit enabled list and report it in the final enabled-pair list. | Finger/object and arm/table checks, plus the sole `panda_link0`–`work_table` exception. |
| Controller and MoveIt controller YAML | None. | Exactly seven arm trajectory joints and two finger trajectory joints. |
| Launch chain | None. | Both Gazebo and MoveIt continue to consume the same controlled URDF. |

The existing `ADJACENT_SELF_PAIRS` audit and unit test must be updated together
with the SRDF so no collision exception is introduced silently. These changes
are followed by the mandatory S0 → S1 → S2 sequence; they are not a shortcut
to S2.

The existing unit test for joint names, limits and units must continue to pass;
the implementation must also add or update a model-hash record that identifies
the new source URDF. No Teacher or privileged simulator truth may enter the
control-policy input as part of this work.

## Consequences and mandatory revalidation

An approved URDF geometry change invalidates the previous S0–S4 evidence. It
does **not** permit “restart S2” directly. In order, the work must:

1. rerun all 13 calibrated contact conditions and keep
   `CONTACT_TELEMETRY_PARTIAL` until the fresh result is
   `CONTACT_TELEMETRY_CALIBRATED`;
2. rerun the ten-trial S1 MoveIt-plan → execute → FK gate against the new model;
3. rerun S2 friction trials only after S0 and S1 pass; then recompute S3 and
   S4 fail-closed gates.

Until that sequence completes, prior grasps, videos and B1 Oracle results are
historical evidence only and cannot be used as results for the changed model.

## Approval record

- Human approver: project operator
- Approval timestamp: 2026-07-16 (Asia/Shanghai)
- Accepted candidate: official Panda origins plus fixed `panda_link8` /
  `panda_joint8`; base `[-.35, 0, .45]`; cube `[.22, .12, .475]`; bin centre
  `[.217366447885, -.249990627453, .45]`; bin pre-place
  `[.217366447885, -.249990627453, .60]`. The bin footprint is reduced from
  40 cm to 30 cm so it remains fully supported by the 0.8 m-wide table; the
  non-task green sphere moves to `[.40, .28, .49]` so the relocated bin has no
  t=0 overlap.
- Source URDF SHA-256 before approval:
  `e017d82f218578603078fd5da73cdba88ed47fef2f5ed57cf9f01f5c666fb096`
- Approved implementation URDF SHA-256:
  `2f77f5150f4e4a5a098ab59a56f98216622cfdfd54a0c79dedbe44e19352eff1`
- Required before S0: pass the MoveIt home-state self-collision gate.
  The tested `home` is the collision-checked neutral tucked state
  `[0, -.5, 0, -1.5, 0, 1, 0]`; non-adjacent collisions remain enabled rather
  than being added as SRDF exceptions.  The no-motion candidate probe also
  checked official `ready`, `transport`, and `extended`; those were rejected
  by the conservative primitives, not silently exempted.
- Collider correction during implementation: `panda_link4` now uses the
  conservative axis-aligned bounds of the cited official collision mesh
  (origin `[-.041234, .034430, .027923]` m; size
  `[.192746, .179159, .166259]` m).  This replaces an unrelated 39.3 cm,
  rotated legacy box that collided with link6 in every no-motion probe.
- The legacy `panda_link1` cylinder also reached the tabletop at the retained
  base height.  It is replaced by conservative official-mesh bounds (origin
  `[.000087, -.037090, -.068515]` m; size `[.110148, .184565, .246977]` m).
  Gazebo's seven arm state interfaces explicitly initialize to the verified
  SRDF home; names, limits, units, controllers, and action vectors are
  unchanged.
- The single primitive bounds for `panda_link2` and `panda_link4` created an
  impossible non-adjacent `link2`–`link4` collision at valid targets.  Their
  collision geometry therefore uses the installed, SHA-recorded official Panda
  collision meshes.  This is deliberately *not* an SRDF/ACM exception; the
  pair remains checked, and `xh_sim` declares the resource dependency.
- Required in S1: SRDF/`ADJACENT_SELF_PAIRS` agreement and enabled-pair report
  containing `panda_link8`–`work_table`.
- Revalidation on this exact hash: no-motion home collision gate passed; all
  13 independent S0 conditions calibrated; S1 passed 10/10 MoveIt
  plan→execute→FK trials with the enabled-pair list and exact adjacent-pair
  audit. S2 then stopped after eight real production-table
  `APPROACH_ALIGNMENT_FAILURE/NO_REACH` trials; S3 sent no attach request and
  S4 is blocked for lack of a verified final grasp mode. These are partial
  execution results, not a grasp success claim.
- Implementation commit(s): intentionally uncommitted (`ALLOW_GIT_COMMIT=0`);
  the current worktree and report hashes are the review record.
