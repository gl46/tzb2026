# M2C S4 ADR-0026 decision-level Qwen V4 contract smoke

Status: **PASS_DECISION_DATA_AND_TRAINING_CONTRACT_BLOCKED_BEFORE_REAL_TRAINING**

The ADR-0026 V4 shard was independently replayed from 39 source evidence
files and 546 bound public RGB-D assets. It contains 273 decision rows from
39 complete step-0-through-step-6 prefixes. Skill and destination supervision
cover all 273 rows; pointer supervision covers 259 rows and is masked for the
14 rows whose public target lies outside the frozen K=8 candidates. The V3
shard remains separate and was not upgraded into V4.

The offline three-head contract smoke passed with prompt digest
`63e19a83c9f1bb63a125f34838e8689e1d48319ed7a1387d05cf835264dafa9f`.
It performed zero optimizer steps and wrote no checkpoint. Teacher and
privileged simulator truth were not used.

The real-only trainer now enforces the hard-freeze gate, both active Phase-2
bindings, full data replay before model-cache access, the canonical local Qwen
revision, all 273 rows without subsampling, and create-only publication. Only
pointer loss may be masked; skill and destination losses remain mandatory. A
versioned ADR-0026 decision-level bundle writer/loader was added separately so
the byte-frozen ADR-0025 V4 bundle implementation and historical evidence keep
their original meaning.

Real training did **not** run. The new decision-bundle loader is not yet part
of the formal deployment closure. `FORMAL_PHYSICAL_RUNNER_BINDING` and
`FORMAL_DEPLOYMENT_CLOSURE_BINDING` are still unset, so the trainer rejects
before data/model execution. The two ADR-0024-withdrawn compatibility bindings
also remain `None`. This is an execution-closure blocker, not a model result.
The 2026-08-20 (Asia/Shanghai) bundle-smoke checkpoint is unchanged.

Next command:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/check_adr0022_binding_addendum_readiness.py
```
