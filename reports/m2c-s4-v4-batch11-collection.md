# M2C S4 V4 Batch-11 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH11_WITH_STAGE_FAILURE`

The three outcome-blind preregistered TRAIN keys were consumed exactly once, with no retry or
replacement. Scene 19162 reached Isaac startup but the stage process exited with code 139 before
stage acceptance. Scenes 19167 and 19173 completed strict eight-step V4 physical chains; both
ended at the unchanged REGRASP contact gate. Host replay accepted both raw chains under the
ADR-0025 32-detection schema and produced `EMPTY` datasets.

## Observed outcomes

- scene 19162: stage process exit 139; no probe and no physical action.
- scene 19167: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 19173: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`; offline replay also
  records `STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch11_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch11-complete \
  --expected-json reports/m2c-s4-v4-batch11-collection.json
```
