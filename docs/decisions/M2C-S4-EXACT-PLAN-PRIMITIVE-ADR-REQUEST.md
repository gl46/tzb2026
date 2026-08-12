# M2C S4 exact-plan physical primitive — human ADR request

- Status: **REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR**
- Date: 2026-08-13 (Asia/Shanghai)
- Governing ADR: `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md`
- Scope: bounded M2C Q-B physical execution contract only
- Recommendation: **Option A**
- Training executed under this request: **false**
- Formal SMOKE / Q-B physical evaluation executed under this request:
  **false / false**
- Teacher labels or Teacher runtime components used: **false**
- B0 or safety-gate changes authorized by this request: **none**

This file asks a human to choose a physical execution contract. It is not an
ADR approval, does not amend ADR-0020, and does not unlock training,
deployment, SMOKE, or Q-B evaluation.

## Why a new human decision is required

The current formal protocol can represent an immutable
`ExactExecutionPlanV2`, including ordered phases, world-frame waypoints,
orientations, gripper targets, contact allowlists, per-phase gates, and a
canonical plan SHA-256. Representation is not authorization to execute it.

The frozen derived V4 probe (SHA-256
`6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87`)
does not provide an exact-plan-aware GRASP/REGRASP entry point. Its physical
helper selects yaw candidates and contact centerlines during actuation. An
executor that calls that helper therefore cannot prove that every executed
waypoint, orientation, gripper command, retry, and allowlist was the same plan
that passed pre-execution gates and was hash-bound before the first command.

Locally authored formal hold/grasp/lift/transport/release motions are new
physical behavior. Reusing low-level controller calls or applying a `B0` name
does not make those motions the unchanged frozen B0. No hash-frozen unchanged
B0 action wrapper is currently available to the formal endpoint.

The current backend consequently fails closed:

- every exact-plan construction request is `INVALID` before model-selected
  physical actuation;
- the execution receipt is `NO_PHYSICAL_EXECUTION`, with IK, collision,
  controller, and safety execution gates recorded as `NOT_RUN`;
- no locally authored motion is substituted for the rejected model action;
- no locally authored motion is called or counted as a B0 fallback; and
- the formal chain cannot produce an eligible physical Q-B episode.

This is an interface/governance blocker, not an observed model result. No
training, formal model SMOKE, or formal Q-B physical evaluation has been run
through this blocked path, so this request makes no success-rate claim.

## Current unlock state

All four source-level unlock bindings remain deliberately unset:

- `FORMAL_PHYSICAL_RUNNER_BINDING = None`
- `FORMAL_DEPLOYMENT_CLOSURE_BINDING = None`
- `FROZEN_B0_RUNTIME_WRAPPER_BINDING = None`
- `OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None`

This request must not be cited as evidence for setting any of them. A human
choice below is necessary but is not, by itself, sufficient to unlock an
entry binding.

## Mutually exclusive options

Select exactly one of A, B, or C.

### A — authorize exact-plan-aware model primitives and an unchanged B0 wrapper (recommended)

Issue a human ADR that authorizes a versioned exact-plan-aware physical
primitive bundle for the model-selected chain and, separately, freezes a
wrapper that invokes the unchanged B0 for ADR-0020 section 7.4 fallback.

The two paths must remain distinct:

1. A valid model-selected skill executes only its precomputed, hash-bound
   exact plan and is attributed
   `MODEL_SELECTED_REGISTERED_SKILL`.
2. An invalid mapping or rejected preflight may call only the separately
   frozen unchanged-B0 wrapper, is never model-owned, and is always excluded
   from `pure_model_success_episode`.

The approving ADR must freeze the following model-primitive contract. Blank,
implicit, runtime-selected, or “implementation-defined” fields are not an
approval.

#### A.1 Exact input contract

- exact implementation entry point, source path, source SHA-256, immutable
  commit, transitive dependency manifest, container/image digest, and Isaac,
  robot, controller, and scene asset digests;
- `run_id`, `session_id`, `decision_index`, observation ID, fresh capture
  receipt SHA-256, RGB SHA-256, depth SHA-256, and canonical K=8 public-track
  payload SHA-256;
- signed model inference response SHA-256 and Isaac-side recomputed
  `RuntimeSkillRegistryV2` mapping SHA-256;
- canonical skill, literal public `target_track_id`, registered
  `destination_cell`, and the exact resolved execution-parameter SHA-256;
- the pre-plan robot/controller/scene state that planning is allowed to use,
  including its frame, dimensions, units, timestamp/freshness rule, and
  canonical digest;
- action frame (`world` where registered), position units (metres), angular
  units (radians / normalized `wxyz` quaternion as applicable), controller
  frequency, command dimensions, tolerances, and normalization; and
- an explicit prohibition on Teacher output, evaluator identity, TaskSpec
  recovery fallback, privileged entity/prim identity, perfect pose, injected
  truth, contact truth as policy input, and final task truth as policy input.

The ADR must say which of these inputs may be used by planning, which are
audit-only, and how any missing, stale, non-finite, or hash-mismatched field
fails before actuation. No action mapping may be guessed.

#### A.2 Exact phase and waypoint contract

For every authorized registered action (`GRASP`, `LIFT`, `MOVE`, `PLACE`,
`RELEASE`, `REOBSERVE`, `REASSOCIATE_TARGET`, and `REGRASP`), freeze the exact
ordered phase schema and all action-specific required fields. At minimum each
phase must bind:

- contiguous phase index and unique phase name;
- command kind;
- every Cartesian waypoint in world-frame metres;
- every normalized world-frame `wxyz` orientation;
- each gripper position in metres;
- exact step count, command rate, interpolation rule, convergence tolerance,
  timeout, and permitted retry count;
- allowed robot links, environment paths, and external-contact paths;
- attachment/removal selector semantics and eligible contact allowlist; and
- for public capture/reassociation phases, the capture label or literal public
  track pointer and the freshness transition it consumes.

In particular, GRASP and REGRASP must bind every approach/contact/close/lift/
retreat waypoint, the selected yaw, contact centerline, finger target,
contact allowlist, and any retry sequence **before** the first physical
command. RELEASE/PLACE must bind the open and retreat phases. MOVE/LIFT must
bind the complete transport trajectory. The executor may not select another
yaw or centerline, insert a waypoint, alter a gripper command, replan, retry,
or adapt parameters after the plan digest is computed.

If `REOBSERVE` or `REASSOCIATE_TARGET` remains a logical operation rather than
a physical skill, the approving ADR must define how ADR-0020 section 7.3's
“physically executed” wording applies to it; code may not silently reinterpret
that requirement.

#### A.3 Pre-execution gates

Before the first physical command, every phase must have explicit, immutable
results for:

- inverse kinematics;
- joint position/velocity/effort limits as applicable;
- swept-path collision against the frozen allowlists;
- controller readiness and command-shape/rate compatibility; and
- workspace, contact, attachment, stale-state, and all other existing safety
  gates.

The ADR must freeze the algorithms, configurations, tolerances, fail/timeout
semantics, and evidence schema for these gates. Every required gate must pass
for every phase. A missing or non-passing result makes the complete plan
`INVALID`; no prefix may execute. Existing safety gates may not be weakened,
removed, bypassed, or reclassified.

#### A.4 Exact output and executor contract

- Canonicalize and bind the immutable plan SHA-256 before actuation.
- The executor accepts only that plan and must independently reject any input,
  state, implementation, or dependency digest mismatch.
- Record the executed-plan SHA-256, per-phase command/result/timestamp,
  controller outcome, observed collision/safety result, and terminal or
  partial-failure receipt in the persistent Isaac audit journal.
- A mid-plan failure terminates and publishes partial failure evidence. It may
  not trigger a hidden replan, fixed continuation, alternative model action,
  or replacement skill.
- Final task truth is computed only by finalization/evaluation and never enters
  a policy request or selects an action.
- Formal evidence is valid only when the precomputed plan SHA-256 and executed
  plan SHA-256 are identical and every required physical phase has a real
  receipt from the bound Isaac session.

#### A.5 Unchanged B0 fallback wrapper

The same ADR must identify a separately reviewed wrapper that invokes the
already frozen, unchanged B0 rather than recreating B0 behavior. Freeze:

- wrapper entry point, source path/SHA-256, immutable commit, transitive
  dependencies, container/image digest, and exact underlying B0 source and
  configuration digests;
- permitted trigger set (including invalid pointer, stale track, invalid cell,
  invalid mapping, and preflight rejection) and exact input/output schema;
- unchanged B0 action parameters, retries, controllers, gates, success
  definition, and failure behavior; and
- receipt attribution that is unambiguously B0, never model-owned, and always
  disqualifies strict-pure success.

If the wrapper cannot prove that it invokes the unchanged frozen B0, fallback
remains unavailable and must produce `NO_PHYSICAL_EXECUTION`. A locally
authored “safe hold” is not an acceptable substitute unless separately
authorized as a new primitive, and it still would not be unchanged B0.

Trade-off: Option A adds the most implementation and review work, but it is the
only listed option that can satisfy both exact-plan provenance and the current
ADR-0020 section 7.4 fallback requirement without weakening B0 or a safety
gate.

### B — authorize model physical primitives; INVALID is terminal no-action

Issue a human ADR for the exact-plan-aware model primitive described in
A.1–A.4, but do not authorize or freeze a B0 fallback wrapper. An invalid
mapping or rejected preflight remains terminal `NO_PHYSICAL_EXECUTION`; it
does not execute a local hold, substitute action, or B0-like motion.

This option **does not satisfy the currently accepted ADR-0020 section 7.4**,
which requires `INVALID mapping -> B0 fallback`. Selecting B therefore also
requires an explicit human amendment or superseding ADR that changes section
7.4 before any formal Q-B evaluation. A code change, test fixture, or this
request cannot make that governance change. Existing evidence may not be
relabelled as compliant after the fact.

Trade-off: this is smaller than A and remains physically fail-closed on
invalid actions, but changes the accepted experimental contract and removes
the requested unchanged-B0 fallback behavior.

### C — do not authorize a new physical primitive; execute D2 / stay COARSE_ONLY

Do not authorize either an exact-plan-aware physical primitive or a B0 runtime
wrapper for M2C Q-B. Keep all four unlock bindings `None`, maintain the current
`INVALID -> NO_PHYSICAL_EXECUTION` behavior, execute the D2 downgrade, and
retain `GO_QRM_COARSE_ONLY`.

The formal Q-B model-owned physical hypothesis then remains unmeasured. The
downgrade must not be reported as a trained-model failure because no training
or formal Q-B physical evaluation was executed through this blocked path.
Permitted follow-up is limited to audit/report work or work separately
authorized by the existing goal.

Trade-off: this introduces no new physical semantics and preserves the current
fail-closed boundary, but does not test the bounded model-owned recovery chain.

## Recommendation

Recommend **A**, conditional on a complete human ADR and subsequent independent
implementation review. It preserves ADR-0020 section 7.4, keeps the model path
and B0 fallback path attributable and separate, and makes preflight-to-
execution identity falsifiable through a canonical plan digest. It does not
authorize weakening B0, changing safety gates, or treating a local primitive
as unchanged B0.

If the required unchanged-B0 wrapper cannot be produced and verified, the
honest choices are B with an explicit section 7.4 amendment or C. That missing
wrapper must not be papered over by a name, receipt enum, no-op, or locally
authored controller motion.

## Non-negotiable boundaries for any option

- The world-model remains the mandatory prediction-and-selection path; a
  state machine or safety component may not choose the recovery chain.
- No Teacher soft label, Teacher inference, or Teacher control-stack component
  is permitted. Any such use kills the affected run and must be reported.
- Privileged simulator truth, evaluator identity, public-role ground truth,
  entity/prim identity, and final task truth may not enter test-time policy
  input.
- B0 sources, parameters, retries, gates, and success definitions remain
  unchanged unless a later explicit human ADR says otherwise. This request
  does not say otherwise.
- Schema, stale-track, frame/unit, IK, joint-limit, collision, controller, and
  safety gates remain fail-closed and may not be relaxed.
- Every decision cycle remains one model selection followed by at most its one
  registered physical skill and then a fresh public RGB-D capture. No runner
  expected-chain selection, fixed continuation, or TaskSpec recovery fallback
  is allowed.
- Scripted, fixture, mock, dry-run, and contract-test evidence is never
  model-owned physical evidence.
- No old checkpoint, receipt, journal, report, or episode may be backfilled or
  reinterpreted under a newly approved contract.

## Human approval fields

All applicable fields must be completed in a separately accepted ADR. Leaving
a required field blank means “not approved.”

- Selected mutually exclusive option: `A | B | C`
- ADR ID and path (required for A or B):
- ADR status (`Accepted` required for A or B):
- Approver name and role:
- Approval timestamp and timezone:
- Approval scope / permitted stages and environments:
- Exact primitive bundle revision (A or B):
- Primitive entry point, source path, SHA-256, and immutable commit (A or B):
- Transitive dependency manifest SHA-256 (A or B):
- Container/image digest and Isaac/runtime versions (A or B):
- Exact input schema path/revision/SHA-256 (A or B):
- Exact plan/phase schema path/revision/SHA-256 (A or B):
- Exact output/receipt schema path/revision/SHA-256 (A or B):
- Action-by-action waypoint/orientation/gripper/retry contract (A or B):
- Frame/unit/dimension/frequency/normalization contract (A or B):
- Per-phase IK/limits/swept-collision/controller/safety gate bundle and hashes
  (A or B):
- Executor no-adaptation/no-replan attestation (A or B):
- Unchanged B0 wrapper entry point, path, SHA-256, immutable commit, dependency
  manifest, and container digest (required for A):
- Underlying frozen B0 sources/configurations and verified SHA-256 list
  (required for A):
- ADR-0020 section 7.4 disposition:
  `UNCHANGED_AND_SATISFIED_BY_A | EXPLICITLY_AMENDED_BY_B | NOT_APPLICABLE_C`
- Teacher use attestation: `NONE`
- Privileged-truth policy-input attestation: `NONE`
- B0 modification authorized: `NO`
- Safety-gate weakening authorized: `NO`
- Revocation/expiry conditions:
- Independent safety reviewer and timestamp (A or B):
- Independent provenance/deployment reviewer and timestamp (A or B):

Even after A or B is accepted, each unlock binding remains `None` until its
own reviewed implementation, real endpoint startup, dependency closure,
offline authentication verification, and exact binding evidence exist. The
entry gate—not this request—makes that later determination.

## Task report

- Changed: only
  `docs/decisions/M2C-S4-EXACT-PLAN-PRIMITIVE-ADR-REQUEST.md`.
- Tests: documentation readback and untracked-file diff whitespace check; no
  code or physical test is claimed by this document.
- Failures: every current exact-plan construction is intentionally `INVALID`
  and returns `NO_PHYSICAL_EXECUTION`; this is a governance/interface blocker,
  not a model evaluation result.
- Blockers: no accepted exact-plan primitive ADR; no approved exact physical
  executor; no hash-frozen unchanged-B0 runtime wrapper; all four unlock
  bindings are `None`; no formal deployment/evaluation authorization.
- Next command:
  `sed -n '1,360p' docs/decisions/M2C-S4-EXACT-PLAN-PRIMITIVE-ADR-REQUEST.md`
  for human review and selection of exactly one option.
