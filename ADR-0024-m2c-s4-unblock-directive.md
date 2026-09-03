# ADR-0024: S4 unblock directive — three decisions, evidence bar, escalation rule

- Status: Accepted (human decision)
- Date: 2026-08-13 (Asia/Shanghai)
- Approver: project owner (gl46)
- Scope: decides `M2C-S4-PUBLIC-TRACK-REID-ADR-REQUEST.md`,
  `M2C-S4-B0-ACTIVE-SESSION-FALLBACK-ADR-REQUEST.md`, and
  `M2C-S4-A3-CONTINUOUS-SELF-COLLISION-ADR-REQUEST.md`; sets the project
  evidence bar; authorizes Batch-04 preparation. Each decision below completes
  the corresponding request's approval fields explicitly; nothing is inferred.

## 1. Public track re-identification — Option A

`PublicTrackAssociatorV2` is authorized with the following frozen contract.

- **Allowed inputs**: exactly the four input groups listed in the request's
  Option A "Exact allowed inputs"; everything on its forbidden list stays
  forbidden.
- **Motion hypotheses** (the only two):
  - `STATIC`: predicted position = prior track position.
  - `HAND_CARRY`: predicted position = prior track position + (end-effector
    world displacement between the two captures). Eligible only when the
    gripper was closed for the whole interval and the last physically executed
    public skill is one of `GRASP`, `LIFT`, `MOVE`, `REGRASP`. The skill name
    selects hypothesis eligibility only.
- **Association gate**: 0.12 m Euclidean distance between a current detection
  and a hypothesis-predicted position. Provenance: the unchanged
  `public_temporal_tracker_v1` gate, reused per hypothesis;
  outcome-independent.
- **Cost and matching**: cost = min over eligible hypotheses of the Euclidean
  distance to the predicted position, after category and `visual_color`
  equality prefilters (unchanged V1 fields). Costs quantized to 1e-6 m.
  Deterministic one-to-one global matching: minimum-total-cost assignment;
  among equal-cost optima, the lexicographically smallest assignment ordered
  by (prior `track_id`, detection centroid x, y, z).
- **Ambiguity margin**: 0.02 m. If, for a given detection, the best and any
  admissible alternative identity assignment differ by less than 0.02 m in
  cost, no prior ID is assigned; the prior ID is absent from the fresh
  observation and downstream stale-pointer handling stays fail-closed.
  Provenance: the ceiling of the measured M1B Isaac r3 perception tolerance
  envelope X/Y (10/15 mm), measured 2026-07-29, outcome-independent of
  scene 16073.
- **Lifecycle**: strict timestamp monotonicity; a prior track is retained for
  at most 2 consecutive captures without a match, then expires; expired or
  unmatched prior tracks are never emitted as current observations; unmatched
  detections get deterministic new public IDs; frame/unit/calibration-hash
  equality is mandatory; no TaskSpec-, receipt-, or outcome-conditioned
  override.
- **Revisions**: `PublicTrackAssociatorV2`, `PathBlockedPublicObservationV4`,
  `PublicTrackCandidateV4` (ADR-0021 ordering semantics unchanged, carried
  over verbatim onto V4 observations), `M2C_Q012_V4`. Exact-load guards
  reject cross-revision checkpoints/observations. V1 evidence, scene-16073
  bytes, and `final_task_success=false` keep their original meaning; no
  replay is a new physical outcome.
- The V1 0.12 m gate for V1 evidence, the 0.03 m original-site predicate
  gate, all public predicates, B0, and every safety gate remain unchanged.

Approval fields: option **A**; numeric gates 0.12 m (V1 provenance) and
0.02 m ambiguity margin (M1B r3 envelope provenance); revisions as above;
new-key preregistration required per section 5; approver/date as in header.

## 2. Active-session B0 fallback — Option B

ADR-0020 §7.4 and ADR-0022's fallback clause are amended by this human
decision to:

```text
invalid pointer / stale track / invalid cell / invalid mapping /
preflight rejection -> terminal NO_PHYSICAL_EXECUTION
```

The episode is a failure, stays in the evaluation denominator, and is always
excluded from strict-pure success. No local hold, substitute action, new B0
implementation, cross-scene runner, retry, or fixed continuation executes.
The M2B B0 stays byte-identical (`1e32fa89…`) and remains the independent B0
comparison arm in separate episodes. `FrozenB0FallbackWrapperV1` and
ADR-0022 §A.5 are withdrawn as no longer required; the receipt/mapping
attribution `NO_PHYSICAL_EXECUTION`, terminal-failure journal, and revised
entry-gate contract required by the request are authorized. No-action may
never be relabelled `B0_FALLBACK`.

Approval fields: option **B**; §7.4 superseded as quoted; approver/date as in
header.

## 3. A.3 continuous self-collision — Option A with bounded delegation

The conservative convex-hull envelope of every decoded STL vertex (A.3
preflight only) plus child-by-child `btContinuousConvexCollision` over every
non-ACM pair is authorized, exactly as scoped in the request's Option A,
including compound expansion, fail-closed handling of unknown/concave/
malformed/non-finite shapes, and separate discrete checks at initial overlap,
both endpoints, and every subdivision boundary.

For the numeric table, this human decision is a **bounded delegation**: the
implementation proposes each value; every value is recorded with its source
in the Phase-2 binding addendum; and every value must satisfy these
human-set bounds and the governing principle that **every ambiguity resolves
toward rejection** (false rejections are acceptable; missed collisions are
not):

- Bullet scalar ABI: `float64` (double-precision build), pinned by package
  and build digest in the addendum.
- Convex-hull construction tolerance: ≤ 1e-6 m.
- Post-construction padding: ≥ 0.002 m outward only.
- Per-shape collision margin: ≥ Bullet's shipped default for the shape type;
  margins may only enlarge the envelope.
- Allowed penetration: 0.0 m.
- Contact-distance threshold: ≥ 0.001 m (a contact within threshold rejects).
- TOI interval: [0, 1] closed; comparison tolerance ≤ 1e-6, rejection-biased.
- Maximum CCD iterations: ≥ 32; iteration exhaustion rejects the plan.
- Subdivision: any step whose swept displacement exceeds the smallest shape's
  conservative radius is subdivided; failure to subdivide rejects.

A parameter whose conservative direction is genuinely ambiguous escalates as
a finding; everything else is decided by implementation within these bounds.
The hull may never be cited as geometry equality, and executor geometry, B0,
and recorded evidence remain unchanged.

Approval fields: option **A**; numeric values by bounded delegation as above,
recorded in the binding addendum; approver/date as in header.

## 4. Evidence bar and escalation rule (standing direction)

The evidence standard that produced the accepted M2B, Q-A V4, and S3
evidence — immutable Git-tree snapshot, container/image ID, SHA-256 evidence
ledgers, and session-bound receipts — **is the project's evidence bar**, set
by the project owner.

- `V3_HOST_RUNTIME_LAUNCHER_BINDING`-style pre-interpreter attestation and
  trusted-host append-only signing receipts are **not required** and are
  rescinded as collection preconditions. The existing bar is sufficient for
  the canonical V3 CLI and for the four Phase-2 bindings.
- Codex must not introduce new human-approval locks beyond the boundaries of
  accepted ADRs. A newly discovered concern is recorded as a finding and
  defaults to the existing evidence bar unless it touches B0 bytes, a safety/
  IK/collision/controller/schema gate, the privileged-truth boundary, or
  Teacher use — only those four categories escalate to a human decision.
- Deadline routing stays as committed: missing evidence is
  `BLOCKED_UNMEASURED`, never a measured zero.

## 5. Batch-04 and schedule authority

- After `PublicTrackAssociatorV2` passes local tests, Codex is authorized to
  commit an outcome-blind Batch-04 preregistration of wholly new TRAIN keys,
  identity-disjoint from every attempted V1/V3 TRAIN or SMOKE key and every
  V4 Q-A, S6, or matched-evaluation key, with fixed key order, stop count,
  and no-retry/no-replacement rule — and to run it without a further human
  gate. Subsequent batches under the same contract need only their own
  outcome-blind preregistrations.
- The uncommitted S6 preregistration SHA drift (2 failures / 5 errors) must
  be resolved honestly in the next commit: either commit the drifted files
  with a recorded reason or restore the frozen bytes; tests must return to
  green.
- If `M2CExactPlanPrimitiveBundleV1` has not passed its contract smoke by
  **2026-08-20**, Codex must propose (not silently apply) a reduced-chain
  scope for human sign-off within the same day.
- Nothing in this directive weakens B0, any gate, the privileged-truth
  boundary, or Teacher rules. Teachers remain unused; kill rules unchanged.
