# ADR-0020: CoarseIntentV2 model-owned recovery chain (M2C Q-B authorization)

- Status: Accepted for the bounded M2C Q-B experiment (human decision)
- Date: 2026-08-12
- Human direction: project owner approved option (a) of
  `docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md` in the coordination session
  of 2026-08-12; this ADR is the separate human authorization that document
  requires. Q-B remained blocked until this ADR was committed.
- Parent evidence:
  - Q-A PASS: `reports/m2c-s2-exploration-v4.json` (V4 domain SHA-256
    `a08d0dee…`, manifest `4e78c044…`; B0 0/3 on pre-registered keys with
    unchanged probe `1e32fa89…`; strict existence proof completed on seed
    9077 with 0 collision violations).
  - S3 PASS: `artifacts/m2c/dataset-v3.jsonl` SHA-256 `48924a20…` (312/0,
    full class coverage), `artifacts/m2c/path-blocked-raw-v1.jsonl` SHA-256
    `704cc579…` (raw evaluator evidence, no training label yet).
  - Expressivity audit: `docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md`.

## Context

The pre-registered Q-B chain (grasp public blocker → transport to a
registered bin cell → release → reobserve → reassociate → regrasp task
target) is composed entirely of skills that already exist in
`RuntimeSkillRegistryV1` (`GRASP`, `LIFT`, `MOVE`, `PLACE`, `RELEASE`,
`REOBSERVE`, `REASSOCIATE_TARGET`, `REGRASP`). The audit found exactly two
missing pieces, both fields rather than capabilities:

1. `decode_coarse_intent()` never predicts a track pointer, so
   `target_track_id` is always `None` and the runtime adapter falls back to
   the TaskSpec task target; the model cannot select a resting blocker.
2. `CoarseIntentV1` has no destination field and no official bin-cell enum
   is registered, so the model cannot select where to place the blocker.

## Decision — option (a): versioned intent, no new skill labels

### 1. `CoarseIntentV2`

`CoarseIntentV2` extends `CoarseIntentV1` with exactly one new field and one
decoding obligation:

- New field `destination_cell: BIN_CELL_0 | BIN_CELL_1 | BIN_CELL_2 |
  BIN_CELL_3 | BIN_CELL_4 | BIN_CELL_5 | None` (default `None`).
- `target_track_id` (existing field) must now be fillable from a model
  prediction, not only from TaskSpec.

All other `CoarseIntentV1` fields, semantics, and defaults are unchanged.
No new skill label is created. `SAFE_PLACE_NON_TARGET` keeps its existing
precondition (non-target already carried) and is not an alias for blocker
clearing.

### 2. Public track pointer

- Candidate list: the fresh observation's `perception_tracks`, sorted
  lexicographically by `track_id`, truncated to the first **K = 8** slots;
  slots beyond the available tracks are masked invalid.
- Structured Q0/Q1/Q2: a new track-pointer head over **9 classes**
  (slots 0–7 plus `NONE`). `NONE` preserves the legacy TaskSpec-fallback
  path for non-recovery phases.
- Qwen coarse path: the decoded text must name a literal `track_id` present
  in the fresh candidate list; anything else is `INVALID`.
- Decode determinism at evaluation: argmax with temperature 0; ties resolve
  to the lower slot index. Re-prompt policy is unchanged from the M2B
  evaluation protocol.
- The stale-track gate applies unchanged: a pointer to a track absent from
  the latest observation is `INVALID`.

### 3. Registered destination-cell contract

- `RuntimeSkillRegistryV2` registers
  `parameter_enums.destination = [BIN_CELL_0 … BIN_CELL_5]` on `MOVE`,
  `PLACE`, and `SAFE_PLACE_NON_TARGET` (currently optional free-form).
- `BIN_CELL_i` resolves to world-frame metres exclusively through
  `bin_cell_targets()[i]` of the frozen scene generator
  (`scripts/generate_industrial_scenes.py`, SHA-256 `e9f9e201…`), i.e. the
  same six partition-cell drop targets the scene contract already publishes.
  The model never emits continuous coordinates.
- Structured Q0/Q1/Q2: a destination head over **7 classes** (6 cells plus
  `NONE`).

### 4. Frame, units, dimensions, frequency, normalization

- Coordinate frames and units per registry entry are unchanged: `world`,
  `m_rad` for the chain skills; destination resolution is world-frame metres
  from the registered enum.
- Decision frequency: exactly one executed `CoarseIntentV2` per decision
  cycle; a fresh public RGB-D observation is mandatory before the next
  selection (per the pre-registration).
- New heads are softmax-normalized; slot features must be presented to the
  model in the same canonical slot order used by the pointer head, built
  from public track fields only.
- Architecture revision name: **`M2C_Q012_V2`**. Exact tensor shapes are
  recorded in checkpoint metadata. `M2B_Q012_V1` and `M2A_BETA1_LEGACY_V1`
  (110/70) checkpoints load only through their exact recorded layouts;
  tensors may not be silently padded, truncated, or reinterpreted
  (ADR-0019 addendum applies unchanged).

### 5. Training data authorization

- Q-B training labels may be built from `dataset-v3.jsonl` and from
  `path-blocked-raw-v1.jsonl` converted into supervised chain labels
  (skill sequence, blocker slot, destination cell).
- Model inputs remain public-only (RGB-D tracks, robot state, TaskSpec,
  FailureContext). Entity/prim identity, perfect poses, contacts, injected
  failure truth, and task-success truth stay training/evaluation-only.
  `PATH_BLOCKED` already exists in `FailureType`; no vocabulary change.
- Split discipline: scene/failure-seed grouped splits; the V4 Q-A matched
  keys and every frozen S6 evaluation key are excluded from training.

### 6. Attribution and gates (unchanged)

- The strict `pure_model_success_episode()` predicate frozen at `80a1910`
  is unchanged. A TaskSpec-fallback-filled `target_track_id` during
  RECOVERY, any `INVALID` mapping, any B0 fallback or fixed continuation
  disqualifies the episode from pure-model success. The runtime journal must
  record per-parameter provenance (`MODEL` vs `TASK_SPEC_FALLBACK`).
- Schema, stale-track, frame/unit, IK, collision, controller, and safety
  gates run before execution, unchanged. B0 sources, parameters, retries,
  and success definitions are untouched (probe `1e32fa89…`).

### 7. Required tests before any Q-B evaluation execution

1. The model — not TaskSpec fallback — selects the blocker track
   (provenance asserted per decision).
2. `destination_cell` resolves only through the registered enum contract;
   free-form destinations are rejected.
3. Every chain step is model-owned and physically executed; a fresh public
   observation gates each next decision.
4. Invalid pointer / stale track / invalid cell → `INVALID` mapping → B0
   fallback → excluded from pure-model success.
5. Checkpoint revision guards: `M2C_Q012_V2` loads exactly; older revisions
   load only through their recorded layouts; mismatches fail loudly.
6. Registry/schema round-trip validation for `CoarseIntentV2` and
   `RuntimeSkillRegistryV2`.

## Governance scope

This ADR authorizes only the bounded M2C Q-B experiment. It does not retire
or replace the mandatory world-model mainline, does not modify B0 or any
pre-execution gate, creates no new skill label, and keeps Flow disabled.
Teachers remain unused: Nano `CANDIDATE`, BWM `CANDIDATE_LICENSE_PENDING`,
Super `PARKED`; any Teacher entering data labels or the runtime control
stack kills the affected run. Weakening B0, relaxing a gate, or feeding
privileged simulator truth into policy input terminates the experiment and
must be reported.
