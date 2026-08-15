# M2C Phase-2 source-binding application

- Status: **PASS_SOURCE_BINDINGS_APPLIED**
- Frozen implementation commit: `3b86d4c997a6e2a7229c6e8149200b166fa32d77`
- Frozen Git tree: `14d7659ac76b9a0b1f4e0fec0bc9d6175894a8bf`
- Isaac image: `sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9`
- Complete transitive-manifest SHA-256: `684c81dcb00d0abf33095bc704e7550d9bb64400b367d2b5da9324aeb85c8993`
- Tracked files replayed: **1258** (59 executable)
- Physical execution, training, or Q-B evaluation performed here: **no**
- Teacher or privileged truth used: **no**

The accepted ADR-0022 binding addendum was frozen at SHA-256
`712fe64e60bf31b67d1eb5552bc2e9a9cfa96c43b07c4e7f2ebbc3a57207078b`.
The full source tree was then built and replayed inside the exact Isaac image.
The image has no bundled Git executable, so the labserver Git 2.43.0 binary
(`2a8c18fb…`) and its helper directory were mounted read-only solely for tree
enumeration; they are not runtime inputs to the model, planner, or controller.

The create-only closure is retained at:

- labserver: `/var/tmp/xh-data/isaac-industrial/m2c/phase2-source-closure-3b86d4c/evidence/source-closure`;
- local evidence mirror: `/Users/gl/tzb-m2c-evidence/m2c-phase2-source-closure-3b86d4c`.

Its manifest and receipt are sealed read-only. The receipt records no training,
physical execution, Q-B evaluation, Teacher use, or privileged-truth policy
input.

## Applied source bindings

- `FORMAL_PHYSICAL_RUNNER_BINDING = (scripts/m2c/run_formal_model_owned_chain_v4.py, 799cae…)`;
- `FORMAL_DEPLOYMENT_CLOSURE_BINDING = (3b86d4c…, sha256:783444…, 684c81…)`.

ADR-0024 withdrew the two compatibility prerequisites, which remain literal
`None`:

- `FROZEN_B0_RUNTIME_WRAPPER_BINDING`;
- `OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING`.

This source application authorizes only the no-Teacher S4 trainer. It does not
authorize formal Q-B execution or a success claim. The trained model bundle,
selected scene/SDF and runtime assets, reviewed real-Isaac HTTP backend factory,
two host audits, single-use challenge, and plan-specific A.3/execution receipts
remain mandatory. Until those exist, formal Q-B remains
`BLOCKED_UNMEASURED` rather than measured zero.

The 2026-08-20 bundle-smoke checkpoint is unchanged.
