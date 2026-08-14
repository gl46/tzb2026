# M2C S4 V4 Batch-15 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH15`

The three outcome-blind preregistered TRAIN keys were consumed exactly once, with no retry or
replacement. All three completed strict eight-step V4 physical chains. Scene 19233 ended at the
unchanged REGRASP pregrasp-IK gate; scenes 19244 and 19265 ended at the unchanged REGRASP
contact gate. Host replay accepted all raw chains under the ADR-0025 32-detection schema and
produced `EMPTY` datasets.

## Observed outcomes

- scene 19233: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- scene 19244: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 19265: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`; offline replay also
  records `STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch15_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch15-complete \
  --expected-json reports/m2c-s4-v4-batch15-collection.json
```
