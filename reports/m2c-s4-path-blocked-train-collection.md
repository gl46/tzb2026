# M2C S4 PATH_BLOCKED TRAIN collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_TRAIN_SAMPLES`.

This report is an offline audit of collection attempts only. It is not training, a model rollout, Teacher inference, or Q-B evaluation. The authoritative machine-readable receipt, including per-key frozen identity and independently recomputed SHA-256 bindings for every evidence file, is `reports/m2c-s4-path-blocked-train-collection.json`.

## Observed evidence

| Scene / failure seed | Frozen matched key | Observed classification |
| --- | --- | --- |
| 12000 / 120007 | `m2c-s4-s6-4962a57684c57e8aafaeef69aa747485dff6907c87f83bee63ede1ea91bf7a6c` | no raw; console terminates with public target outside canonical K=8 |
| 12005 / 120057 | `m2c-s4-s6-6a2da6182be05c10358e9f88221133ef922ee644b86f13ba1d9d96a66060380b` | no raw; console terminates with public target outside canonical K=8 |
| 12008 / 120087 | `m2c-s4-s6-4fa521ea25328b9effeec7d9e8167d02093e70ec06db929d557f6d07956e1a2c` | no raw; console terminates with public target outside canonical K=8 |
| 12029 / 120297 | `m2c-s4-s6-132ad80b24303252253206f686d58aef08b8033a6344af334a3fcc4470bafc13` | no raw; console terminates with public target outside canonical K=8 |
| 12050 / 120507 | `m2c-s4-s6-2f4e8e0a4a2fc5f2d74e4d9ad0a5e01dec5c1033173604beb22e281f71782bf2` | complete scripted raw `PASS`; final task false; regrasp `CONTACT_GATE_REJECTED` |
| 12086 / 120867 | `m2c-s4-s6-1888a71f26673a96f002910f75e090e9ce070a403ce223f53e31d4aa45267d83` | complete scripted raw `PASS`; final task false; regrasp `CONTACT_GATE_REJECTED` |
| 12091 / 120917 | `m2c-s4-s6-5b8e56c563afc5b4d941c8d17a120cab4d57c0aeffd68eb6fd20d97ff0a38deb` | no raw; console terminates with public target outside canonical K=8 |
| 12071 / 120717 | `m2c-s4-s6-f52e1d21780c29607fe7cef68462582c48a9f2c550465c52047fa45fd3b1fa17` | no raw; console terminates with public target outside canonical K=8 |
| 12143 / 121437 | `m2c-s4-s6-47409cfba791cc436557e20aec69fd0bb2bcef7d6cb5c48331ff742f90da7869` | no raw; console terminates with public target outside canonical K=8 |
| 12169 / 121697 | `m2c-s4-s6-a43e239fbf1ae465f18bb88950fbbccce2ac72f865369426296996bdee4bc4ab` | infrastructure stage crash: exit 139; no metrics; empty probe directory; no raw |
| 12109 / 121097 | `m2c-s4-s6-2254c8eaf1e913d14e19fecda4d2cab332ead3d08c1084e1581ef33fb45fb4a0` | no raw; console terminates with public target outside canonical K=8 |

The eleven keys are unique frozen `TRAIN/train` identities. No SMOKE, S6 evaluation, or V4 key is included. Of 36 frozen TRAIN keys, 25 are unobserved; this audit makes no inference about those 25.

Batch 02 is bound to `docs/decisions/M2C-S4-TRAIN-COLLECTION-BATCH-02-PREREG.md` at file SHA-256 `177820dae82127c7bef30e9ebf7fd479596c5c60f68ccb312c4cf3ddce3a6e89` and commit `b66870e65743f87f8d8ad111c64dd7b81de40161`. The auditor recomputes its outcome-independent rule after excluding the first eight scene seeds: choose the smallest remaining scene seed in each SDF partition. It reproduces exactly `12143, 12169, 12109` and their frozen key identities.

## Boundaries and result

- Training samples packaged: **0**.
- Training samples eligible: **0**.
- Training executed: **false**.
- Model rollout executed: **false**.
- Teacher used: **false**.
- Privileged simulator truth used as policy input: **false**.
- Formal Q-B evaluation executed: **false**.
- Scripted collection counted as pure model success: **false**.
- `pure_model_success_episodes`: **not measured (`null`)**, not zero.

The two raw envelopes are physical scripted-public-supervision evidence. A top-level probe `PASS` does not override `final_task_success=false` or the final regrasp controller rejection, and it cannot be reported as model-owned or pure success.

## Integrity and replay

The auditor validates frozen manifest content digests, exact TRAIN identity, exclusion from SMOKE/S6/V4, job boundaries, stage source hashes, partial-receipt hashes, raw physical-receipt hashes, eight-step skill/action protocols, and exact terminal classification. It independently hashes every regular evidence file (including captures, consoles, raw envelopes, stages, and manifests) and freezes a canonical evidence-tree digest. Copied `files.sha256` files are explicitly not trusted roots; their actual bytes are separately bound, and any non-self entries are only an auxiliary cross-check.

Replay is fail-closed against the committed JSON report:

```bash
.venv/bin/python scripts/m2c/audit_path_blocked_train_collection.py \
  --expected-report reports/m2c-s4-path-blocked-train-collection.json \
  --training-keys configs/m2c_s4_training_keys.json \
  --s6-keys configs/m2c_s6_evaluation_keys.json \
  --batch02-prereg docs/decisions/M2C-S4-TRAIN-COLLECTION-BATCH-02-PREREG.md \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/k8-admissibility/attempt2 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/k8-admissibility/attempt3 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/k8-admissibility/attempt5 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/k8-admissibility/attempt6 \
  --attempt RAW_PASS_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED=/Users/gl/tzb-m2c-evidence/m2c-s4/k8-admissibility/attempt7c \
  --attempt RAW_PASS_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED=/Users/gl/tzb-m2c-evidence/m2c-s4/train-collection-b6def060/attempt8 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/train-collection-b6def060/attempt9 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/train-collection-b6def060/attempt10 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/train-collection-batch02-b66870e/attempt11 \
  --attempt INFRASTRUCTURE_STAGE_EXIT_139=/Users/gl/tzb-m2c-evidence/m2c-s4/train-collection-batch02-b66870e/attempt12 \
  --attempt PUBLIC_TARGET_OUTSIDE_CANONICAL_K8=/Users/gl/tzb-m2c-evidence/m2c-s4/train-collection-batch02-b66870e/attempt13
```

## Task report

Changed files:

- `scripts/m2c/audit_path_blocked_train_collection.py`
- `tests/unit/test_m2c_path_blocked_train_collection_audit.py`
- `reports/m2c-s4-path-blocked-train-collection.json`
- `reports/m2c-s4-path-blocked-train-collection.md`

Tests:

- `.venv/bin/pytest -q tests/unit/test_m2c_path_blocked_train_collection_audit.py`
- `.venv/bin/ruff check scripts/m2c/audit_path_blocked_train_collection.py tests/unit/test_m2c_path_blocked_train_collection_audit.py`
- `for audit_file in scripts/m2c/audit_path_blocked_train_collection.py tests/unit/test_m2c_path_blocked_train_collection_audit.py reports/m2c-s4-path-blocked-train-collection.json reports/m2c-s4-path-blocked-train-collection.md; do git diff --no-index --check /dev/null "$audit_file" || test $? -eq 1; done`

Failures: the first bare `pytest` invocation was unavailable in the shell (`command not found`); the project `.venv` invocation is the supported command. The first real evidence replay also correctly found that per-step action protocols differ by skill; the auditor and fixture were corrected to freeze the observed `m_rad`, `m`, and observation-only protocols before the report was generated.

Blockers: zero packaged or eligible TRAIN samples; 25 frozen TRAIN keys remain unobserved; observed collection is systemically blocked by public K8/regrasp admissibility, with one additional infrastructure crash.

Next command: **stop further batch collection and request human ADR direction**. Do not self-preregister batch 03. The replay command above remains the local read-only integrity check, not authorization for more collection.
