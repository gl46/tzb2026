# M2C S4 V3 TRAIN collection batch 03 audit

Status: **BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES_BATCH03**.

the three preregistered TRAIN keys were each attempted exactly once without retry; all produced byte-verified eight-step V3 K8 scripted chains with steps 0-6 passing. Scene 16073 physically reported LIFTED but the unchanged public predicate rejected success, scene 16085 ended at the contact gate, and scene 16102 ended at the pregrasp IK gate. No result is promoted to an eligible training sample.

This is a byte-bound audit of scripted TRAIN collection only. It is not training, a model rollout, Q-B evaluation, or evidence of pure model success.

## Counts

- Pre-registered keys attempted once: 3 / 3
- Retry or replacement attempts: 0
- Raw V3 eight-step K8 chains: 3
- Eligible/packaged training samples: 0 / 0
- Distinct frozen SDF identities covered: 3
- Regular evidence files byte-hashed: 164

## Attempts

| Attempt | Scene | Frozen key | Step-7 physical status | Classification | Eligible |
| --- | ---: | --- | --- | --- | --- |
| `batch03-01` | 16073 | `m2c-s4-v3-train-a101b1d9d220df…` | `LIFTED` | `RAW_V3_REGRASP_LIFTED_PUBLIC_PREDICATE_REJECTED` | no |
| `batch03-02` | 16085 | `m2c-s4-v3-train-cc4279699767f1…` | `CONTACT_GATE_REJECTED` | `RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED` | no |
| `batch03-03` | 16102 | `m2c-s4-v3-train-87da40d69271e4…` | `PREGRASP_IK_GATE_REJECTED` | `RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED` | no |

Scene 16073 is deliberately not called successful: its physical receipt says `LIFTED`, but the frozen public result has no carried public track and no `grasped=true` / `lifted=true` predicates. The unchanged public acceptance rule therefore keeps `final_task_success=false` and the sample ineligible.

## Boundaries

Training executed: false. Model rollout executed: false. Teacher used: false. Privileged truth used as policy input: false. Formal Q-B evaluation executed: false. `pure_model_success_episodes` is null. No claim is made about unobserved TRAIN keys or model/Q-B performance.
