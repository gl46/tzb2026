# ADR-0013: Per-object detachable grasp actuation and camera-to-world calibration for M1B industrial scenes

Date: 2026-07-18 (Asia/Shanghai)
Status: **APPROVED — implementation authorized by project owner in Codex conversation**

## Context

M1B-beta is blocked: the industrial world publishes `cylinder_01…12` contact
topics, but the robot model carries only the M1A single-cube DetachableJoint.
Grasping real cylinders requires per-object attach plumbing and an RGB-D → 
execution frame convention. [ADR-0011](ADR-0011-non-oracle-grasp-broker.md)
defines the non-oracle data boundary but explicitly adds no model change; this
ADR is the model/actuation change that implements it. M1A evidence that binds
this design:

- GATE4 established that each DetachableJoint **auto-attaches at world start**
  and that a detach-first reset is mandatory (M0 runner convention).
- The M1A contact gate condition "`target_id` equals the task target" is an
  oracle leak (it silently prevents wrong-object grasps from ever occurring);
  it must be replaced, not carried forward.

## Decision requested

Approve the following four contracts as one change set.

### 1. Per-object DetachableJoint generation

- The spawn-SDF generator consumes the scene object manifest emitted by
  `generate_industrial_scenes.py` and emits **one DetachableJoint plugin block
  per graspable object**: `parent_link` `panda_link7`, `child_model` from the
  manifest, topics `/xh/m1b/<object>/attach`, `/xh/m1b/<object>/detach`,
  output `/xh/m1b/<object>/grasp_state`.
- Generation is deterministic; the generated SDF, generator, and scene manifest
  SHA-256 triple is recorded per run (extends the M1A manifest discipline).
- The whitelist diff extends to exactly: 1 mimic block + N detachable blocks.
  Any other delta fails closed.
- The M1A cube production world and its regression path remain untouched.

### 2. Startup and reset detach contract

- Because every DetachableJoint auto-attaches at world start, a fresh N-object
  world begins with **N welds to `panda_link7`**. Episode reset MUST broadcast
  detach on all N topics and verify all N `grasp_state` values read `detached`
  before the episode may begin; the N-state record enters episode provenance.
- Any unobtainable `grasp_state` → `INVALID_RESET`, fail-closed, episode does
  not count.

### 3. Broker contact-driven entity selection (implements ADR-0011)

- At attach time the actuation-internal broker reads finger contact pairs,
  requires **both fingers contacting the same physical body**, and selects that
  body's attach topic. Contact-pair entity names exist only inside the broker,
  as firmware-equivalent state.
- The M1A gate condition "`target_id` equals the task target" is **replaced**
  by "bilateral same-entity contact". Task-level identity verification moves to
  perception: after a successful attach, the carried track is re-observed and
  compared with the commanded target track; a mismatch raises a
  `WRONG_OBJECT` failure into the online loop (recovery), and supervision
  records `actual_sim_entity_id` + `wrong_object` for evaluation only.
- All other numeric gates carry over unchanged (bilateral overlap >= 100 ms,
  relative speed, corridor, recent close command). The gripper-width window
  becomes per-object-class configuration derived from **perceived** object
  dimensions with a conservative clamp; supervision dimensions may audit but
  never feed the online check.
- The broker's public return is exactly: `grasp_success`, generic tactile
  summary, and a re-observation request for the carried track. No entity name
  crosses the boundary (unit-tested by field-absence assertions).

### 4. Camera-to-world calibration contract

- Perception outputs poses in the RGB-D optical frame. Conversion to the
  planning frame uses **only the TF tree published from the robot and scene
  description** (static extrinsics are robot self-knowledge and permitted).
- Forbidden at runtime: reading object poses or camera pose from Gazebo
  services on the online path.
- Each episode records frame names, the transform values, the TF source, and
  a hash of the chain.
- Calibration is validated offline against supervision (median 3D error of
  perceived objects; budget consistent with the M1B-alpha <= 2 cm gate).
  Calibration error counts toward perception error and is never separately
  excused.

## Acceptance before M1B-beta unblocks

1. Generated SDF contains exactly N detachable blocks; whitelist diff and hash
   triple recorded.
2. Fresh session: after the reset broadcast, all N `grasp_state` values are
   observed `detached` (evidence retained).
3. One-cylinder physical round-trip on the industrial world: approach → close
   → bilateral same-entity contact → attach → rigid-follow verification →
   detach → decouple (the GATE4 coupling check, executed on a cylinder).
4. **Wrong-object drill**: deliberately grasp a non-target cylinder. The broker
   must attach it (physics stays honest), post-grasp perception must flag the
   track mismatch, recovery must trigger, and supervision must record
   `wrong_object = true`. This is the direct proof that the M1A oracle leak is
   sealed — the old design would have refused the attach and hidden the
   failure class entirely.
5. The M1A cube regression suite still passes.
6. New unit tests: broker field-absence (no entity ids in Observation-path
   fields), reset-verification fail-closed, per-class width clamp.

## Approval record

- Human approver: **project owner, approved in Codex conversation on 2026-07-18**
- Per-object DetachableJoint generation: **APPROVED**
- Reset detach contract: **APPROVED**
- Broker same-entity selection replacing target-id gate: **APPROVED**
- TF-only camera calibration contract: **APPROVED**
- Implementation SHA: **PENDING**

## Amendment 1 (2026-07-19): physical non-coupling reset verification

Status: **APPROVED — implementation authorized by project owner in Codex conversation**

Rationale: the Gazebo DetachableJoint system publishes `grasp_state` only on a
state transition — no latch, no periodic republish, no query service (already
evidenced in M1A GATE4: re-requesting the current state produces no message).
One-shot messages race subscription setup across N topics, and a missed
message is indistinguishable from a failed detach, so message-receipt
verification cannot be made reliable without modifying the plugin.

Change to §2 verification:

1. After the detach broadcast, reset verification is a **physical
   non-coupling check**: command a bounded arm jog (EE displacement >= 0.02 m
   inside the home-safe volume), record all N object poses before and after
   (supervision-side, reset-provenance only). PASS iff no object displaces
   more than the settle-noise threshold (1 mm).
2. Any displacement above threshold → `INVALID_RESET`, fail-closed
   (unchanged).
3. `grasp_state` messages are collected best-effort and retained as auxiliary
   evidence; a missing message is a warning, not a failure, when the physical
   check passes.
4. The jog and pose reads are reset-infrastructure evidence
   (evaluator-side), never Observation-path inputs (consistent with
   ADR-0011).
5. Optional later hardening, not required to unblock: a project-local
   DetachableJoint variant with periodic state publication may replace this
   check after its own whitelist/manifest review.

Amendment approval:

- Human approver: **project owner, approved in Codex conversation on 2026-07-19**
- Physical non-coupling verification replacing 12/12 message receipt: **APPROVED**
