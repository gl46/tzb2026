# M2C S4 V4 Batch-18 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH18`

The final outcome-blind preregistered TRAIN key was consumed exactly once, with no retry or
replacement. It completed a strict eight-step V4 physical chain. Scene 19307 ended at the
unchanged REGRASP pregrasp-IK gate. Host replay accepted the raw chain under the ADR-0025
32-detection schema and produced an `EMPTY` dataset.

## Observed outcomes

- scene 19307: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch18_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch18-complete \
  --expected-json reports/m2c-s4-v4-batch18-collection.json
```
