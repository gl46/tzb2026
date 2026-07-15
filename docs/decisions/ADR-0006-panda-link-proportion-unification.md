# ADR-0006: 机器人连杆比例统一到 Panda 运动学量级，场景与限位不变

Date: 2026-07-16 (Asia/Shanghai)
Status: **PROPOSED — NOT APPROVED**

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
URDF-origin FK sample was required.

## Evidence before decision

[`reports/m1a-fk-workspace-sampling.json`](../../reports/m1a-fk-workspace-sampling.json)
records a deterministic 100,000-configuration uniform sample of the seven arm
joints (seed `20260716`) against the dynamic-world cube target
`[0.22, 0.12, 0.475]` m. It uses collision-centre fingertip points, holds both
finger joints at 0.02 m, and runs no ROS, Gazebo, collision, contact or grasp
operation. The report is bound to source-URDF SHA-256
`e017d82f218578603078fd5da73cdba88ed47fef2f5ed57cf9f01f5c666fb096`.

The hypothetical candidate scales only `panda_joint1`…`panda_joint7` and
`panda_hand_joint` origins by 0.371212121. It leaves `world_to_panda`, the two
finger joints, hand/finger geometry and finger collision-centre offsets
unchanged. That gives 0.85 m nominal total reach: 0.735 m scaled arm/wrist
serial translation plus 0.115 m unchanged end-effector extension.

| FK model | Closest sampled pad centre | 3 cm density | 5 cm density |
| --- | ---: | ---: | ---: |
| Current controlled URDF | 1.67 cm | 3/200,000 (0.0015%) | 10/200,000 (0.0050%) |
| 0.85 m candidate, base/scene unchanged | 14.23 cm | 0/200,000 | 0/200,000 |

The result is evidence against approving the exact initial candidate. It does
not prove a mathematical workspace bound, but it does show that this candidate
does not provide sampled access to the required target neighbourhood. Moving
the cube farther in +x would not repair that measured shortfall with the
current fixed base. No URDF, scene, controller or end-effector change has been
made by this ADR or the sampling run.

## Decision requested

Do **not** approve an implementation of the exact “0.85 m total reach, fixed
base and unchanged scene” candidate from this evidence. A human must instead
approve one of the following explicitly scoped next decisions before any model
edit:

1. a revised Panda-scale kinematic candidate with an offline target-density
   result that reaches the task target; or
2. a base-placement change, accompanied by the same FK evidence and a revised
   task-scene rationale; or
3. rejection of the link-proportion remedy in favour of another human-approved
   geometry decision.

The human approval must name the exact candidate (joint-origin scale, base
transform and cube pose if any change), its source report and its URDF revision.
This ADR title describes the requested direction; its current status is not an
authorization to alter the model.

## Invariants for any approved implementation

An approved implementation must preserve all of the following:

1. `panda_joint1`…`panda_joint7` and both finger joint names, lower/upper
   limits, radians/metres units and controller action interfaces;
2. the calibrated hand, fingers, finger collision geometry and contact sensor
   topic names; and
3. the controller/MoveIt same-URDF requirement, explicit collision policy and
   SRDF collision-pair reporting.

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

- Human approver: **pending**
- Approval timestamp: **pending**
- Exact model/base/scene candidate: **pending**
- Implementation commit(s): **pending**
