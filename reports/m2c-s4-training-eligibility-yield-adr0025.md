# M2C S4 training-eligibility yield audit (ADR-0025 §3)

Status: `BLOCKED_ZERO_OBSERVED_ELIGIBLE_CHAIN_YIELD`

This report replays seven immutable collection reports plus the governed offline replay of scene 19083. It does not collect, execute physics, train, run a model rollout, or perform formal Q-B evaluation.

## Measured yield

- Unique TRAIN identities: **22** (V3: 11; V4: 11)
- Complete eight-step physical chains: **14**
- Eligible and packaged training episodes: **0**
- Eligible yield per attempted identity: **0/22 = 0.0**
- Eligible yield conditional on a complete chain: **0/14 = 0.0**
- Finite evidence-based key projection for one eligible episode: **none at the observed zero point yield**

The code-level minimum is one complete eligible episode; the current trainer rejects zero. This is not a claim that model capability is zero: pure model success remains `null` because no formal Q-B evaluation has run.

## Complete-chain failure taxonomy

- Terminal contact/controller rejection: **9**
- Terminal pregrasp IK rejection: **4**
- Lifted but rejected by the public success predicate: **1**

All ten complete V3 chains and all three newly collected Batch-09 V4 chains passed gates for steps 0–6. The evidence supports a recurring terminal regrasp approach/contact-acceptance mismatch, but does not isolate perception offset, approach geometry, or object state as its cause. Scene 19083 passes the 32-detection offline schema replay but remains excluded by its unchanged physical failure; its replay also records a step-1 public-target-outside-K8 exclusion.

## Frozen eligibility consequence

V3 and V4 eligibility are episode-atomic: `final_task_success=true`, an exact eight-step chain, and the remaining physical/public gates are required. A failed episode emits an empty dataset, so intermediate steps from these failed chains are not currently model-supervisable rows. This audit does not change that predicate, B0, a safety gate, or a threshold.

## 2026-08-20 checkpoint

At the unchanged observed point yield, no finite collection size can be justified even for one eligible episode. Training remains unauthorized and formal Q-B remains unmeasured. The Phase-2 bundle-smoke checkpoint stays 2026-08-20 (Asia/Shanghai).

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_s4_training_eligibility_yield_adr0025.py --expected-json reports/m2c-s4-training-eligibility-yield-adr0025.json
```
