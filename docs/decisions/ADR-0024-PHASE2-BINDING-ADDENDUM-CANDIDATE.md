# ADR-0024 Phase-2 binding addendum candidate — CONTRACT_SMOKE_ONLY

- Status: **CONTRACT_SMOKE_ONLY / BLOCKED_UNMEASURED**
- Checkpoint: **2026-08-20 (Asia/Shanghai)**
- Production binding authorized: **false**
- Physical or formal evidence produced: **false**
- Teacher used: **false**
- Privileged simulator truth used as policy input: **false**

This file is a machine-audited candidate, not an accepted binding addendum and
not a production configuration. It records the locally testable portion of
ADR-0024 Phase-2 while all four compatibility/entry assignments remain literal
`None`. It must not be renamed or reinterpreted as
`ADR-0022-BINDING-ADDENDUM.md`; that formal artifact can exist only after real
deployment and eight-skill evidence satisfies the project evidence bar.

## What the local contract smoke proves

- `M2CExactPlanPrimitiveBundleV1` binds ADR-0022 plus the superseding accepted
  ADR-0024, keeps each exact phase immutable, preflights all phases before an
  executor call, and never replans, inserts, retries, or changes a failed plan.
- A.3 decodes the exact controlled Panda URDF/SRDF and only the byte-bound
  link2/link4 STL assets; it expands every collision element into canonical
  children, retains every decoded STL vertex for the conservative hull, and
  binds all numeric configuration, geometry, FK inputs/outputs, native source,
  headers, compiler flags, float64 libraries, build manifest, and receipts.
- The flat native ABI is query-only, rejects unknown/non-finite/degenerate
  shapes, separately checks start/end distance, and never treats an ambiguous
  `calcTimeOfImpact == false` as clear without an independent conservative
  motion-disc certificate.
- ADR-0024 section 2 is the only runtime rejection policy: invalid mapping,
  stale pointer, invalid cell, failed gate, or failed preflight terminates as
  `NO_PHYSICAL_EXECUTION`. It is not a hold, retry, substitute skill, or B0
  action and can never be relabelled `B0_FALLBACK`.

These are contract properties only. They do not prove a native build, real FK,
Isaac startup, physical safety, execution success, model-owned success, or
entry readiness.

## A.3 delegated numeric configuration

The candidate binds configuration digest
`1193e1bfab421cc69373e6e41b350c26e69a4a07ca17e66f92271aea365427d0`:

- Bullet 3.24 scalar ABI `float64`; `BT_USE_DOUBLE_PRECISION`, no fast-math;
- hull construction tolerance `1e-7 m`;
- outward-only post-construction padding `0.002 m`;
- box/cylinder/hull margin `0.04 m`, never smaller than shipped default;
- allowed penetration `0.0 m` and contact rejection threshold `0.001 m`;
- TOI interval `[0,1]`, rejection-biased comparison tolerance `1e-7`;
- native/declared maximum iterations `64`; exhaustion rejects;
- subdivision cap `4096`, using each child maximum angular-motion radius and
  the pair's smallest conservative radius; cap/ambiguity rejects;
- query timeout `5,000,000,000 ns`.

The machine config binds the exact source and asset digests. The original STL
bytes and pinned Bullet float64 runtime do not exist on this local Mac, so the
capability receipt is explicitly `NOT_AVAILABLE`; no fixture may produce a
production PASS.

## B0 boundary

`FrozenB0FallbackWrapperV1` and ADR-0022 A.5 are withdrawn by accepted
ADR-0024 section 2. They are not prerequisites and are not callable from the
formal runtime. The M2B B0 freeze remains unchanged as the independent
comparison arm in separate episodes. This candidate modifies neither B0 bytes
nor any safety/IK/collision/controller gate.

## Production bindings

- `FORMAL_PHYSICAL_RUNNER_BINDING = None`
- `FORMAL_DEPLOYMENT_CLOSURE_BINDING = None`
- `FROZEN_B0_RUNTIME_WRAPPER_BINDING = None` (withdrawn compatibility sentinel)
- `OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None` (withdrawn compatibility sentinel)

## Blocking evidence

- `EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING`
- `IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING`
- `ORIGINAL_LINK2_LINK4_STL_ASSETS_NOT_AVAILABLE_LOCALLY`
- `PINNED_BULLET_FLOAT64_NATIVE_BUILD_AND_PACKAGE_RECEIPT_MISSING`
- `REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING`
- `REAL_QUERY_ONLY_FK_PROVIDER_BINDING_MISSING`
- `REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING`

No training, Isaac scene startup, physical action, SMOKE, Q-B, or S5/S6
evaluation was performed while generating this candidate. No Teacher entered
the control path; Teacher kill rules remain unchanged.

## One next command

```bash
.venv/bin/python scripts/m2c/audit_adr0024_phase2_candidate.py --project-root .
```
