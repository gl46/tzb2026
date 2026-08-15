# ADR-0022 Phase-2 binding addendum — source unlock for S4 training

- Status: **Accepted Phase-2 binding addendum**
- Date: **2026-08-15 (Asia/Shanghai)**
- Authority: ADR-0022 Phase-2 steps 2–4, as amended by accepted ADR-0024
- Scope: the two active source bindings required before S4 training
- Physical Q-B evidence produced by this addendum: **no**
- Teacher used: **no**
- Privileged simulator truth used as policy input: **no**

This is the binding addendum required by ADR-0022.  It records the exact
source-level primitive/runtime contract that must be frozen before the S4
world-model trainer is allowed to run.  It does not claim a successful
physical episode and does not replace the later per-run deployment, asset,
wire, safety, and execution receipts required by the S4 entry gate.

The immutable implementation commit cannot be embedded in the commit that
introduces this file without a Git self-reference.  The binding application
therefore uses the repository's reviewed two-phase closure protocol:

1. this addendum is committed together with the already tested implementation;
2. a create-only closure replays that exact commit and its complete Git tree;
3. the descendant binding-only commit records the resulting commit, image and
   manifest digest in `configs/m2c_s4_unlock_bindings.json` and applies the two
   active constants in `s4_entry_gate.py`.

The machine config and closure receipt must prove that the addendum-introduction
commit is an ancestor of the binding commit and that every implementation byte
read by the trainer/formal source tree equals that frozen Git tree.

## Active and withdrawn bindings

The binding commit shall set exactly:

- `FORMAL_PHYSICAL_RUNNER_BINDING` to the repo-relative path and SHA-256 of
  `scripts/m2c/run_formal_model_owned_chain_v4.py` at the implementation
  commit;
- `FORMAL_DEPLOYMENT_CLOSURE_BINDING` to the implementation commit, the exact
  Isaac 6 image ID
  `sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9`,
  and the complete Git-tree transitive-manifest file SHA-256.

Accepted ADR-0024 section 2/4 withdraws the other two prerequisites.  They
must remain literal `None`:

- `FROZEN_B0_RUNTIME_WRAPPER_BINDING = None`;
- `OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None`.

No no-action terminal may be relabelled as B0 fallback.  The frozen M2B B0
remains byte-identical and is used only as the independent comparison arm.

## A.1 exact-plan primitive contract

The source closure includes the versioned `M2CExactPlanPrimitiveBundleV1`,
the bound-plan provider, the eight-skill synthesis backend, the per-decision
bundle factory, the real-Isaac component graph, the frozen-probe executor and
all their tests/configuration sources.  The contract smoke must prove before
binding application:

- exact plan-digest identity before every phase;
- every phase is preflighted before the first executor call;
- phase and gate results are immutable;
- no runtime replan, inserted command, changed yaw/centreline, retry,
  replacement skill, local hold or B0 continuation;
- a mid-plan failure terminates the plan and later phases do not execute;
- invalid pointer/mapping/cell, stale track or failed preflight becomes
  terminal `NO_PHYSICAL_EXECUTION` and remains a failed denominator episode.

The non-motion `REOBSERVE` and `REASSOCIATE_TARGET` operations consume a fresh
session-bound public RGB-D capture/association transition.  They do not move
the robot and cannot use entity/prim identity, Teacher output or outcome truth.

## A.3 delegated numeric contract

Under ADR-0024 section 3, the following exact values are accepted for the
source-bound preflight and are replayed by
`configs/m2c_adr0024_phase2_binding_candidate.json`:

- Bullet 3.24 scalar ABI: `float64`, `BT_USE_DOUBLE_PRECISION`, no fast-math;
- decoded-STL convex-hull construction tolerance: `1e-7 m`;
- outward-only post-construction padding: `0.002 m`;
- shipped Bullet margins retained per concrete shape (governed maxima:
  `0.0055074 m` box, `0.008 m` cylinder, `0.04 m` convex hull);
- allowed penetration: `0.0 m`;
- contact rejection threshold: `0.001 m`;
- TOI interval: closed `[0, 1]`, rejection-biased comparison tolerance `1e-7`;
- native maximum CCD iterations: `64`; exhaustion rejects;
- subdivision cap: `4096`, using every child maximum angular-motion radius
  and the smallest conservative pair radius; ambiguity/cap exhaustion rejects;
- query timeout: `5,000,000,000 ns`.

Every decoded STL vertex is retained in the conservative hull.  Complete
continuous robot self-collision and robot/environment child pairs are checked;
unknown, concave, malformed, non-finite or incompletely expanded geometry
rejects.  ADR-0025 permits exactly the two enumerated start-state ACM pairs
recorded in `configs/m2c_a3_acm_adr0025_v1.json`; no wildcard, margin, padding,
hull or threshold change is allowed.

The query-only native-load/static-home-state smoke is supporting contract
evidence, not physical success: 74/74 governed child-pair requests were clear
with zero target writes, simulation steps or scene mutations.  Every actual
bound plan must still produce its own complete preflight receipts before the
first command.

## Source-closure and contract-smoke requirements

The binding application must provide all of the following:

- a create-only `M2CPhase2SourceBindingClosureReceiptV1`;
- a `FormalTransitiveImportClosureManifestV1` containing every regular tracked
  file in the implementation commit, with exact Git mode and SHA-256 replay;
- the fixed Isaac image ID above;
- exact current and committed bytes for the formal V4 runner;
- green contract tests for the primitive bundle, all-phase preflight,
  mid-plan termination, terminal-no-action policy, source-closure replay and
  ADR-0026 decision-level loader/trainer gate;
- B0/safety/IK/collision/controller/schema and Teacher/truth invariants
  unchanged.

The closure is intentionally source-level and precedes model training.  The
trained Qwen adapter, selected S4 scene assets, host audits and per-run physical
receipts cannot be included before they exist.  They remain mandatory inputs
to the later formal Q-B evidence verifier; this addendum does not waive them.

## Authorization boundary

After the exact addendum commit passes the create-only source closure and the
offline contract smoke, ADR-0022 step 4 authorizes the descendant binding-only
commit to set the two active bindings above.  That commit authorizes the
no-Teacher S4 training entry to run.  It does **not** by itself authorize a
formal Q-B success claim, set `pure_model_success_episodes`, or make an
unbound HTTP backend factory executable.

Before formal Q-B execution, the selected trained bundle, exact scene/SDF,
runtime assets, endpoint factory, model/Isaac host audits, challenge receipt,
plan-specific A.3 preflight and physical execution receipts must still satisfy
the versioned S4 entry evidence contract.  Missing evidence remains
`BLOCKED_UNMEASURED`, never measured zero.

The 2026-08-20 bundle-smoke checkpoint remains unchanged.
