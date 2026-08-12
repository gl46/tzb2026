# M2C S4 public candidate contract — human ADR request

- Status: **REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR**
- Date: 2026-08-13 (Asia/Shanghai)
- Parent: `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md`
- Current frozen contract: fresh public `perception_tracks`, literal
  `track_id` ascending, first K=8
- Teacher use: false
- Training executed: false
- Model rollout / Q-B evaluation executed: false / false

## Why a human decision is required

The frozen TRAIN collection has now attempted 11/36 unique keys under the
unchanged ADR-0020 contract. Eight attempts reached the post-release public
observation but the task target was outside literal-ID K=8. Two attempts
admitted the task target into K=8 but the scripted final regrasp was rejected
by the unchanged contact/controller gate and ended with
`final_task_success=false`. One pre-registered attempt ended in an Isaac/RTX
stage startup exit 139 before probe execution. Zero episodes were packaged or
eligible for PATH_BLOCKED training.

The observed outcomes do not authorize changing K, sorting, candidate
filtering, recapture, or fallback behavior. Those fields are formal model
semantics fixed by ADR-0020, so Codex cannot change them without a new human
ADR/addendum.

## Mutually exclusive options

### A — public semantic-role pointer contract (recommended)

Authorize a versioned `PublicTrackCandidateV3` contract that first forms a
bounded public candidate list from declared public attributes needed by the
recovery task (for example, publicly perceived color/role class plus confidence
and freshness), then applies a deterministic tie-break. Keep all candidates
literal public track IDs and keep the final list bounded. Freeze:

- the exact public fields allowed in candidate construction;
- class/role ordering and tie-break ordering;
- K and mask behavior;
- how missing/ambiguous roles fail closed;
- training/runtime prompt and checkpoint metadata revision;
- compatibility behavior for V2 checkpoints;
- leakage tests proving no entity/prim/TaskSpec target identity is used.

Trade-off: this directly addresses the evidence that lexicographic opaque-ID
rank is unrelated to task relevance, but it changes model input semantics and
therefore requires new manifests/checkpoints and a separate pre-evaluation
contract smoke.

### B — increase K only

Keep literal-ID sorting and authorize a larger fixed K (with new pointer-head
shape, slot feature shape, checkpoint revision, and exact-load guards).

Trade-off: mechanically includes more visible tracks, but retains arbitrary
opaque-ID rank and increases model/context cost. The new K must be chosen and
pre-registered without looking at evaluation-key outcomes. Existing K=8
checkpoints and evidence cannot be silently reinterpreted.

### C — bounded public recapture

Keep K=8 and literal-ID ordering, but authorize a fixed number and timing of
fresh public recaptures before declaring the pointer invalid. Freeze the
recapture count, camera/robot action (if any), aggregation rule, and whether a
recapture consumes a model decision cycle.

Trade-off: may mitigate tracker instability without enlarging the head, but
changes decision frequency and can introduce a fixed continuation. The ADR
must explicitly say whether recapture is model-owned and how strict pure
success treats it.

### D — no contract change; stop PATH_BLOCKED S4 (D2-style downgrade)

Do not authorize a new candidate contract. Freeze the finding that the
current public input/physical acceptance path yielded zero eligible training
episodes, keep formal Q-B evaluation blocked, and retain
`GO_QRM_COARSE_ONLY`. Continue only audit/report work or statistically safer
M2B-domain expansion.

Trade-off: no new architectural risk; the bounded M2C Q-B hypothesis remains
unmeasured rather than disproved by a trained model.

## Non-negotiable boundaries for any approval

- V4 Q-A, SMOKE, and S6 keys remain excluded from training.
- Public input may not use entity/prim identity, perfect pose, injected truth,
  task-success truth, or TaskSpec-filled target identity during recovery.
- No Teacher label or Teacher runtime component is permitted.
- B0, IK, collision, controller, schema, stale-track, frame/unit, and safety
  gates remain unchanged.
- Old reports and checkpoints keep their original K=8/V2 semantics; no
  backfilling or reinterpretation.
- A new option must be committed before collecting or evaluating under the
  changed contract.

## Human approval fields

- Selected option: `A | B | C | D`
- Exact K (if applicable):
- Exact public fields and ordering (if applicable):
- Exact recapture policy (if applicable):
- New schema/checkpoint revision name:
- Does the approval authorize new TRAIN key manifests/data collection?:
- Does the approval modify strict-pure treatment of recapture?:
- Approver/date:

Until these fields are completed in an accepted human ADR, Codex must not
change K/candidate semantics or start training/formal Q-B evaluation.

## Task report

- Changed file: this human decision request.
- Tests: evidence classifications are being frozen by
  `scripts/m2c/audit_path_blocked_train_collection.py` and its unit tests.
- Failures: 8 K8 rejections, 2 regrasp contact/controller rejections, 1 Isaac
  stage startup exit 139 across 11 unique TRAIN keys.
- Blockers: zero eligible PATH_BLOCKED samples; candidate contract change is
  not authorized.
- Next command: human selects and fully specifies one option, or selects D to
  freeze the downgrade finding.
