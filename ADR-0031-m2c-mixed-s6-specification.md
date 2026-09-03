# ADR-0031: Mixed render-layout S6 — key redraw, corpus, and sequencing

- Status: Accepted (human decision)
- Date: 2026-08-19 (Asia/Shanghai)
- Approver: project owner (gl46)
- Parents: ADR-0028 (ITT protocol, three arms), ADR-0030 (Option B),
  NOTE-0012 (diversity audit: scripted family = 1 layout family; render
  path 598/600 distinct; S3 74/74, M2B 150/150 distinct, zero overlap with
  the scripted family)

## 1. S6 key redraw (outcome-blind, before any S6 consumption)

- Population: **native render-path scenes of the unchanged frozen
  generator** (`render()` placements; the scripted V4 family overwrite is
  not applied to S6 scenes). No generator byte changes.
- Composition: **30 keys = 10 × EMPTY_GRASP + 10 × WRONG_OBJECT +
  10 × RELEASE_FAILURE**, failure injection via the existing frozen S3
  collection protocol. PATH_BLOCKED is excluded from S6; all
  scripted-family results (smoke ch21–25 and any future family runs) are
  reported separately under the ADR-0030 §1 framing.
- Diversity and disjointness, verified by canonical placement hash before
  the manifest is frozen: ≥ 25 distinct layout classes among 30 keys, no
  class > 2 keys; layout-class disjoint from the scripted 3-class family,
  from every S3 dataset-v3 training layout, from every locally determinable
  M2B V2 training layout, and from every consumed key of any kind. Fresh
  seeds outside previously used collection ranges; fixed order; stop count
  30; no retry/replacement; selection rule committed before any outcome.
- Arms and protocol unchanged: B0 / QRM_COARSE_NO_FC / QRM_COARSE_FC,
  30 × 3 = 90 one-shot runs under the ADR-0028 §1 ITT contract.

## 2. Merged retraining (proceeds under ADR-0028 §4; deferral lifted)

The ADR-0030 §4 deferral is resolved by the audit now on file. The merged
two-arm retraining proceeds with corpus = M2B Dataset V2 + S3 dataset-v3 +
the 273 PATH_BLOCKED decision rows. The training report must disclose:
per-class row/episode counts; per-class layout diversity (M2B 150 classes /
S3 74 classes / PATH_BLOCKED 1 family — stated plainly); the NOTE-0010
position-permutation check with single-feature separability AUC; and new
bundle digests with the existing checkpoint-revision discipline. Job
scheduling on the training host remains the mainline session's and its
operator's call.

## 3. Precondition ① smoke under the mixed design

Post-retraining smoke challenges draw fresh render-path keys,
layout-disjoint from the S6 key set and from all training layouts, one-shot
each, batched per ADR-0029 §2. ADR-0028 §2.1 (first model-arm physical
receipt before S6) and the 2026-08-24 review date stand. The formal
production-scene binding must be re-derived for render-path scenes through
the existing versioning discipline; this is implementation, not a new human
gate, unless an ADR-0024 §4 category is touched.

## 4. Reporting and claims

- `fc_gain_over_b0` and `pure_model_success_episodes` are reported with
  paired matched-key statistics whatever their direction. If B0 saturates
  on the diverse classic-class keys, that is reported as the finding it is;
  parity on 25+ distinct layouts is a robustness result, not a failure to
  be massaged.
- Generalization claims are bounded to the render-layout population of the
  frozen generator; PATH_BLOCKED claims are bounded to its single layout
  family with explicit disclosure. Option A (V5 diversified blocked family)
  is recorded as post-competition outlook.

## 5. Calendar and boundaries

Keys frozen by 2026-08-21; retraining and precondition-① smoke by
2026-08-24 (ADR-0028 review date); S6 resolution by 2026-08-30; hard freeze
2026-09-01. No gate, threshold, B0 byte, public predicate, generator byte,
privileged-truth, or Teacher change. Consumed evidence stands.
