# ADR-0005: MoveIt / Gazebo controlled-model unification for M1A

Date: 2026-07-16 (Asia/Shanghai)
Status: **ACCEPTED — 2026-07-16 (Asia/Shanghai)**

## Context

M1A S1 on node2 established that Gazebo controls
`robot_ws/src/xh_sim/urdf/panda_controlled.urdf`, while the current MoveIt
smoke launch builds `moveit_resources_panda`. This violates the M1A requirement
that planning and Gazebo execution use one robot model. The S1 runner correctly
returned `BLOCKED`, with zero trajectory dispatches; no grasp or B1 result is
claimed.

The controlled URDF is a Panda-compatible, primitive-inertia model. It is
suitable only for the stated controller and contact-telemetry experiments; it
is not evidence of a high-fidelity Franka model. The decision must preserve
the action protocol: seven named arm joints in radians, two finger joints in
metres, and standard trajectory actions with recorded feedback.

## Decision requested

Approve or reject the following scoped M1A decision:

> Use `panda_controlled.urdf` as the sole robot-description source for both
> MoveIt and the node2 Gazebo controller in M1A. Generate or maintain a
> project-local MoveIt configuration from that exact URDF; do not substitute
> the official Panda resource as the runtime planning model.

If accepted, implementation must additionally:

1. retain the current `panda_joint1`…`panda_joint7` and finger joint names,
   limits, units, controller endpoint and frame provenance;
2. add table and bin collision objects to every M1A planning scene;
3. record SHA-256 for the MoveIt and Gazebo model sources in every S1 run;
4. prove standard-action dispatch, continuous `/joint_states`, FK end-effector
   error, and anti-teleport gates in ten three-segment trials;
5. leave Teacher and simulator oracle data outside the control-policy input;
6. preserve an explicit rollback path to the current planning-only smoke
   without relabelling it as execution.

## Alternatives considered

1. **Keep `moveit_resources_panda` for planning and bridge it to Gazebo.**
   Rejected unless a future ADR proves identical model, joint limits and frames.
   Current evidence contradicts that condition.
2. **Use direct `FollowJointTrajectory` without MoveIt.** Rejected for M1A
   completion: it can verify a controller but not the required MoveIt execution
   chain or collision scene.
3. **Replace the Gazebo robot with the official Panda model.** Not selected by
   this proposal: it would be a broader simulator/model change and requires a
   separate ADR with new contact and controller validation.

## Consequences and validation gate

Accepting this ADR enables implementation work but does not itself satisfy S1.
The first success criterion remains `VERIFIED_MOVEIT_EXECUTION`; no S2, S3 or
S4 experiment may be claimed before it. Failure to meet the same-URDF or
anti-teleport gates returns M1A to `BLOCKED`/`PARTIAL`, not PASS.

## Approval record

- Human approver: project operator
- Approval timestamp: 2026-07-16 (Asia/Shanghai)
- Accepted option: project-local MoveIt configuration sourced from
  `panda_controlled.urdf`
- Implementation commit(s): pending
