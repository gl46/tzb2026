# ADR-0019: M2B failure-rich data and bounded model activation

- Status: Accepted for the bounded M2B experiment
- Date: 2026-07-31
- Human direction: execute the supplied M2B failure-rich QRM goal
- Parent evidence: M2A commit `1c83776c91c6a9c5e7bf2d873d20da367ffdff81`

## Context

M2A proved the dual-RTX Isaac data engine and the
Isaac-to-A100-to-checkpoint-to-Isaac path, but its Pilot corpus contains no
physical `EMPTY_GRASP`, `WRONG_OBJECT`, or `RELEASE_FAILURE` trajectories.
FailureContext therefore has only limited variation, the residual target is
not tied to a successful corrective action, and every live model decision was
rejected by an unconditional integration gate before B0 executed.

## Decision

1. Freeze M2A commit `1c83776` and Dataset V1 as read-only evidence.
2. Build Dataset V2 around physically observed failure and recovery events,
   with scene/failure-seed grouped splits.
3. Generate residual supervision only from bounded perturbation-correction
   pairs. Privileged simulator targets are training-only labels.
4. Establish a versioned canonical skill registry and explicit runtime
   mapping. No frame, unit, parameter, track, or action mapping is inferred.
5. Keep schema, range, track, IK, collision, controller, and safety gates in
   front of execution. Invalid decisions fall back to B0 and cannot count as
   model successes.
6. Require at least 20 accepted and executed model decisions before reporting
   QRM task performance.
7. Compare B0, NoFC, FC, and MLP only on matched unseen scene/failure seeds.
8. Flow and online Shadow remain disabled. No Teacher participates.

## Checkpoint compatibility addendum

M2B adds explicit recovery skills to the coarse label and current-stage
vocabularies.  This is a named `M2B_Q012_V1` architecture revision.  Frozen
M2A checkpoints remain loadable only through their exact
`M2A_BETA1_LEGACY_V1` 110-input/70-output layout; tensors may not be silently
padded, truncated, or reinterpreted.  New checkpoints record their schema and
architecture revision.

## Runtime boundary

The model may select a registered coarse skill and bounded parameters. Public
RGB-D, tracks, robot state, TaskSpec, and FailureContext are policy inputs.
Entity/prim identity, perfect poses, contacts, injected-failure truth, and
task-success truth remain under training/evaluation-only supervision.

## Governance scope

This ADR authorizes a bounded M2B experiment; it does not retire or replace
the repository's mandatory world-model mainline. Any broader mainline change
still requires a separate human ADR and merge decision.

## Teacher boundary and kill rules

Teachers are unused. Nano remains `CANDIDATE`, BWM remains
`CANDIDATE_LICENSE_PENDING`, and Super remains `PARKED`. Any Teacher entering
the data labels or runtime control stack kills the affected run. Current
Teacher kill-rule events: **none**.
