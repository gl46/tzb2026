# ADR-0030: Layout-degeneracy framing, S6 diversity precondition, §1 non-trigger

- Status: Accepted (human decision)
- Date: 2026-08-19 (Asia/Shanghai)
- Approver: project owner (gl46)
- Endgame decision: **Option B — mixed render-layout S6** (recorded 2026-08-19;
  specification in `ADR-0031-m2c-mixed-s6-specification.md`); Option A
  (V5 diversified blocked family) deferred to post-competition outlook;
  Option C remains the fallback if B is blocked
- Trigger: the ch21–25 cross-challenge analysis showing all five consumed
  smoke challenges executed against one repeated physical layout
  (shared SDF `2bd5a27d…`; per-object offsets identical across challenges to
  ≤ 0.05 mm; declared-target residual 17.950 mm in all five; 11/11 production
  scenes in [25000, 26000) share the layout).

## 1. Corrected factual framing (binding for all evidence and materials)

Challenges 21–25 are five one-shot formal challenges executed against **one
repeated physical layout** with differing failure seeds. Procedural
independence (one-shot nonces, no retry, per-challenge evidence) holds as
recorded; environmental independence does not. Terminal audits, status
reports, and every submission material must state this framing; the phrase
"five independent challenges" (or equivalent) is prohibited. No consumed
evidence is reinterpreted; per-challenge conclusions that depend only on
procedure stand, and any conclusion phrased as cross-scene confirmation is
downgraded to single-layout observation.

## 2. ADR-0028 §2 precondition ③ — layout diversity of evaluation AND training

Before any S6 challenge is consumed, a layout-diversity audit must be on
file covering all of:

1. **S6 key set**: each key's physical layout class computed
   deterministically from the frozen generator at that key's scene seed
   (canonical placement hash), with the degeneracy mechanism explained.
2. **Generator capacity**: how many distinct layout classes the frozen
   generator can produce across a wide seed sweep, both unconstrained and
   under the actual key-selection filters (exactly-six-objects, V4 offline
   geometry gates). This distinguishes a sampling problem (redraw can fix)
   from a filter/generator problem (redraw cannot).
3. **Training corpora**: layout-class distributions of the V4 PATH_BLOCKED
   training episodes (known: 5 classes, one of them ≈31% and coincident
   with the challenge scene), S3 dataset-v3, and — where locally
   determinable — M2B Dataset V2.

Eligibility for S6: the key set spans ≥ 10 distinct layout classes, no
single class contributes > 4 of the 30 keys, and **no key shares the
`2bd5a27d…` layout** (its gate-relevant residuals are now known from smoke,
so keys on it are no longer outcome-blind). If ineligible **and** the
capacity analysis shows diverse layouts are obtainable, the S6 key manifest
must be redrawn before any S6 consumption: outcome-blind, from a seed range
chosen for layout diversity under the unchanged frozen generator, with a
preregistered layout-class disjointness constraint, identity-disjoint from
every consumed TRAIN/SMOKE/Q-A key and from the `2bd5a27d…` layout class,
committed with its selection rule before any outcome is observed. Redrawing
after the first S6 consumption is prohibited. If the capacity analysis
shows the generator/filters cannot produce diverse layouts, S6 in its
current form is not run; the honest options (bounded single-layout
evaluation with explicit disclosure, generator-versioning as a new human
decision, or D-route closure) return to the human with the audit.

## 3. ADR-0029 §1 explicitly not triggered

The apparent cross-challenge consistency of perception offsets is one layout
measured five times, not a systematic term confirmed across layouts; the
lying-cylinder hypothesis was never exercised (all six cylinders upright).
Perception-side changes remain unauthorized. The §1 pre-authorization can be
invoked only by a future §3-style analysis spanning ≥ 3 distinct layout
classes.

## 4. Sequencing — diversity resolution BEFORE retraining

The merged retraining authorized by ADR-0028 §4 is **deferred until the §2
audit is on file**: retraining before scene diversity is resolved would
produce a bundle evaluable only on the same repeated layout (the V4
PATH_BLOCKED corpus is 5 near-identical classes, one coincident with the
evaluation scene), spending GPU without supporting any claim. When
retraining does run, its corpus composition and per-class layout diversity
are disclosed in the report, together with the NOTE-0010
position-permutation check. Scheduling of the retraining job on the
training host is the mainline session's and its operator's call; no peer
suggestion constitutes authorization to start it.

## 5. Boundaries

No gate, threshold, B0 byte, public predicate, generator byte,
privileged-truth boundary, or Teacher rule changes. Consumed nonces and
evidence stand. Deadline discipline unchanged (S6 resolution by 2026-08-30,
hard freeze 2026-09-01).
