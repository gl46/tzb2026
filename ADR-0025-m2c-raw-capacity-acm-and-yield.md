# ADR-0025: V4 raw detection capacity, A3 ACM correction, and yield directive

- Status: Accepted (human decision)
- Date: 2026-08-14 (Asia/Shanghai)
- Approver: project owner (gl46)
- Scope: decides `M2C-S4-V4-RAW-DETECTION-CAPACITY-ADR-REQUEST.md`; grants a
  bounded, provenance-backed authorization for A3 start-state ACM
  correction; directs a training-eligibility yield report. Boundaries of
  ADR-0020/0021/0022/0024 otherwise unchanged.

## 1. Raw public-detection capacity — Option A

- Selected option: **A**
- Exact `max_raw_public_detections`: **32**
- Independent numeric provenance: 4× the maximum entity count of the frozen
  IndustrialCylinderBenchmarkV1 scene contract (6 dynamic cylinders + work
  table + partition bin = 8 scene entities; a 4× factor bounds quadruple
  public component splits per entity). Derived from the frozen scene
  configuration, not from any observed capture; the observed maximum 13 was
  not used.
- Every unassociated public detection up to 32 passes to
  `PublicTrackAssociatorV2` without truncation or outcome-dependent
  filtering; association, lifecycle, ambiguity, and new-ID rules stay
  exactly as approved in ADR-0024 §1.
- Does final candidate K remain exactly 8?: **YES** —
  `PublicTrackCandidateV4` role ordering and truncation unchanged.
- More than 32 raw detections remains fail-closed.
- The new value and revision are bound in the raw schema, deployment receipt,
  host replay, checkpoint metadata, and tests.
- May immutable scene 19083 raw bytes be replayed offline after the revised
  implementation and tests pass?: **YES** — offline only; its physical
  outcome (`final_task_success=false`, terminal contact-gate rejection)
  stays authoritative and may not be reinterpreted.
- Are physical retry/replacement or outcome reinterpretation authorized?:
  **NO**.
- Approver/date: project owner (gl46), 2026-08-14.

## 2. A3 start-state ACM correction (bounded pre-authorization)

The query-only A3 smoke found `panda_hand`–`panda_link7` and
`panda_link2`–`panda_link4` overlapping at the frozen discrete start state
with neither pair disabled in the frozen SRDF. Because A3 hulls are
deliberately conservative outer envelopes (≥2 mm padding plus shipped
margins), kinematically adjacent or permanently-near link pairs can register
as overlapping without any real collision. Left unaddressed, every
synthesized plan will fail A3 at the start state.

This human decision authorizes adding `disable_collisions` (ACM) entries to
the controlled-Panda SRDF **only** for link pairs that satisfy at least one
of, with byte-bound evidence for whichever is claimed:

- (a) the pair is listed as disabled in the official upstream
  `franka_description`/MoveIt Panda SRDF (provenance: the pinned upstream
  source and its hash); or
- (b) the pair's **original mesh geometry** (not the inflated hulls) is
  proven overlapping or within 1 mm at the frozen nominal start state by a
  recorded query-only check.

Constraints: ACM entries are per-pair and enumerated in the Phase-2 binding
addendum with their (a)/(b) evidence; no wildcard or category-level
disabling; no margin, padding, hull, or threshold change is authorized by
this section; pairs that fail both tests stay enabled and continue to reject.
An entry justified by (b) must also record why the overlap is kinematically
permanent (adjacent joint or fixed attachment), otherwise it escalates back
to a human decision.

## 3. Training-eligibility yield report (directive, not a contract change)

Across V3+V4, 19 TRAIN identities have produced 11 complete eight-step
chains but 0 training-eligible rows, and the scripted chain's terminal
regrasp has now been rejected by the unchanged contact gate in at least three
independent scenes (V3 9038, V3 existence attempts, V4 19083). Before the
next large collection batch, Codex must commit a short report stating:

1. the exact training-eligibility predicate for a PATH_BLOCKED row —
   in particular whether `final_task_success=true` is required, and if so,
   whether intermediate model-supervisable steps of a failed chain are
   usable as labels under ADR-0020 §5 (state the answer from the frozen
   bytes; do not change the predicate);
2. the measured per-key eligible-chain yield to date and the implied number
   of keys needed for the S4 training target at that yield;
3. a root-cause read of the recurring terminal contact-gate rejections
   (perception offset, approach geometry, or object state), as a finding
   only — no gate, threshold, or B0 change is authorized;
4. if the implied key count is infeasible before 2026-08-20, the report must
   say so plainly; scope reduction remains a human decision per ADR-0024 §5.

## Boundaries

No B0 byte, safety/IK/collision/controller/schema gate (beyond the §2 ACM
entries), privileged-truth boundary, or Teacher rule is changed. Teachers
remain unused; kill rules unchanged. Deadline routing stays
`BLOCKED_UNMEASURED` for missing evidence.
