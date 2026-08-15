# M2C Phase-2 formal exact-plan integration audit

- Status: **BLOCKED_UNMEASURED_FORMAL_EXACT_PLAN_INTEGRATION**
- Checked HEAD: `01883be7f976810b2850c43fb956d764e8df496f`
- Formal execution eligible: **false**
- Physical execution / training by this audit: **false / false**

## Result

The ADR-0022/ADR-0024 exact-plan envelope, all-phase preflight coordinator,
no-replan executor, and A3 float64 Bullet implementation exist.  The
query-only native ABI was loaded in the frozen Isaac 6 image without loading
Kit/Isaac; the corrected frozen home state returned 74/74 governed child-pair
queries CLEAR with zero query failures.  This is a static-start smoke, not
plan-specific execution evidence.

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

The V4 host-local verifier now replays the exact Qwen and Isaac audit
lifecycles, every HMAC envelope, the one-shot challenge receipt, and variable
terminal counts for one through eight decisions. Its receipts contain no SSH
signature, trust root, or signer principal. No real node2/labserver receipts
exist yet, so this implementation does not remove the session/startup evidence
blocker or authorize a production binding.

The coordinator does not generate waypoints.  A single-use, deployment-bound
provider now consumes one query-only active-session state receipt and replays
the complete request/observation/mapping/plan/source closure before exposing a
plan.  The persistent-scene owner core now binds the public failure boundary,
eight fresh capture prefixes, and terminal public evaluation, but its real raw
RGB-D/proprioception source and formal HTTP factory are still unbound.  The
real Isaac synthesis backend is also absent and plan-specific A3 evidence for
all eight skills remains unmeasured. The ADR-0024 V2 readiness verifier is complete but has no real
evidence index to authorize an addendum. The S4 entry gate now preserves the
historical V2 path while independently replaying a strict V3 envelope backed
by that same formal V4 Phase-2 evidence index.

## Blockers

- `REAL_BOUND_PLAN_SYNTHESIS_BACKEND_NOT_BOUND`
- `REAL_ISAAC_RAW_PUBLIC_FRAME_SOURCE_NOT_BOUND`
- `REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND`
- `PLAN_SPECIFIC_A3_PREFLIGHT_AND_EIGHT_SKILL_EXECUTION_UNMEASURED`

## Safe implementation order

1. `BIND_REVIEWED_PRODUCTION_ASSOCIATION_AND_ATTRIBUTE_DEPLOYMENT`
2. `BIND_REAL_QUERY_ONLY_PLAN_SYNTHESIS_BACKEND`
3. `BIND_REAL_ISAAC_RAW_PUBLIC_FRAME_SOURCE`
4. `BIND_REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY`
5. `REPLAY_PLAN_SPECIFIC_A3_PREFLIGHT_FOR_ALL_EIGHT_SKILLS`
6. `COLLECT_REAL_PHASE2_V2_EVIDENCE_INDEX`

This is a structural, unmeasured formal-Q-B blocker—not a model failure. The
two source bindings are applied for no-Teacher S4 training; the two withdrawn
compatibility sentinels remain `None`. Teacher and privileged simulator truth
were not used.

Verification: `PYTHONPATH=src:scripts .venv/bin/pytest -q tests/unit/test_m2c_phase2_a3_native_load_smoke.py tests/unit/test_m2c_formal_isaac_persistent_scene_v4.py tests/unit/test_m2c_formal_isaac_episode_io_v4.py tests/unit/test_m2c_formal_isaac_backend_v4.py` ->
**19 passed**, 0 failed.

Next command:

```bash
.venv/bin/pytest -q tests/unit/test_m2c_phase2_formal_exact_plan_integration.py
```
