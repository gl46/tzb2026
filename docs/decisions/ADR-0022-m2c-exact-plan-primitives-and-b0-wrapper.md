# ADR-0022: Exact-plan physical primitives and unchanged-B0 fallback wrapper

- Status: Accepted for the bounded M2C Q-B experiment (human decision);
  **execution unlock requires the Phase-2 binding addendum below**
- Date: 2026-08-13 (Asia/Shanghai)
- Selected option: **A** of
  `docs/decisions/M2C-S4-EXACT-PLAN-PRIMITIVE-ADR-REQUEST.md`
- Parent: `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md` (§7.4 fallback
  requirement is preserved, not amended)

## Decision

Authorize a versioned exact-plan-aware physical primitive bundle for the
model-selected chain, and a separately frozen wrapper that invokes the
unchanged B0 for §7.4 fallback. The two paths stay distinct and separately
attributed:

1. A valid model-selected skill executes only its precomputed, hash-bound
   `ExactExecutionPlanV2`; attribution `MODEL_SELECTED_REGISTERED_SKILL`.
2. An invalid mapping or rejected preflight may call only the frozen
   unchanged-B0 wrapper; attribution is B0, never model-owned, always
   excluded from `pure_model_success_episode`.

Names: primitive bundle **`M2CExactPlanPrimitiveBundleV1`**; fallback wrapper
**`FrozenB0FallbackWrapperV1`**; plan schema `ExactExecutionPlanV2` (already
representable in the formal protocol).

## Adopted contract

Sections A.1–A.5 of the request are adopted **in full and verbatim** as the
frozen contract for the bundle and wrapper. In particular:

- **A.1 inputs**: every listed identity/digest/state field is mandatory in
  the plan record. Planning may use: the fresh capture receipt and its
  RGB/depth digests, the canonical public-track candidate payload
  (`PublicTrackCandidateV3` per ADR-0021), the signed model inference
  response, the recomputed `RuntimeSkillRegistryV2` mapping, the resolved
  execution parameters, and the pre-plan robot/controller/scene state named
  in the record. All remaining A.1 fields (source/commit/container/asset
  digests, session identifiers) are audit-only. Any missing, stale,
  non-finite, or hash-mismatched field fails the whole plan before actuation.
  The A.1 prohibition list (Teacher output, evaluator identity, TaskSpec
  recovery fallback, privileged identity/pose/contact/success truth) applies
  to both planning and audit inputs of the model path.
- **A.2 phases**: every registered action binds its complete ordered phase
  schema before the first command; GRASP/REGRASP bind every
  approach/contact/close/lift/retreat waypoint, the selected yaw, contact
  centerline, finger targets, contact allowlist, and the full retry sequence
  in the plan itself. The executor may not select, insert, alter, replan,
  retry, or adapt anything after the plan digest is computed.
- **A.3 gates**: IK, limits, swept-path collision against frozen allowlists,
  controller readiness/shape/rate, workspace/contact/attachment/stale-state
  and all existing safety gates produce explicit immutable per-phase results
  before the first command; any missing or failing result invalidates the
  complete plan and no prefix executes. Algorithms, configurations,
  tolerances, and fail/timeout semantics are those already frozen in the
  formal protocol sources at the binding commit; the binding addendum pins
  their digests. No gate may be weakened, removed, bypassed, or reclassified.
- **A.4 executor**: canonical plan SHA-256 bound before actuation; executor
  independently rejects any digest mismatch; per-phase receipts land in the
  persistent Isaac audit journal; a mid-plan failure terminates with partial
  evidence and may not trigger a hidden replan, fixed continuation,
  alternative model action, or replacement skill; final task truth never
  enters a policy request. Evidence is valid only when precomputed and
  executed plan SHA-256 are identical and every physical phase has a real
  session-bound receipt.
- **A.5 wrapper**: `FrozenB0FallbackWrapperV1` must invoke the already frozen
  unchanged B0 (probe SHA-256
  `1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094`) with
  unchanged parameters, retries, controllers, gates, success definition, and
  failure behavior. Trigger set: invalid pointer, stale track, invalid cell,
  invalid mapping, preflight rejection — exactly the ADR-0020 §7.4 set. If
  the wrapper cannot prove it invokes the unchanged frozen B0, fallback stays
  unavailable and the receipt is `NO_PHYSICAL_EXECUTION`; a locally authored
  "safe hold" is not a substitute and is not authorized.

## Non-motion skills

`REOBSERVE` and `REASSOCIATE_TARGET` are defined as **physically executed**
when, respectively: (a) a real fresh Isaac capture receipt (session-bound,
RGB SHA-256 + depth SHA-256) is produced and journaled; (b) a real
association computation over that fresh capture is journaled with its input
digests and resulting track binding. Each consumes one model decision cycle
and one freshness transition. No robot motion is required for either. This is
the explicit ADR-0020 §7.3 interpretation the request demands; code may not
reinterpret it further.

## Phase-2 binding addendum (necessary to unlock)

This human choice is necessary but not sufficient. Unlock proceeds only as:

1. Codex authors the bundle and wrapper on the M2C branch.
2. Codex commits a binding addendum
   (`docs/decisions/ADR-0022-BINDING-ADDENDUM.md` plus machine-readable
   `configs/m2c_s4_unlock_bindings.json`) pinning every A.1/A.5 digest:
   entry points, source paths and SHA-256, immutable commit, transitive
   dependency manifest, container/image digest, and Isaac/robot/controller/
   scene asset digests, for both the bundle and the wrapper.
3. An offline contract smoke proves: plan-digest identity checking, per-phase
   gate result immutability, mid-plan-failure termination without replan,
   wrapper-to-frozen-B0 digest identity, and both attribution labels.
4. Only after 2 and 3 may the four source-level bindings
   (`FORMAL_PHYSICAL_RUNNER_BINDING`, `FORMAL_DEPLOYMENT_CLOSURE_BINDING`,
   `FROZEN_B0_RUNTIME_WRAPPER_BINDING`,
   `OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING`) be set, in one commit that
   references this ADR and the addendum.

A failure at any step leaves the bindings `None` and the path fail-closed;
the failure is reported as a blocker, never worked around.

## Governance scope

This ADR does not amend ADR-0020 §7.4, does not weaken B0 or any gate,
creates no new skill label, keeps Flow disabled, and does not retire the
mandatory world-model mainline. Teachers remain unused (Nano `CANDIDATE`,
BWM `CANDIDATE_LICENSE_PENDING`, Super `PARKED`); any Teacher label or
runtime component kills the affected run. Privileged simulator truth never
enters a policy request. Existing evidence keeps its original semantics.

## Approval fields

- Selected option: **A**
- Primitive bundle / wrapper / plan schema names:
  **`M2CExactPlanPrimitiveBundleV1` / `FrozenB0FallbackWrapperV1` /
  `ExactExecutionPlanV2`**
- §7.4 amendment: **none** (preserved)
- Non-motion skill interpretation: as defined above
- Digest binding: deferred to the Phase-2 addendum; bindings stay `None`
  until addendum + contract smoke pass
- Does this approval alone unlock training/SMOKE/Q-B evaluation?: **no**
- Approver/date: project owner (gl46), 2026-08-13
