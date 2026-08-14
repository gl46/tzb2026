# M2C Phase-2 formal exact-plan integration audit

- Status: **BLOCKED_UNMEASURED_FORMAL_EXACT_PLAN_INTEGRATION**
- Checked HEAD: `79571b84d7e33b52779030ce56e6e18022c0cd3f`
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

The active `FormalPublicObservationV4` transport independently replays the
approved V4 association history, role-ranked K=8 candidates, declared public
attribute, RGB-D bytes, and public proprioception journal.  The V4 endpoint
state machine and backend coordinator now carry that observation through
mapping, all-phase preflight, single-use exact-plan execution, and final public
evaluation.  INVALID mappings and explicitly typed non-actuating gate
rejections terminate as `NO_PHYSICAL_EXECUTION`; unknown failures are not
laundered into experimental outcomes.

The V4 host contract orders only authenticated capture, inference, execution,
and finalization calls. It publishes a replayable terminal evidence envelope,
never selects an expected skill, and never substitutes B0. No real V4 Isaac
HTTP service is deployment-bound, so this remains a contract result rather
than formal physical evidence.

The coordinator does not generate waypoints.  A single-use, deployment-bound
provider now consumes one query-only active-session state receipt and replays
the complete request/observation/mapping/plan/source closure before exposing a
plan.  Its real Isaac synthesis backend and lifecycle/capture deployment are
still absent, plan-specific A3 evidence for all eight skills remains
unmeasured, and the Phase-2 readiness verifier has not completed its ADR-0024
migration.

## Blockers

- `REAL_BOUND_PLAN_SYNTHESIS_BACKEND_NOT_BOUND`
- `REAL_ISAAC_EPISODE_LIFECYCLE_AND_CAPTURE_SOURCE_NOT_BOUND`
- `REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND`
- `PLAN_SPECIFIC_A3_PREFLIGHT_AND_EIGHT_SKILL_EXECUTION_UNMEASURED`
- `PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE`
- `TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET`

## Safe implementation order

1. `BIND_REAL_QUERY_ONLY_PLAN_SYNTHESIS_BACKEND`
2. `BIND_REAL_ISAAC_EPISODE_LIFECYCLE_AND_PUBLIC_CAPTURE_SOURCE`
3. `BIND_REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY`
4. `REPLAY_PLAN_SPECIFIC_A3_PREFLIGHT_FOR_ALL_EIGHT_SKILLS`
5. `MIGRATE_PHASE2_READINESS_TO_ADR0024_AND_SET_ONLY_TWO_ACTIVE_BINDINGS`

This is a structural, unmeasured blocker—not a model failure and not a
permission failure. The two active production bindings remain unset; the two
withdrawn compatibility sentinels remain `None`. Teacher and privileged
simulator truth were not used.

Verification: `.venv/bin/pytest -q tests/unit/test_m2c_*.py` ->
**803 passed**, 0 failed.

Next command:

```bash
.venv/bin/pytest -q tests/unit/test_m2c_phase2_formal_exact_plan_integration.py
```
