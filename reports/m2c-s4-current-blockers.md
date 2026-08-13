# M2C S4 current blockers

- Status: **BLOCKED_UNMEASURED_HUMAN_DIRECTION_REQUIRED**
- Checked HEAD: `e33f86a3cfeb43814faaec54ed13e07f177314ab`
- Q-A: **PASSED**
- Q-B: **UNMEASURED**
- `pure_model_success_episodes`: **null**, not zero
- D1 / D2: **false / false**

## PATH_BLOCKED training entry

The frozen V3 manifest contains 36 TRAIN keys. Three outcome-blind collection
batches attempted 11 unique keys and produced 10 byte-verified scripted
eight-step chains. None satisfied the unchanged public success predicate and
therefore no row was packaged or marked training-eligible. Training, model
rollout, and formal Q-B evaluation remain unexecuted.

Batch-03 exhausted its fixed three-key, no-retry/no-replacement authorization.
Scene 16073 exposed a public-track association limitation after a physically
successful lift; its frozen public predicate still returned false. The physical
receipt cannot backfill public success. A fourth batch or a changed tracker is
not authorized by current bytes.

Human direction is required on
`docs/decisions/M2C-S4-PUBLIC-TRACK-REID-ADR-REQUEST.md` (A/B/C). Option A
requires a complete, outcome-independent PublicTrackAssociatorV2 contract and
then a separate wholly-new TRAIN-key preregistration; option B stops PATH; C
must be equally complete. Code may not infer a choice or numeric thresholds.

## ADR-0022 Phase-2 entry

The exact-plan A.3 contract now recomputes canonical physical-state digests,
checks full cross-phase state continuity, phase allowlists and phase/config
timeouts, and strictly replays every limit, workspace, collision, attachment,
controller and safety predicate. It remains hard-coded
`formal_execution_eligible=false` and lacks a trusted host append-only signing
receipt.

The Isaac 6.0.1 query capability audit binds nine installed source/binary/asset
files but reports all production capabilities `NOT_AVAILABLE`. Lula has no
accepted zero-write proof, its public solver does not support collision
avoidance, and no reviewed hypothetical attachment/contact query or active-
session mutation-counter backend is bound.

A bounded MoveIt/KDL/Bullet audit found a possible future pure-computation
backend, but not a complete A.3 implementation: Bullet provides continuous
robot-world collision but not continuous moving-link/moving-link self-
collision. Terminal two-finger/object geometry can be queried, but it cannot
prove real bilateral contact, force closure, controller readiness, or active-
session attachment. It therefore cannot unlock the gate.

The frozen M2B B0 has no callable that can continue the already-evolved formal
Isaac session. Starting its standalone runner creates a different episode, and
reassembling low-level helpers would be a new B0 implementation. Human
direction is required on
`docs/decisions/M2C-S4-B0-ACTIVE-SESSION-FALLBACK-ADR-REQUEST.md` (A/B/C).

All four source bindings remain literal `None`; no binding addendum or unlock
config was generated.

## Boundaries and verification

- Teacher use: **false**; Nano/BWM/Super remain CANDIDATE /
  CANDIDATE_LICENSE_PENDING / PARKED.
- Privileged simulator truth as policy input: **false**.
- B0, M2B evidence, safety/IK/collision/controller/schema gates: unchanged.
- Additional collection after Batch-03: **false**.
- Training / physical SMOKE / formal Q-B evaluation: **false / false / false**.
- Related contract regression: **102 passed**.
- Failures: no product-test failure; the outcome is a deliberate fail-closed
  blocker.

Next command:

```bash
sed -n '1,280p' docs/decisions/M2C-S4-PUBLIC-TRACK-REID-ADR-REQUEST.md && \
  sed -n '1,260p' docs/decisions/M2C-S4-B0-ACTIVE-SESSION-FALLBACK-ADR-REQUEST.md
```
