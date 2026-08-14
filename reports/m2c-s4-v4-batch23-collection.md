# M2C S4 V4 Batch-23 collection audit

Status: `BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH23_WITH_STAGE_FAILURE`

The three outcome-blind preregistered extension TRAIN keys were consumed exactly once, with no
retry or replacement. Scene 22141 reached Isaac startup but the stage process exited with code
139 before stage acceptance. Scenes 22112 and 22163 completed strict eight-step V4 physical
chains; the former ended at the unchanged REGRASP contact gate and the latter at the unchanged
pregrasp-IK gate. Host replay accepted both raw chains under the ADR-0025 32-detection schema and
produced `EMPTY` datasets.

## Observed outcomes

- scene 22112: steps 0-6 passed; REGRASP ended `CONTACT_GATE_REJECTED`.
- scene 22141: stage process exit 139; no probe and no physical action.
- scene 22163: steps 0-6 passed; REGRASP ended `PREGRASP_IK_GATE_REJECTED`.
- Collision or safety violations: **0**.
- Eligible / packaged training episodes: **0 / 0**.

The result does not imply pure model success is zero. Training, model rollout, and formal Q-B
evaluation did not run, so `pure_model_success_episodes` remains `null`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_v4_batch23_collection.py \
  --evidence-root /Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch23-complete \
  --expected-json reports/m2c-s4-v4-batch23-collection.json
```
