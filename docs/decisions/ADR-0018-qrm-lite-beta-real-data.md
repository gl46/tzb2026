# ADR-0018: QRM-Lite Beta on real Isaac RGB-D and FailureContext

- Status: Accepted for M2A evidence collection
- Date: 2026-07-31
- Parent: QRM Alpha tag `qrm-lite-alpha` at `0287d23`
- Alpha verdict: `GO_COARSE_AND_MLP_ONLY`

## Decision

1. Beta trains coarse skills and a bounded MLP residual on Canonical episodes
   captured by Isaac Sim 6.0.1.
2. Qwen3.5-4B remains pinned to revision
   `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; LoRA on/off FailureContext runs
   use identical scene splits, seeds and budgets.
3. Flow remains in the repository but is `DISABLED` for M2A.
4. FailureContext is an explicit project addition: failure type, predicate
   residual, retry count, previous skill and recovery history.
5. The continuous target is a bounded camera-optical-frame correction to the
   public geometric nominal. Offline simulator truth may supervise the target
   but is never a model input.
6. Online order is model output, schema validation, clipping, transform/action
   mapping validation, IK/collision planning, then execution or B0 fallback.
7. No camera-residual-to-Franka-joint mapping may be invented. Until official
   evidence exists, that mapping gate rejects and B0 executes.
8. Only held-out and live Isaac evidence can support a scale-up verdict.

## Governance scope

This ADR authorizes the bounded M2A QRM experiment. It does not silently amend
ADR-0001 or replace the repository's mandatory world-model governance. A
broader mainline replacement requires a separate human ADR/merge decision.

## Stop conditions

- Oracle truth appears in the QRM observation or prompt.
- FailureContext split/budget differs between ablation arms.
- Residual bypasses mapping, IK, collision or workspace validation.
- LoRA/MLP metrics are reported without retained raw logs and data hash.
- MLP fails held-out or live evidence: retain coarse/B0 and stop scaling it.

## Teacher boundary and kill rules

QRM-Lite is not installed as a Teacher and Teachers never enter the control
stack. Nano/BWM/Super states remain unchanged. Teacher kill-rule events:
**none**.

