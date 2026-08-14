# M2C Phase-2 formal exact-plan integration audit

- Status: **BLOCKED_UNMEASURED_FORMAL_EXACT_PLAN_INTEGRATION**
- Checked HEAD: `eb6656f7ba168b412275dd5adf7e63cd0f7ff993`
- Formal execution eligible: **false**
- Physical execution / training by this audit: **false / false**

## Result

The ADR-0022/ADR-0024 exact-plan envelope, all-phase preflight coordinator,
no-replan executor, and A3 float64 Bullet candidate exist.  The query-only
deployment path also ran, but the frozen home state still has two fail-closed
self-collision rejections.

The A.3 coordinator now has a versioned ADR-0024 deployment authorization
contract. It replaces the rescinded trusted-host signature prerequisite with
byte-bound accepted-ADR/addendum/config, immutable Git/container/runtime
closure, complete configuration, session-audit implementation, and host-local
HMAC verifier bindings. A plan is exposed to the primitive bundle only after
all phase evidence is replayed under that closure. Per-run session receipts and
post-execution host HMAC replay remain mandatory. The V1 signing schema remains
parseable for historical audit only and cannot authorize a new command.

The versioned `FormalPublicObservationV4` transport now independently replays
the approved V4 candidate and association bindings.  It is deliberately not
yet active: `FormalPublicObservationV2` still cannot carry `association_history`, `candidate_payload`, `candidate_payload_sha256`, `declared_target_attribute`, `public_track_associator_revision`.
Consequently the A.1 public candidate digest cannot be independently
recomputed from the **current active** wire.
The separate `FormalExactPlanRuntimeV1` now cross-binds a complete externally
provided A.1--A.4 envelope to V4 RGB-D/candidates, inference response, mapping,
and execution parameters; it runs whole-plan preflight and consumes a prepared
plan before the executor call.  It does not generate waypoints and has no
production provider, so it cannot authorize execution by itself.
The real backend's plan-construction and execution methods remain deliberate
rejection stubs, and there is no production constructor for a bound
`M2CExactPlanPrimitivePlanV1`.

## Blockers

- `FORMAL_PUBLIC_OBSERVATION_V4_NOT_IN_ACTIVE_WIRE_PROTOCOL`
- `PRODUCTION_BOUND_PLAN_PROVIDER_NOT_IMPLEMENTED`
- `FORMAL_BACKEND_EXACT_PLAN_CONSTRUCTION_AND_EXECUTION_STUBS`
- `PLAN_SPECIFIC_A3_PREFLIGHT_AND_EIGHT_SKILL_EXECUTION_UNMEASURED`
- `PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE`
- `TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET`

## Safe implementation order

1. `PLUMB_VERSIONED_V4_OBSERVATION_THROUGH_CAPTURE_AND_INFERENCE_WIRE`
2. `IMPLEMENT_PRODUCTION_BOUND_PLAN_PROVIDER_OVER_V4_AND_MAPPING_INPUTS`
3. `INTEGRATE_FULL_PLAN_PREFLIGHT_BEFORE_ANY_COMMAND`
4. `KEEP_BACKEND_TERMINAL_NO_PHYSICAL_EXECUTION_UNTIL_A3_AND_BINDINGS_PASS`

This is a structural, unmeasured blocker—not a model failure and not a
permission failure. The two active production bindings remain unset; the two
withdrawn compatibility sentinels remain `None`. Teacher and privileged
simulator truth were not used.

Verification: `.venv/bin/pytest -q tests/unit/test_m2c_*.py` ->
**766 passed**, 0 failed.

Next command:

```bash
.venv/bin/pytest -q tests/unit/test_m2c_phase2_formal_exact_plan_integration.py
```
