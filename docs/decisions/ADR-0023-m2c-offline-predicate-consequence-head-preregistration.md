# ADR-0023: Offline public-predicate consequence head preregistration

- Status: **Proposed — human approval required**
- Date: 2026-08-13 (Asia/Shanghai)
- Authorization: documentation only; this proposal does **not** authorize
  implementation, data generation, training, evaluation, deployment, or any
  S4-S6 runtime change.
- Timing disclosure: written after the M2C TRAIN observations disclosed in
  ADR-0021 and after ADR-0022 was accepted, but before this proposed head,
  dataset, checkpoint, or offline evaluation exists. It is not a claim of
  preregistration before earlier M2C results.

## Question and bounded hypothesis

Can a small world-model head predict the public predicate consequences of an
actually executed candidate skill from only the public pre-action observation,
the candidate skill, and `FailureContextV1`?

The proposed artifact is
`M2COfflinePublicPredicateConsequenceHeadV1`. It is an offline diagnostic of
world-model expressivity, not a policy component. A positive result may support
a later, separately approved proposal; it does not unlock or alter S4, S5, or
S6.

## Frozen information boundary

### Inputs allowed

Each example has exactly three input groups:

1. `public_observation_features_before`: deterministic features of the fresh
   public RGB-D observation and public robot proprioception. Public tracks may
   contribute category, confidence, public pose, and opaque track linkage.
   Opaque IDs may only link the selected candidate to the same observation;
   they may not be embedded as ordered or semantic numeric features.
2. `candidate_skill`: the registered skill type and its public, discrete
   arguments, including a selected public candidate slot/track and destination
   cell when the registered skill requires them. It contains no execution
   result, post-action state, gate result, exact-plan result, or evaluator
   label.
3. `failure_context`: a canonical `FailureContextV1` projection whose contents
   are derived only from public observations and prior public execution
   history.

Instruction text, TaskSpec truth, `observation_after`, success labels, and any
field outside these three groups are excluded. A feature manifest must list
every tensor name, dtype, shape, units, frame, normalization, and source field;
unlisted features fail closed.

### Supervision allowed

The only target is the canonical public-predicate receipt attached to the first
time-valid `observation_after` produced after the candidate skill was actually
executed. The dataset builder consumes that receipt; it may not reconstruct or
correct labels from simulator supervision.

- A predicate is labelled `TRUE` or `FALSE` only when the public receipt says
  so explicitly. Absence is `UNOBSERVED`, never an implicit negative.
- Every target binds the post-action public capture and frozen public-predicate
  extractor hashes. Receipts may use public RGB-D and documented public robot
  proprioception, but never entity/prim identity, perfect pose, contact truth,
  injected-failure truth, or final task-success truth.
- A candidate that was not executed has no factual consequence label and may
  not become a counterfactual example. Synthetic, imputed, relabelled, or
  Teacher-produced consequences are forbidden.
- An executed candidate without a valid post-action public receipt remains in
  the source-accounting manifest as `MISSING_LABEL_RECEIPT`; it is not silently
  converted to failure or dropped from accounting.

Teacher soft labels are prohibited. Nano remains `CANDIDATE`, BWM remains
`CANDIDATE_LICENSE_PENDING`, and Super remains `PARKED`; no Teacher adapter,
`TeacherResponse`, logit, explanation, pseudo-label, or distilled output may
enter inputs, labels, training, evaluation, or the resulting artifact.

## Offline-only containment

This head and all of its predictions are barred from S4-S6 closed-loop
decision making. They may not:

- propose, rank, select, veto, retry, or replace a skill;
- alter `CoarseIntentV2`, `PublicTrackCandidateV3`, runtime mapping, an
  `ExactExecutionPlanV2`, B0 fallback, or pure-model attribution;
- feed a schema, IK, collision, stale-state, controller, safety, or success
  gate; or
- enter a controller, actuator request, policy prompt, FailureContext, or
  runtime history.

The offline report must state `closed_loop_consumers=[]`. S4-S6 entry points
must not import the head or load its checkpoint. Its scores are not S4-S6
evidence and cannot repair, replace, or reinterpret an episode. Any future
online use is a formal model change and requires a new human ADR plus new
preregistration before observing online outcomes.

## Data isolation and split contract

1. Only explicitly designated TRAIN-source episodes may be used. ADR-0021 V4
   Q-A keys, S4 SMOKE keys, all frozen S6 evaluation keys, and their sibling
   scenes/captures are excluded from fitting and model selection.
2. Split assignment is by an immutable lineage group containing scene seed,
   physical episode lineage, pre-action capture, and all candidate/action
   siblings. No group, adjacent-frame derivative, duplicate, or augmentation
   may cross train/validation/test boundaries.
3. The source inventory, deduplication report, exact group lists, predicate
   vocabulary, and train/validation/test manifests are content-addressed and
   frozen before fitting. Test labels remain unread by training, feature
   selection, threshold selection, and early stopping.
4. The training seed is `20260813`. The final test is run once for one frozen
   checkpoint hash. A changed feature set, split, vocabulary, threshold, or
   checkpoint after test disclosure is a new experiment requiring a new
   prospective preregistration; it may not overwrite this result.
5. Source-accounting reports the number of executed candidates, valid receipts,
   `MISSING_LABEL_RECEIPT` rows, exclusions, and reasons. If missing receipts
   exceed 5% of otherwise eligible executed candidates, the experiment is
   `NO_GO_DATA_INTEGRITY`.

## Metrics and decision rule

The frozen comparison is against
`CandidateSkillFailureContextPriorV1`, fitted on TRAIN only and given candidate
skill plus FailureContext but no public observation features. It is not a
Teacher.

- Primary: macro mean `delta_brier = Brier(prior) - Brier(head)` over explicit
  `TRUE`/`FALSE` labels. Each predicate is weighted equally; `UNOBSERVED` is
  masked and its coverage is reported.
- Uncertainty: 20,000 lineage-group bootstrap resamples, seed `20260813`,
  percentile 95% confidence interval.
- Eligibility: at least 30 independent test lineage groups and at least three
  predicates having at least 10 `TRUE` and 10 `FALSE` test labels each.
- Positive offline result: primary point estimate at least `0.02`, lower 95%
  confidence bound strictly above zero, and macro expected calibration error
  at most `0.10` using ten equal-width bins fixed before test.
- Secondary, never gate-substituting: per-predicate support/coverage, Brier,
  AUROC, validation-frozen-threshold F1, macro F1, calibration error, and the
  same metrics stratified by skill type and FailureContext failure type.

If eligibility is not met, the result is `INSUFFICIENT_OFFLINE_EVIDENCE`, not a
pass. If the positive rule is not met, the head is killed and reported as a
negative offline result; thresholds, predicates, or splits may not be relaxed
to rescue it. No result, including a pass, authorizes closed-loop use.

## Schemas and hash binding

A future implementation must introduce strict, extra-forbid schemas:

- `M2COfflinePredicateConsequenceDatasetManifestV1`: source inventory and
  hashes, exact split groups, exclusions, vocabulary, feature contract, label
  extractor, parent ADR hashes, and Teacher/truth audit;
- `M2COfflinePredicateConsequenceSampleV1`: sample/lineage IDs, split, three
  input payload hashes, executed-skill receipt hash, post-action public capture
  hash, public-predicate receipt hash, and tri-state labels;
- `M2COfflinePredicateConsequencePredictionV1`: sample/checkpoint hashes and
  per-predicate `p_true`, `p_false`, and `p_unobserved` summing to one; and
- `M2COfflinePredicateConsequenceReportV1`: dataset, checkpoint, code, metric,
  bootstrap, containment-audit, and kill-rule results.

JSON hashes use UTF-8 canonical JSON with sorted keys, separators `(',', ':')`,
no NaN/Infinity, and lowercase 64-hex SHA-256. Tensor/checkpoint formats and
byte-level hashing must be named before training. Hashes are computed from one
read of immutable bytes; paths alone are never evidence. The document's own
hash is recorded externally after acceptance and cannot be self-embedded.

Reference bytes reviewed while writing this proposal:

- ADR-0021 SHA-256:
  `60161eb2b40cdf7e32cd5714ef420b7bfb74d28a4a6b5789eecdd9cc73cba7cf`
- ADR-0022 SHA-256:
  `4538eb980b66dc0945d1f016325f6c3c5679c87b97b9986e25253e67a2cc3ef1`
- `contracts.py` SHA-256:
  `2f05ab4e04af084ec36a56f43d79a69f07ebbfa299402dc47bf822b1052d3d91`
- `public_failure_predicates.py` SHA-256:
  `22eed691ae8d5fdfebeef54929d3d1252240e884e207f67d741cb1c93d7de8db`

All implementation bindings are currently **UNBOUND**. These reference hashes
document what was reviewed; they do not authorize code and must be rechecked by
the future accepted binding record.

## Kill rules and approval boundary

Kill the affected run and invalidate its checkpoint/report if any Teacher soft
label or component appears; privileged truth reaches an input or target; a
split lineage crosses boundaries; test labels influence development; an
unexecuted candidate receives a factual label; a hash/schema check fails; or
the head/checkpoint/prediction is imported, loaded, or consumed by S4-S6.
Every report lists all kill-rule events explicitly, including `none`.

Human approval of this proposal is required before any implementation. Because
formal model changes require a human ADR, implementation also requires an
accepted binding addendum pinning the exact vocabulary, feature/schema files,
code and test hashes, dataset/split manifests, checkpoint format, and offline
entry point. Any online or closed-loop proposal requires a separate human ADR;
this document cannot be interpreted as advance approval.

## Human decision fields

- Approve this offline experiment: **PENDING**
- Approve exact inputs/label boundary: **PENDING**
- Approve data split and metrics/kill rule: **PENDING**
- Approve any S4-S6 or online use: **NO — outside this proposal**
- Approver/date: **UNSET**
