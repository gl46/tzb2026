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

The real-Isaac exact-plan executor implementation is present and contract
tested. It calls only the hash-frozen execution helpers and cannot select a
yaw, centreline, retry, fallback, or replacement command at runtime. This does
not make it deployable: its reviewed deployment binding remains absent, and
the real plan-synthesis backend plus real episode lifecycle/capture source are
not bound.

## A.3 delegated numeric configuration

The candidate binds configuration digest
`8c6ba840339bca5a84ccd805b0c068439d59812eb0c3ecc9bdd809f1341d4bb5`:

- Bullet 3.24 scalar ABI `float64`; `BT_USE_DOUBLE_PRECISION`, no fast-math;
- hull construction tolerance `1e-7 m`;
- outward-only post-construction padding `0.002 m`;
- primitive margins reproduce Bullet 3.24's shipped `setSafeMargin` formula
  per concrete shape instance; the exact governed-Panda maxima are
  `0.0055074 m` for boxes and `0.008 m` for the cylinder, while each convex
  hull uses the shipped `0.04 m`; every payload independently proves it is no
  smaller than its actual constructor default;
- allowed penetration `0.0 m` and contact rejection threshold `0.001 m`;
- TOI interval `[0,1]`, rejection-biased comparison tolerance `1e-7`;
- native/declared maximum iterations `64`; exhaustion rejects;
- subdivision cap `4096`, using each child maximum angular-motion radius and
  the pair's smallest conservative radius; cap/ambiguity rejects;
- query timeout `5,000,000,000 ns`.

The machine config binds the exact source and asset digests. The original STL
bytes and pinned Bullet float64 runtime were replayed in the independent
query-only build report `reports/m2c-phase2-a3-native-build.json`. Builder image
`sha256:01d3c57b…` produced native module `2231cee6…`; the controlled Panda
URDF/SRDF and both STL files replay to exactly 14 collision children. This
closes the asset/native-build availability blockers, but it is not physical
evidence and does not make formal execution eligible.

The controlled-Panda read-only FK implementation is complete at the
contract/equivalence layer. A separately compiled node2 verifier using ROS
Jazzy `kdl_parser` and Orocos KDL 1.5.1 compared 12 frozen states across all
12 collision-bearing link frames (144 transforms). Maximum translation error
was `2.5438405243138006e-16 m`; maximum relative-quaternion orientation error
was `5.147892387644517e-16 rad`, both below the frozen `1e-12` tolerances.
The exact report is `reports/m2c-phase2-a3-controlled-panda-fk.json`. This
closes provider implementation/numeric equivalence, not its immutable
deployment/session binding.

The query-only deployment path is now byte-replayed under the pinned Isaac 6
container image without loading Kit or Isaac. The create-only final receipt
SHA-256 is `a50740f34adef952d89613ecd8b23c132152e47f09791360f46301b2fca70c50`.
It completed all 76 child-pair queries with zero query failures: 74 were clear
and two were fail-closed static collision rejections (hand-link7 and
link2-link4). The comparison report is
`reports/m2c-phase2-a3-query-only-deployment-comparison.json`. Thus the
permission and native deployment path is closed. The arbitrary frozen home
state is not a universal capability gate: that specific state correctly
rejects under A.3 and remains non-executable. It is not converted into an ACM
exception, a reduced margin, or an execution authorization. Formal execution
instead requires each actual bound plan to pass its complete plan-specific A.3
replay before any command.

The preflight coordinator now defines `ExactPlanA3DeploymentBindingV2`. It
implements ADR-0024 section 4 directly: trusted-host signatures and launcher
attestation are not prerequisites. The reviewed binding instead covers the
accepted ADR, addendum and unlock config, immutable implementation commit and
container, exact plan source set, complete A.3 configuration, query callback,
session-audit implementation, and host-local HMAC verifier. A successful
authorization still claims no physical action; the real session-bound phase
and bundle receipts plus post-execution HMAC replay remain required evidence.

The V4 host-local HMAC verifier and create-only CLI now replay both sides of a
terminalized episode without any SSH signature, trust root, or signer
principal. They bind the one-shot challenge receipt, formal evidence, exact
Qwen/Isaac audit lifecycle, every authenticated envelope, and variable counts
for one through eight model decisions. This is still contract-only: no real
node2 or labserver receipt exists and the V4 Isaac HTTP backend factory is
unbound. The ADR-0024 V2 readiness verifier is implemented and remains
fail-closed until its exact real-evidence index is supplied.

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
- `REAL_BOUND_PLAN_SYNTHESIS_BACKEND_NOT_BOUND`
- `REAL_ISAAC_EPISODE_LIFECYCLE_AND_CAPTURE_SOURCE_NOT_BOUND`
- `REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND`
- `IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING`
- `REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING`
- `REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING`
- `REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING`
- `S4_ENTRY_GATE_FORMAL_V4_EVIDENCE_REPLAY_NOT_BOUND`
- `TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET`

No training, Isaac scene startup, physical action, SMOKE, Q-B, or S5/S6
evaluation was performed while generating this candidate. No Teacher entered
the control path; Teacher kill rules remain unchanged.

## One next command

```bash
.venv/bin/python scripts/m2c/audit_adr0024_phase2_candidate.py --project-root .
```
