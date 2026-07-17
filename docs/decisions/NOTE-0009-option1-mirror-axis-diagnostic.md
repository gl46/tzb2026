# NOTE-0009: ADR-0007 Option 1 diagnostic outcome

Date: 2026-07-16 (Asia/Shanghai)

## Scope

This note records the bounded diagnostics approved under ADR-0007 Option 1.
They used no object contact, no pose writes, no friction/mass/solver change,
and no persistent model change.

## Results

1. Gazebo's direct `gz model` link-pose query shows q1's left-finger link does
   not move during `[0.010, 0.040] m`, while q2's right-finger link moves during
   `[0.040, 0.010] m`. This rules out a ROS-only joint-state readout failure.
2. The spawned SDF exposes both prismatic joints with the expected common
   origin, `+Y` / `-Y` axes, and `[0, 0.04] m` limits. The only hand plugin is
   `gz_ros2_control`; no plugin contains a finger-link or finger-joint-specific
   mapping.
3. With `[0.015, 0.035] m`, q1 remained physically stationary and q2 moved by
   about `0.005 m`, matching q2's own target rather than q1's. This does not
   support an index cross-wire explanation.
4. The temporary mirror overlay used q1 `axis="0 -1 0"`, a pi joint-frame
   rotation, and mirrored local X pad geometry. It preserved q1/q2 names,
   `[0, 0.04] m` limits, collision/sensor geometry in world space, and positive
   value = open. Its SHA was
   `84e213f849c16bb294e65c63a45a9c217f8a88e292969528bdc1d1c17033ab2c`.
   Its isolated no-contact probe repeated the failure: q1 stayed at `0.040 m`
   for q1-only and bilateral close commands, whereas q2-only reached `0.010 m`.

The manual mirror runtime record is
`logs/m1a-20260716-hand-mirror-axis-08-manual.json`. The first three diagnostics
are retained in `logs/m1a-20260716-option1-diagnostic-04.log` and
`logs/m1a-20260716-option1-diagnostic-06.log`.

## Cleanup and decision

Both remote source and install overlays were restored to the approved SHA
`2f77f5150f4e4a5a098ab59a56f98216622cfdfd54a0c79dedbe44e19352eff1`.
The temporary Gazebo sessions were terminated. The signed-axis convention is
not a valid Option 1 repair, and the approved three-hour diagnostic policy bars
further Open-ended Option 1 investigation.

The next candidate is [ADR-0008](ADR-0008-panda-mimic-compatibility-adapter.md),
which is proposed only and needs a new human approval before any model change.

- Changed files: this note and ADR-0007's outcome record.
- Verification: direct link-pose observation, spawned-SDF inspection,
  asymmetric command, and isolated mirror probe.
- Failure: q1 remains physically unable to close under both original and
  mirror-axis configurations.
- Blocker: a Panda mimic model changes labelled single-finger calibration
  semantics and needs explicit approval.
- Next command: approve or amend ADR-0008; do not run S0/S1/S2/S3/S4 yet.
