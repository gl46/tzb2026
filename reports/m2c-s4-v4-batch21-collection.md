# M2C S4 V4 Batch-21 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH21`

The first three outcome-blind keys from the frozen V4 extension manifest were consumed exactly
once, with no retry or replacement. All three completed strict eight-step V4 physical chains.
Scenes 22026 and 22044 ended at the unchanged REGRASP contact gate; scene 22048 ended at the
unchanged REGRASP pregrasp-IK gate. Host replay accepted all raw chains under the ADR-0025
32-detection schema and produced `EMPTY` datasets.

## Observed outcomes

- scene 22026: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 22044: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`; offline replay also
  records `STEP_4:PUBLIC_TARGET_OUTSIDE_V4_K8`.
- scene 22048: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch21_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch21-complete \
  --expected-json reports/m2c-s4-v4-batch21-collection.json
```
