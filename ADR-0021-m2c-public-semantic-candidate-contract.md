# ADR-0021: Public semantic-role candidate contract (PublicTrackCandidateV3)

- Status: Accepted for the bounded M2C Q-B experiment (human decision)
- Date: 2026-08-13 (Asia/Shanghai)
- Selected option: **A** of `docs/decisions/M2C-S4-PUBLIC-CANDIDATE-ADR-REQUEST.md`
- Parent: `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md` (amended only in
  the candidate-construction clause of its section 2; everything else stands)
- Timing disclosure: this contract was designed after observing the 11
  TRAIN-key collection attempts under the K=8 literal-ID contract (8 target
  outside K=8, 2 gate-rejected regrasps, 1 startup exit 139) and before any
  evaluation-key execution. TRAIN outcomes motivated the change; no
  evaluation-key outcome was observed or used.

## Decision

Lexicographic opaque-ID rank is unrelated to task relevance; the measured
result is a candidate-window miss on 8 of 11 TRAIN keys. `PublicTrackCandidateV3`
replaces the ordering while keeping the list bounded, public, and deterministic.

### 1. Exact public fields allowed in candidate construction

Only the following, all from the fresh public observation:

- `PerceptionTrackV1.track_id` (opaque; final tie-break only)
- `PerceptionTrackV1.category` (public perceived class string)
- `PerceptionTrackV1.confidence`
- `PerceptionTrackV1.pose_xyzquat` (presence check only; values are not used
  for ordering)
- the TaskSpec-declared public target attribute class (the attribute words in
  the instruction/TaskSpec, e.g. a declared color/class term) — **attribute
  words only, never `task_target_track_id`** during recovery

Forbidden in candidate construction: entity/prim identity, evaluator role
truth, perfect pose, injected-failure truth, task-success truth, TaskSpec
target track identity, Teacher output, and any ordering by `pose_xyzquat`
values.

### 2. Role classes and deterministic ordering

Each fresh public track is assigned exactly one role:

1. `ROLE_TARGET_ATTRIBUTE_MATCH` — `category` contains the TaskSpec-declared
   target attribute class (case-insensitive substring on the declared class
   token; the exact matcher is frozen in code and covered by unit tests);
2. `ROLE_MANIPULABLE_OTHER` — valid `category` and present `pose_xyzquat`,
   no attribute match;
3. `ROLE_INADMISSIBLE` — missing `category` or missing `pose_xyzquat`;
   excluded from the candidate list entirely (fail closed; the model can
   never point at an inadmissible track).

Candidate list order: role group 1 before group 2; within a group,
`confidence` descending; exact confidence ties break by `track_id` ascending.
The result is truncated to **K = 8** slots; empty slots are masked invalid.

### 3. Fail-closed behavior

- An empty candidate list makes the pointer decision `INVALID` (→ B0
  fallback per ADR-0020 §7.4; excluded from strict-pure success).
- A pointer to a masked/absent slot, or a Qwen-path literal `track_id` not in
  the candidate list, is `INVALID` (unchanged from ADR-0020).
- No recapture is authorized: **exact recapture policy = none**. Strict-pure
  treatment is not modified.
- Before the first collection under this contract, a one-time public-pipeline
  audit must confirm on existing S3 evidence that `category` actually carries
  the declared attribute vocabulary; if it does not, collection remains
  blocked and this is reported as a new blocker, not worked around.

### 4. Revisions and compatibility

- Candidate schema revision: `PublicTrackCandidateV3`.
- Checkpoint architecture revision: **`M2C_Q012_V3`** (pointer head stays 9
  classes over slots 0–7 + `NONE`; slot *semantics* changed, so a new
  revision name is mandatory). Training/runtime prompts record the candidate
  contract revision.
- No trained `M2C_Q012_V2` checkpoint exists (zero training rows); the
  exact-load guard rule of ADR-0020 §4 applies unchanged to all revisions.
  Existing reports and evidence keep their original K=8 literal-ID semantics;
  no backfilling or reinterpretation.
- Leakage tests must prove candidate construction reads only the section-1
  fields.

### 5. Authorized collection

This ADR authorizes new TRAIN key manifests and PATH_BLOCKED training-data
collection under `PublicTrackCandidateV3`. V4 Q-A keys, SMOKE keys, and every
frozen S6 evaluation key remain excluded from training. B0, IK, collision,
controller, schema, stale-track, frame/unit, and safety gates are unchanged.
Teachers remain unused; Nano/BWM/Super states and kill rules are unchanged.

## Approval fields

- Selected option: **A**
- Exact K: **8** (unchanged bound)
- Exact public fields and ordering: section 1 and section 2 above
- Exact recapture policy: **none authorized**
- New schema/checkpoint revision name: **`PublicTrackCandidateV3` /
  `M2C_Q012_V3`**
- Does the approval authorize new TRAIN key manifests/data collection?: **yes**
  (TRAIN keys only; evaluation-key exclusions unchanged)
- Does the approval modify strict-pure treatment of recapture?: **no**
- Approver/date: project owner (gl46), 2026-08-13
