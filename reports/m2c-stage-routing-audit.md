# M2C stage-routing audit

- Status: **PASS_FAIL_CLOSED_IN_PROGRESS**
- Checked implementation commit: `09a8bb03172e7544f220ace2263ad4a5b0c88ee2`
- Current route: `S4_IN_PROGRESS_UNMEASURED`
- Q-A: `PASSED`; Q-B: `UNMEASURED`
- `pure_model_success_episodes`: `null`, not zero
- D1 / D2: `false` / `false`
- Goal complete: `false`; system verdict: `EVIDENCE_PENDING`

The status reducer now treats missing Q-B evaluation, zero eligible training rows,
and a measured zero as three distinct states. D2 is possible only after the frozen
8/26 checkpoint and only after strict terminal replay produced a measured zero.
Legal D1 routes skip S3–S5 but still require S6 and S7. Missing evidence at a
deadline remains `BLOCKED_UNMEASURED`; it is never rewritten as a negative model
result.

## Current evidence

- S4 TRAIN collection: `BLOCKED_ZERO_ELIGIBLE_TRAIN_SAMPLES`.
- S4 formal entry: `BLOCKED_FORMAL_Q_B_EVALUATION`.
- Training/model rollout/formal Q-B evaluation: `false` / `false` / `false`.
- Teacher use and privileged policy input: both `false`.
- Nano/BWM/Super remain `CANDIDATE` / `CANDIDATE_LICENSE_PENDING` / `PARKED`.

S2 status now recomputes the V4 report's three B0 per-key failures, strict
existence proof, and local frozen source hashes instead of trusting only top-level
booleans. The remote 167-file Isaac evidence tree is not mirrored in this
repository, so this audit does not claim a local raw-byte replay of that tree.

## Verification

- Focused stage/status tests: **26 passed**.
- Cross-stage routing/S2/S5/S6/freeze tests: **78 passed**.
- Full repository suite: **762 passed**.
- `ruff check .`: **PASS**.
- Changed-file `ruff format --check`: **PASS**.
- `git diff --check`: **PASS**.

Repository-wide `ruff format --check .` still identifies 226 historical files
that predate the current formatter. They were deliberately not mechanically
rewritten because doing so would create unrelated churn across frozen evidence.

## Blockers

- Human ADR direction for the frozen public K=8 admissibility blocker.
- Human ADR direction for an exact-plan-aware physical primitive and unchanged
  B0 fallback wrapper.
- Zero eligible S4 training rows and no trained world-model bundle.
- Formal runner/deployment/B0-wrapper/offline-authentication bindings remain
  unset.
- S5 has no accepted human ADR or residual-enabled formal runtime.
- S6 has no authenticated 120-episode evidence set or signed terminal-failure
  lifecycle.

No training, remote command, Teacher inference, or physical evaluation was run.

Next command:

```bash
sed -n '1,260p' docs/decisions/M2C-S4-PUBLIC-CANDIDATE-ADR-REQUEST.md && \
  sed -n '1,320p' docs/decisions/M2C-S4-EXACT-PLAN-PRIMITIVE-ADR-REQUEST.md
```
