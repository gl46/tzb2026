# M2C S4 active-session B0 fallback — human ADR request

- Status: **REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR**
- Date: 2026-08-13 (Asia/Shanghai)
- Parent decisions:
  `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md` and
  `ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md`
- Trigger: implementation review after ADR-0022 Option A was accepted
- Training / formal SMOKE / Q-B evaluation executed under this request:
  **false / false / false**
- Teacher used: **false**
- Privileged simulator truth used as policy input: **false**
- B0 or gate change authorized by this request: **none**

This request records a newly proven interface mismatch. It does not approve a
fallback implementation, amend ADR-0020 or ADR-0022, set an entry binding, or
authorize training or physical evaluation.

## Newly proven blocker

ADR-0020 section 7.4 requires an invalid pointer, stale track, invalid cell, or
invalid mapping to execute B0 fallback and exclude the episode from strict
pure-model success. ADR-0022 Option A preserves that requirement and permits
only a wrapper that invokes the already frozen unchanged B0.

The frozen B0 inventory remains byte-identical to M2B. In particular:

- `scripts/isaac_m1b_actuation_probe.py` SHA-256 is
  `1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094`;
- `scripts/m2b/run_physical_failure_smoke.py` SHA-256 is
  `7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865`;
- `configs/m2c_b0_freeze.json` SHA-256 is
  `4bec9104be849dfd8d71b32b537eb2b5d70ea4d8560b4bdd65b1d1019d3e8d04`.

Static byte/AST review proves those frozen files expose no callable that can
accept the current live formal Isaac session and run the unchanged B0 from
that already-evolved physical state. The frozen runner owns a separate
process, constructs another SimulationApp/scene, and executes a complete
standalone attempt. Re-running it with the same scene seed is another episode,
not continuation of the session that produced the invalid model decision.

Importing frozen low-level helpers and locally reconstructing a B0 sequence is
also invalid: the new sequence would choose orchestration, parameters, retries,
terminal behavior, and state transfer in new source bytes. A digest label or
`B0_FALLBACK` enum cannot turn that implementation into the unchanged B0.

Consequently, the current honest behavior remains
`NO_PHYSICAL_EXECUTION`; the four entry bindings remain `None`. This is an
interface/governance blocker, not a measured model failure and not
`pure_model_success_episodes = 0`.

## Mutually exclusive options

Select exactly one of A, B, or C.

### A — authorize a versioned active-session B0 implementation

Authorize a new `FrozenB0ActiveSessionV2` implementation that executes in the
same live formal Isaac session. This option must explicitly amend the current
"B0 implementation is byte-identical to M2B" boundary; the new implementation
may not be described as the unchanged SHA-256 `1e32...` B0 merely because its
constants or low-level helpers originated there.

Before any physical use, a Phase-2 addendum must freeze and independently
review:

- the complete extracted state machine and every transition;
- exact parameters, retries, controller commands, gates, success/failure
  definitions, timeouts, and terminal behavior against the M2B B0;
- same-session input/output state, frame, units, dimensions, frequency, and
  freshness contracts;
- source, immutable commit, container, dependency and asset digests;
- a differential equivalence campaign on frozen non-evaluation keys; and
- receipt attribution as B0-only, always excluding strict-pure success.

Any semantic mismatch remains a blocker. This option is the largest change
and requires explicit human acceptance that source identity is no longer the
Goal's original B0 invariant.

### B — amend invalid mapping to terminal no-action (recommended)

Amend ADR-0020 section 7.4 and ADR-0022 Option A only as follows:

```text
invalid pointer / stale track / invalid cell / invalid mapping /
preflight rejection -> terminal NO_PHYSICAL_EXECUTION
```

The episode remains a failure, is retained in the evaluation denominator, and
is always excluded from strict-pure success. No local hold, substitute action,
new B0, cross-scene runner, retry, or fixed continuation executes. The existing
M2B B0 stays byte-identical and is still the independent B0 comparison arm.

This option needs a versioned formal receipt/mapping attribution
`NO_PHYSICAL_EXECUTION`, a terminal-failure journal, and a revised entry-gate
contract. It may not relabel no-action as `B0_FALLBACK`. It changes no model
skill, safety threshold, mapping acceptance rule, or B0 comparison result.

This is recommended because it preserves the strongest safety and B0
integrity boundaries while allowing valid model-selected exact plans to be
tested. It does, however, explicitly supersede the existing section 7.4
fallback requirement and therefore cannot be selected by code.

### C — retain Option A and keep S4 blocked

Keep ADR-0020 section 7.4 and ADR-0022 Option A exactly as written. Do not
author a new B0 implementation and do not permit terminal no-action in place
of B0 fallback. All four bindings remain `None`; S4 training/formal evaluation
remain blocked, and deadline routing must report **blocked/unmeasured**, not a
measured zero or D2 model conclusion.

## Boundaries under every option

- B0 may not be weakened to manufacture model headroom.
- Existing safety, IK, collision, controller, schema, stale-state and mapping
  gates may not be relaxed or reclassified.
- The Qwen world model remains the prediction-and-selection mainline.
- Teacher labels/runtime remain forbidden; Nano stays `CANDIDATE`, BWM stays
  `CANDIDATE_LICENSE_PENDING`, and Super stays `PARKED`. Any Teacher use kills
  the affected run.
- Entity/prim identity, perfect pose/contact, injected-failure truth and final
  task truth remain unavailable as test-time policy input.
- Existing evidence keeps its original semantics; no backfill or relabel is
  permitted.
- ADR-0022 A.3 non-actuating exact-plan preflight may continue to be
  implemented offline, but no physical command or binding is authorized by
  this request.

## Human approval fields

- Selected option: `A` / `B` / `C`
- ADR-0020 section 7.4 disposition: `ACTIVE_SESSION_B0_V2` /
  `TERMINAL_NO_PHYSICAL_EXECUTION` / `UNCHANGED_AND_BLOCKED`
- Is the M2B byte-identical B0 invariant amended?: `YES` only for A; `NO` for
  B or C
- Is a no-action receipt allowed to claim B0 attribution?: **NO**
- Does approval alone set any Phase-2 binding?: **NO**
- Does approval alone authorize training or Q-B evaluation?: **NO**
- Approver/date: pending human decision

## Current disposition

No option is selected. `FrozenB0FallbackWrapperV1` must keep returning
`NO_PHYSICAL_EXECUTION` for the active formal session, the Phase-2 readiness
gate must remain `BLOCKED`, and all four source-level bindings must remain
literal `None`.
