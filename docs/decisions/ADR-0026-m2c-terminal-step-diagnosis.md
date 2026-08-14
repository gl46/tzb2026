# ADR-0026: Halt collection; terminal-regrasp diagnosis with preregistered decision tree

- Status: Accepted (human decision)
- Date: 2026-08-15 (Asia/Shanghai)
- Approver: project owner (gl46)
- Parent: ADR-0025 §3 yield audit
  (`reports/m2c-s4-training-eligibility-yield-adr0025.md`:
  62 identities, 49 complete chains, 0 eligible; terminal failures
  31 contact / 17 pregrasp-IK / 1 predicate)

## 1. Immediate halt

All PATH_BLOCKED TRAIN collection batches stop now, including the already
preregistered Batch 24/25 and the training-extension manifest. Collecting at
a measured 0/49 conditional yield after the §3 audit's own "no finite
collection size" finding is unjustifiable spend. Preregistered-but-unrun
batches are recorded as cancelled by this directive, not as failures.

## 2. Diagnostic ablation (authorized, preregister before outcomes)

A scripted, outcome-blind probe campaign on **fresh diagnostic seeds**
(identity-disjoint from every TRAIN/SMOKE/Q-A/S6/matched key), measuring the
terminal regrasp step only, under three pre-registered conditions at the
same anchor geometry:

- C1 — no blocker (target alone at its anchor);
- C2 — retained (green-position) blocker only;
- C3 — full V4 layout (both blockers, red one scripted-cleared first, i.e.
  the current chain).

At least 12 seeds per condition, fixed order, no retry/replacement. Record
per-attempt: pregrasp IK result, contact-gate result, selected free-gap yaw,
target-blocker surface gap, and public predicates. No gate, threshold, B0,
or predicate change is authorized; this measures, it does not tune.

## 3. Preregistered decision tree (committed before ablation outcomes)

- **R1 — C1 succeeds ≥ 75% and C3 ≤ 25%**: the domain's terminal geometry is
  the cause. Then: (a) TRAIN-domain geometry may be relaxed (larger
  target–blocker spacing) for training keys only, disclosed as a
  train/eval distribution difference; (b) the Q-A criterion gains a
  feasibility floor for any future domain: the scripted existence proof
  must succeed on ≥ 30% of pre-registered proof seeds, not merely once.
  V4's Q-A PASS stands as recorded, with an honest addendum that its
  existence proof is now measured at tail-event rate; whether to pursue a
  V5 evaluation domain or route to D1 is a subsequent human decision
  informed by the remaining calendar.
- **R2 — C1 also fails ≥ 50%**: the approach/contact-acceptance execution
  primitive is the cause, independent of blockers. Then: a versioned fix to
  the scripted chain and exact-plan synthesis terminal approach is
  authorized (bounded enumeration over the admissible free-gap yaw set and
  approach-cone variation, selected deterministically pre-execution,
  zero mid-execution retries preserved), followed by a small re-validation
  batch (≤ 12 keys) before any large collection.
- **R3 — mixed outcome**: both fixes above may proceed in the R1/R2 forms;
  any other response escalates.

## 4. Eligibility amendment (decided now, applies once data exists)

ADR-0020 §5 training-label eligibility is amended: complete chains whose
steps 0–6 passed every gate are admissible as **decision-level supervision**
for those steps even when the terminal step failed, provided (a) each row is
labelled with its episode's terminal outcome, (b) terminal-step rows are
taken only from episodes whose terminal step physically succeeded, and
(c) the dataset card reports the failed/successful episode mix. Rationale:
the model under test selects skills; the 49 chains' decision sequences are
correct by the frozen gates, and execution-level terminal failure does not
falsify the decision labels. Evaluation (Q-B) success definitions are
untouched: final task success still requires the full physical chain.

## 5. Boundaries

No B0 byte, safety/IK/collision/controller/schema gate, public predicate,
privileged-truth boundary, or Teacher rule changes. Existing evidence keeps
its meaning; scene outcomes are not reinterpreted. Deadline routing stays
`BLOCKED_UNMEASURED` where evidence is missing. The 2026-08-20 bundle-smoke
checkpoint and ADR-0024 §5 scope-reduction rule stand.
