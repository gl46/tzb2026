# ADR-0027: Public-depth NO_RETURN schema (Option A) and diagnostic C1/C2 correction

- Status: Accepted (human decision)
- Date: 2026-08-16 (Asia/Shanghai)
- Approver: project owner (gl46)
- Scope: decides `M2C-S4-QWEN-DEPTH-NO-RETURN-ADR-REQUEST.md`; corrects the
  ADR-0026 §2 diagnostic scene conditions; authorizes one fresh one-shot
  Q-B challenge after re-binding. Consumed artifacts are never reused.

## 1. Depth contract — Option A

- Selected option: **A**; Option A approved: **true**; B/C: **false**.
- The versioned formal request/service schema is approved exactly as the
  request's ten clauses specify: one non-empty 2-D `float32` ndarray,
  shape equal to the decoded public RGB; at least one finite sample; every
  NaN and −inf rejected; **+inf permitted only as `NO_RETURN`**; original
  bytes and SHA-256 retained; +inf excluded from public-geometry numeric
  operations with no guessed finite replacement; prompts, weights, candidate
  ordering, heads, B0, public predicates, and all safety/IK/collision/
  controller gates unchanged; raw depth still forbidden as a backbone or
  policy feature; fail-closed on wrong dtype/shape, all-no-return images,
  or RGB/depth/receipt/request identity mismatch.
- Semantics provenance (outcome-independent): ROS REP-117, the standard
  range-image convention — +inf denotes a valid measurement with no return
  inside maximum range; NaN denotes an erroneous measurement. The simulator
  emitting +inf for open space is ordinary, not anomalous.
- Implementation uses a new schema literal and exact-load binding. Contract
  tests replay the frozen scene-15076 depth bytes as schema-valid and keep
  rejecting empty, wrong-rank, wrong-shape, wrong-dtype,
  all-positive-infinity, NaN, and −inf arrays. The consumed challenge
  (nonce `3286b251…`) is never reused; the failed run stays
  `BLOCKED_UNMEASURED`, not a model result.
- Code change authorized: **true** (this schema only). Existing evidence
  reinterpretation: **false**.

## 2. ADR-0026 §2 diagnostic conditions — corrected

The consumed C1 run failed pre-action because removing both blockers left 4
objects against the frozen 6–12 scene-schema bound. ADR-0026 §2 is amended:
conditions relocate rather than remove.

- **C1 (no blocker near target)**: all six cylinders retained; the red and
  green blockers are placed at preregistered far anchors at least
  `MIN_TOP_GRASP_CORRIDOR_RADIUS_M = 0.25 m` from the target anchor and
  outside its descent corridor (provenance: the frozen corridor constant of
  the scene generator).
- **C2 (green only)**: green keeps its V4 pose; red relocates to a far
  anchor under the same rule.
- **C3**: unchanged full V4 layout.
- A fresh diagnostic campaign on new seeds is authorized under the otherwise
  unchanged ADR-0026 §2 protocol (≥12 seeds per condition, fixed order, no
  retry/replacement, measurement only). The consumed diagnostic run is
  recorded and never retried. The §3 decision tree applies unchanged.

## 3. Fresh Q-B challenge

After the versioned depth runtime, verifier, deployment closure, and local
contract tests are committed and every existing entry binding is again
exact, **one** fresh preregistered one-shot challenge with a new nonce,
identity-disjoint from the consumed one, is authorized. Subsequent
challenges follow the same rule (fresh preregistration each; no further
human gate needed per challenge unless an ADR-0024 §4 category is touched).

## Boundaries

No B0 byte, safety/IK/collision/controller gate, public predicate,
privileged-truth boundary, or Teacher rule changes. Trained ADR-0026 bundle
digests (`6e7cb272…` FC / `1b6757dc…` NoFC) are unchanged by this ADR.
Deadline routing stays `BLOCKED_UNMEASURED` where evidence is missing;
2026-08-20 bundle-smoke checkpoint and ADR-0024 §5 stand.
