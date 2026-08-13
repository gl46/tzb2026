# M2C Phase-2 formal exact-plan integration audit

- Status: **BLOCKED_UNMEASURED_FORMAL_EXACT_PLAN_INTEGRATION**
- Checked HEAD: `1daf6c1cba033a7d45893dcf3d6225dacd517f86`
- Formal execution eligible: **false**
- Physical execution / training by this audit: **false / false**

## Result

The ADR-0022/ADR-0024 exact-plan envelope, all-phase preflight coordinator,
no-replan executor, and A3 float64 Bullet candidate exist.  The query-only
deployment path also ran, but the frozen home state still has two fail-closed
self-collision rejections.

The versioned `FormalPublicObservationV4` transport now independently replays
the approved V4 candidate and association bindings.  It is deliberately not
yet active: `FormalPublicObservationV2` still cannot carry `association_history`, `candidate_payload`, `candidate_payload_sha256`, `declared_target_attribute`, `public_track_associator_revision`.
Consequently the A.1 public candidate digest cannot be independently
recomputed from the **current active** wire.
The real backend's plan-construction and execution methods remain deliberate
rejection stubs, and there is no production constructor for a bound
`M2CExactPlanPrimitivePlanV1`.

## Blockers

- `FORMAL_PUBLIC_OBSERVATION_V4_NOT_IN_ACTIVE_WIRE_PROTOCOL`
- `FORMAL_BOUND_PLAN_PROVIDER_NOT_IMPLEMENTED`
- `FORMAL_BACKEND_EXACT_PLAN_CONSTRUCTION_AND_EXECUTION_STUBS`
- `A3_STATIC_HOME_SELF_COLLISION_PREFLIGHT_REJECTED`
- `FOUR_PRODUCTION_BINDINGS_UNSET`

## Safe implementation order

1. `PLUMB_VERSIONED_V4_OBSERVATION_THROUGH_CAPTURE_AND_INFERENCE_WIRE`
2. `ADD_BOUND_PLAN_PROVIDER_OVER_RECOMPUTABLE_V4_AND_MAPPING_INPUTS`
3. `INTEGRATE_FULL_PLAN_PREFLIGHT_BEFORE_ANY_COMMAND`
4. `KEEP_BACKEND_TERMINAL_NO_PHYSICAL_EXECUTION_UNTIL_A3_AND_BINDINGS_PASS`

This is a structural, unmeasured blocker—not a model failure and not a
permission failure.  The four production bindings remain unset.  Teacher and
privileged simulator truth were not used.

Verification: `.venv/bin/pytest -q tests/unit/test_m2c_*.py` ->
**703 passed**, 0 failed.

Next command:

```bash
.venv/bin/pytest -q tests/unit/test_m2c_phase2_formal_exact_plan_integration.py
```
