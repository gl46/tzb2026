# M2C S6 matched-evaluation pre-registration

Status: **PRE-REGISTERED BEFORE ANY M2C S6 EXECUTION OR RESULT**  
Written: 2026-08-12 (Asia/Shanghai)

At the time this document was written, no M2C S6 matched episode had been
executed and no M2C S6 outcome had been observed. The M2B 20-key result and the
M2C S2/S3 evidence were already known. They are design inputs, not S6 results.

This pre-registration does not authorize Q-B training or evaluation and does
not approve a new skill, target pointer, destination cell, action mapping, or
model architecture. Q-B remains blocked on the separate human expressivity
ADR required by `M2C-QB-EXPRESSIVITY-PREREG.md`.

## Frozen comparison

Every matched key must contain exactly one episode from each method:

1. `B0` — unchanged frozen B0;
2. `QRM_COARSE_NO_FC`;
3. `QRM_COARSE_FC`;
4. `QRM_COARSE_FC_MLP`.

All four records for a key must share the same scene seed, physical failure,
source hashes, retry contract, action registry, and safety/IK/collision gates.
A missing method, duplicated episode or decision, cross-key source mismatch,
or reused execution receipt makes the evaluation non-formal. A mapping
rejection or failed execution remains in the denominator; it is not silently
excluded.

## Frozen gates and estimands

- At least 30 complete matched keys.
- At least 50 physically executed model decisions across the three model
  methods. Model proposals, rejected mappings, and B0 fallbacks do not count.
- Zero collision or safety violations.
- Teacher use and privileged simulator truth as policy input are forbidden.
- The primary estimand is the paired final-task-success difference
  `QRM_COARSE_FC - B0`, reported as `fc_gain_over_b0`.
- Its uncertainty is a two-sided 95% paired nonparametric bootstrap percentile
  interval over matched keys, using 20,000 resamples and PRNG seed `20260812`.
- Secondary estimands are `QRM_COARSE_FC - QRM_COARSE_NO_FC` and
  `QRM_COARSE_FC_MLP - B0`, using the same frozen paired bootstrap procedure.
- All point estimates and intervals are reported even when zero or adverse.

`pure_model_success_episodes` is computed episode by episode with the strict
predicate in `closed_loop_metrics.py`. Every successful episode excluded from
that count must retain its exclusion reasons. The broad
`successful_episodes_with_any_model_decision` remains descriptive only, and
the assertion `pure <= any_model` remains mandatory.

## Disposition

The offline summarizer may be implemented and tested before S6. Real S6
execution remains downstream of the recorded S4/S5 disposition and may not be
used to bypass the human Q-B ADR. No threshold, retry, safety gate, or B0
source may be changed after results are observed.
