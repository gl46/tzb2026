# ADR-0028: S6 intention-to-treat protocol approved, three arms, launch preconditions

- Status: Accepted (human decision)
- Date: 2026-08-18 (Asia/Shanghai)
- Approver: project owner (gl46)
- Scope: decides `M2C-S6-TERMINALIZED-DENOMINATOR-ADR-REQUEST.md`; sets S6
  launch preconditions; directs two pre-S6 verifications.

## 1. Intention-to-treat protocol — approved with one amendment

Clauses 1–5 of the request are approved verbatim: frozen keys × arms planned
before any result; one-shot non-replaceable challenges; exactly one signed
`COMPLETE | TERMINAL_FAILURE` terminal envelope per consumed run; every
mapping/preflight/execution failure stays in its arm's denominator;
unconsumed records are missing evidence, never zero; safety-unknown failures
count as failures and block the zero-safety-violation gate until resolved.
The versioned evidence contract and withhold-until-all-resolved summarizer
are approved as specified.

**Amendment — three arms, not four**: the arms are `B0`,
`QRM_COARSE_NO_FC`, `QRM_COARSE_FC`; the plan is **30 keys × 3 arms = 90
runs**. `QRM_COARSE_FC_MLP` is dropped by explicit human decision, recorded
as `NOT_RUN_BY_DECISION`, consistent with the standing `COARSE_ONLY`
residual verdict; no S5 residual ADR will be sought before the freeze. This
is a human protocol decision, not a silent replacement.

## 2. Launch preconditions (both required)

S6 challenge consumption may begin only when:

1. **One model-arm physical receipt exists**: at least one preregistered
   SMOKE challenge has carried a model-selected decision through scene
   binding, plan synthesis, A3 preflight, and a real physical receipt.
   Burning the 90-run plan against the currently measured 0% execution rate
   is not authorized. If this precondition is still unmet on
   **2026-08-24**, the choice between launching anyway (measuring an honest
   zero) and reporting `BLOCKED_UNMEASURED` returns to the human with the
   then-current evidence.
2. **Training-composition report is on file** (§4 below).

## 3. Scene-binding miss root cause (directive)

The consumed challenges show selected-track public centroids missing the
frozen 20 mm scene-binding gate (e.g. 26.991 mm on challenge 24) and one
ambiguous binding. Before any perception-side change is proposed, commit a
short root-cause report: per consumed challenge, the selected object's pose
class (upright/lying), the centroid offset vector, and whether the offset is
consistent with the previously recorded systematic estimator biases
(radius-correction ~0.3r centroid push; lying-cylinder half-length Z
offset). The 20 mm gate itself is not to be changed. If the cause is a
public-estimator bias, the fix is a versioned public-geometry revision and
requires a separate human sign-off before deployment; this ADR does not
authorize it.

## 4. Training-composition verification (directive)

Report from the frozen bytes: the class composition of the 273-row ADR-0026
training dataset behind the deployed FC/NoFC bundles (`6e7cb272…` /
`1b6757dc…`). If it contains only PATH_BLOCKED decision chains, state
whether the deployed models have ever seen a supervised
"direct-grasp-the-declared-target" or non-PATH_BLOCKED recovery row. If
they have not, one two-arm retraining on the merged decision-level dataset
(M2B Dataset V2 + S3 dataset-v3 + PATH_BLOCKED rows, same schedule, new
bundle digests, preregistered before S6 key consumption) is authorized; the
existing bundles and their evidence remain frozen as recorded.

## Boundaries

No B0 byte, safety/IK/collision/controller/schema gate, the 20 mm binding
gate, public predicate, privileged-truth boundary, or Teacher rule changes.
Consumed challenges are never reused; recorded negatives stand. Deadline
routing stays `BLOCKED_UNMEASURED` for missing evidence. The 9/1 hard
freeze stands: if S6 cannot resolve all 90 runs by 2026-08-30, the
summarizer's partial-disclosure rule applies (report resolved/unresolved
counts separately; publish no headline metric from an unresolved plan).
