# M2C S4 ADR-0026 decision-level supervision dataset card

Status: `PASS_PACKAGED_DECISION_LEVEL_SUPERVISION`

## Scope and intended use

This is offline, model-training supervision for the world-model/coarse decision heads.
It is not a safety/controller substitute and does not alter formal Q-B success.
V3 and V4 are separate shards; no historical observation is silently upgraded.

## Replay and rows

- Complete chains replayed: **49**
- Prefix-eligible episodes: **49**
- Excluded prefix episodes: **0**
- Decision rows: **344** (V3 71; V4 273)
- Decision-index histogram: `{'0': 49, '1': 49, '2': 49, '3': 49, '4': 49, '5': 49, '6': 49, '7': 1}`
- Skill-head rows: **344**
- Pointer-head rows: **330**; masked: **14**
- Destination-head rows: **344**

## Required episode outcome mix

- Final task success: **0 success / 49 failed**
- Every row carries its source episode's terminal outcome.
- Terminal physical execution: **1 succeeded / 48 failed**
- Decision 7 appears only for the one physically successful `LIFTED` terminal step.

## K8 masking retained without label fabrication

- Fourteen decisions have a public selected target outside the replayed K8.
- Their skill and destination supervision remains valid under ADR-0026, while pointer
  supervision is masked; no pointer class is guessed or fabricated.
- The approved 32-capacity schema does not change final K=8.

## Boundaries

- Teacher used: false
- Privileged simulator truth as policy input: false
- Collection/physics/model rollout/training/Q-B performed by packaging: false
- Existing episode outcomes reinterpreted: false
- Bundle-smoke checkpoint: **2026-08-20 Asia/Shanghai** (unchanged)
