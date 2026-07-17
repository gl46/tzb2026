# NOTE-0007: Production-table grasp orientation family

Date: 2026-07-16

## Decision

Continue S2 using only the remaining seven total-attempt slots with a
collision-checked approach-pose family.  This is not a physical-model change:
the controlled URDF, world, Panda joint protocol, controller interfaces,
contact sensors, S0/S1 reports, and S3 contact-gate thresholds remain intact.

## Evidence and scope

The prior eight production-table S2 attempts all returned collision-checked
IK `-31` or did not execute.  The old horizontal side-grasp aligns the finger
centreline to the cube centre at `z=0.475 m`, while the hand collision body
extends `0.055 m` below that centreline.  It necessarily intersects the table
whose top is `z=0.450 m`; this is a pose-family incompatibility, not a sensor,
friction, or controller defect.

The replacement evaluates, in order:

1. fingertip-down with world-Y closing;
2. fingertip-down with world-X closing;
3. 60 degree and 45 degree inclined side candidates;
4. pure side only when the target centre is at least `0.065 m` above the table.

Each eligible candidate records its runtime-oracle target pose, hand pose,
collision-checked IK result (`-31` or solution), planning/execution result,
and the selected candidate.  The production cube is intentionally not moved
to the high S0 calibration fixture; that fixture stays `CALIBRATION_ONLY`.

## Safety invariants

- finger tips retain a `0.010 m` clearance above the `0.450 m` table top;
- the exact MoveIt table primitive is re-read before IK and its object padding
  must be no greater than that clearance;
- target corridor evidence is calculated in `panda_hand`, never by assuming a
  world-up grasp direction;
- the existing `0.045–0.070 m` S3 width gate is unchanged;
- no DetachableJoint request is permitted during S2.

This narrow approach correction is the user-approved response to the prior
`CUMULATIVE_EIGHT_APPROACH_ALIGNMENT_FAILURES` stop.  The historic eight
trials remain counted and immutable in the consolidated S2 report; this note
does not erase them or reset the total cap of fifteen.
