# ADR-0014: Pause M1B simulation until per-object detach reset is verified

Date: 2026-07-18 (Asia/Shanghai)
Status: **APPROVED — project owner authorized the model/control repair in Codex conversation**

## Context

ADR-0013 requires every generated DetachableJoint to be detached before an
episode begins.  A live M1B launch initially ran the physics loop while all
12 child cylinders were auto-attached to `panda_link7`.  The later reset did
detach all 12 topics, but the intervening welded multi-object physics state
left the Panda hand feedback invalid.  An isolated M1A probe with the same
URDF/SDF hash passed all q2-master physical-mimic checks, identifying startup
order—not an alternative hand model—as the supported repair target.

## Decision

For M1B only, start Gazebo paused after the industrial world loads.  Spawn the
generated Panda model and initialize its ROS controllers while paused; then
the actuation-internal reset utility must detach and observe every generated
cylinder.  It may issue the world-resume request only after `RESET_VERIFIED`.
Any missing state leaves the world paused and returns `INVALID_RESET`.

M1A retains its existing immediately-running launch path.  No joint, link,
sensor, controller interface, mimic relation, unit, or action mapping changes.

## Approval record

- Project owner: **authorized repair in Codex conversation on 2026-07-18**
- Scope: M1B startup lifecycle and reset ordering only
- Required evidence: paused M1B reset 12/12, post-resume hand preflight,
  then ADR-0013 physical round-trip and wrong-object drill.
