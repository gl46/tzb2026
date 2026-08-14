# M2C S4 V4 Batch-22 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH22_WITH_STAGE_FAILURE`

The three outcome-blind preregistered extension TRAIN keys were consumed exactly once, with no
retry or replacement. Scenes 22053 and 22087 reached Isaac startup but their stage processes
exited with code 139 before stage acceptance. Scene 22107 completed a strict eight-step V4
physical chain and ended at the unchanged pregrasp-IK gate. Host replay accepted that raw chain
under the ADR-0025 32-detection schema and produced an `EMPTY` dataset.

## Observed outcomes

- scene 22053: stage process exit 139; no probe and no physical action.
- scene 22087: stage process exit 139; no probe and no physical action.
- scene 22107: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch22_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch22-complete \
  --expected-json reports/m2c-s4-v4-batch22-collection.json
```
