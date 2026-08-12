# M2C S4 PATH_BLOCKED public-input admissibility

- Status: **BLOCKED_PUBLIC_INPUT_ADMISSIBILITY**
- Scope: scripted, public-only physical training supervision; not a model rollout
- Frozen contract: fresh public tracks, literal `track_id` ascending, first K = 8
- Observed frozen TRAIN key identities: **3 / 36**
- Frozen byte-identical SDF layouts covered by those observations: **3 / 3**
- Packaged / eligible PATH_BLOCKED training samples: **0 / 0**
- Training executed: **false**
- Q-B evaluation executed: **false**
- Teacher used: **false**
- Privileged simulator truth used as policy input: **false**
- B0 implementation or parameters changed: **false**
- Safety or mapping gates relaxed: **false**

## Finding

One frozen TRAIN key was physically run for each of the three byte-identical
SDF layouts represented by the 36-key manifest. All three observed keys reach
step 6 with the public task target visible, but the target is outside the exact
ADR-0020 K=8 candidate list. The hash-bound public RGB-D replay gives:

| Scene / failure seed | Step-6 public tracks | Target confidence | Literal-ID rank | Result |
| --- | ---: | ---: | ---: | --- |
| 12000 / 120007 | 10 | 0.99 | 9 | `PUBLIC_TARGET_OUTSIDE_CANONICAL_K8` |
| 12005 / 120057 | 11 | 0.99 | 10 | `PUBLIC_TARGET_OUTSIDE_CANONICAL_K8` |
| 12008 / 120087 | 11 | 0.99 | 10 | `PUBLIC_TARGET_OUTSIDE_CANONICAL_K8` |

This is a public-input admissibility failure, not a Qwen prediction failure.
The collection runs were scripted supervision, and neither training nor formal
Q-B evaluation ran. Therefore `pure_model_success_episodes` is **unmeasured**,
not zero. The complete per-frame track lists, K=8 slots, RGB/depth hashes,
stage-metrics hashes, partial-input manifest hashes, probe-console hashes, and
collection-job hashes are in
`reports/m2c-s4-path-blocked-k8-admissibility.json`.

The frozen manifest has 12 key identities per SDF layout. Only 3/36 key
identities were physically observed; the other 33 have distinct failure seeds
and supervision bytes. Their rollout outcomes are deliberately not inferred
from the shared SDF bytes. The auditor binds the three observed identities to
the frozen manifest and rejects duplicate-layout or non-TRAIN substitutions.

Attempt 4 for scene 12008 exited 139 during RTX/USD stage startup before probe
evidence. It is recorded as an infrastructure failure and excluded from the
three-attempt K=8 finding; attempt 5 repeated scene 12008 successfully through
the public probe and reproduced the K=8 rejection.

## Gate interpretation

- **D1 is not triggered.** Q-A V4 already passed with B0 0/3 and an existence
  proof. This later failure is not a fifth S2 domain candidate.
- **D2 is not triggered.** No trained model or formal Q-B episode was run, so a
  strict pure-success count has not been measured.
- Confidence filtering, a larger K, TaskSpec target injection, privileged
  identity, replacement TRAIN keys, or use of SMOKE/S6 keys would change or
  evade the frozen contract and are rejected.
- A bounded public recapture/candidate contract may only be introduced by a
  new human ADR/addendum. Continuing the already frozen remaining TRAIN keys
  does not change the contract, but cannot be represented as already observed.

## Task report

- Changed files: public-only K=8 auditor, its unit tests, and this JSON/Markdown
  finding pair.
- Tests: `PYTHONPATH=src:scripts .venv/bin/python -m pytest -q tests/unit/test_m2c_path_blocked_k8_audit.py`.
- Failures: attempt 4 infrastructure exit 139; attempts 2/3/5 fail closed at
  step 6 with `PUBLIC_TARGET_OUTSIDE_CANONICAL_K8`.
- Blockers: zero eligible PATH_BLOCKED chain samples; 33 frozen TRAIN key
  identities remain unobserved; formal Isaac runner remains physically
  unverified and unfrozen.
- Next command: continue the already frozen TRAIN collection only if additional
  failure-seed coverage is required; do not train/evaluate with zero eligible
  PATH_BLOCKED samples and do not change K/sorting without a human ADR.
