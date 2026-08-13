# M2C S4 V3 TRAIN collection audit

Status: **BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES**.

nine execution-attempt directories cover eight unique frozen V3 TRAIN keys and all three frozen SDF identities; seven raw eight-step scripted chains passed steps 0-6 but ended with a rejected step-7 regrasp and final_task_success=false, one stage terminated with exit 139, and the first scene-16012 probe stopped at the pre-Kit tzdata hard-freeze guard; therefore zero episodes are training-eligible

This is a byte-bound audit of scripted TRAIN collection only. It is not training, a model rollout, Q-B evaluation, or evidence of pure model success.

## Counts

- Execution-attempt directories: 9
- Unique frozen TRAIN keys attempted: 8
- Raw V3 eight-step chains: 7
- Eligible/packaged training samples: 0 / 0
- Frozen SDF identities covered: 3
- Regular evidence files byte-hashed: 415

## Attempts

| Attempt | Scene | Frozen key | Observed terminal class | Eligible |
| --- | ---: | --- | --- | --- |
| `batch01-retry1` | 16012 | `m2c-s4-v3-train-ed5fcd556eca92…` | `RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED` | no |
| `batch01-tzdata-failure` | 16012 | `m2c-s4-v3-train-ed5fcd556eca92…` | `PRE_KIT_TZDATA_GUARD_FAILURE` | no |
| `batch02` | 16022 | `m2c-s4-v3-train-a8203adbc267df…` | `RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED` | no |
| `batch02-prereg-01` | 16047 | `m2c-s4-v3-train-ecda02ee3573ed…` | `RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED` | no |
| `batch02-prereg-02` | 16066 | `m2c-s4-v3-train-0b384127e1af7c…` | `RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED` | no |
| `batch02-prereg-03` | 16081 | `m2c-s4-v3-train-bbb839d64e2c4e…` | `RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED` | no |
| `batch03` | 16025 | `m2c-s4-v3-train-36050eeec15031…` | `INFRASTRUCTURE_STAGE_EXIT_139` | no |
| `batch04` | 16026 | `m2c-s4-v3-train-fbbe4d803e6cd3…` | `RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED` | no |
| `batch05` | 16063 | `m2c-s4-v3-train-55baf6bd195df3…` | `RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED` | no |

## Boundaries

Training executed: false. Model rollout executed: false. Teacher used: false. Privileged truth used as policy input: false. Formal Q-B evaluation executed: false. `pure_model_success_episodes` is null because no model rollout was evaluated.

Batch-02 selection was independently recomputed from the frozen manifest and the committed pre-registration; exactly the three selected keys were attempted once and the stop-after-three rule was observed.
