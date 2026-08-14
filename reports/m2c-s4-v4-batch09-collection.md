# M2C S4 V4 Batch-09 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH09`

The three outcome-blind preregistered TRAIN keys were consumed exactly once. All three stage
builders and all three physical probes completed, producing three strict eight-step V4 raw
chains and 24 physical skill receipts. Host replay passed for every chain under the ADR-0025
32-detection raw schema. No episode satisfied the unchanged final training predicate, so no
training sample was eligible or packaged.

## Observed outcomes

- scene 19085: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- scene 19120: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 19121: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`; offline replay also
  records `STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch09_collection.py   --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch09-complete   --expected-json reports/m2c-s4-v4-batch09-collection.json
```
