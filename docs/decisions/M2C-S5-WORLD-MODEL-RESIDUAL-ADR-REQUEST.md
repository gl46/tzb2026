# M2C S5 world-model residual closed loop — human ADR request

- Status: **REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR**
- Date: 2026-08-13 (Asia/Shanghai)
- Governing goal: `CODEX_GOAL_M2C_HEADROOM.md` section S5
- Governing model ADRs:
  `ADR-0020-m2c-model-owned-recovery.md` and
  `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md`
- Teacher labels/runtime used: **false**
- Training executed under this request: **false**
- Residual physical evaluation executed under this request: **false**

This request freezes the decision boundary before any M2C S5 residual
training or physical closed-loop result is observed. It is not an accepted
ADR and does not authorize training, deployment, SMOKE, S5, or S6 execution.
S5 remains downstream of a valid S4 disposition: it may execute only after
S4 passes the strict Q-B gate. If S4 takes D2, the goal skips S5 and proceeds
to S6 with `GO_QRM_COARSE_ONLY`.

## Why a human decision is required

The formal Qwen V2 world-model bundle currently predicts three discrete
heads—skill, public-track pointer, and registered destination. It has no
continuous residual head. `M2C_Q012_V2` contains a separate structured MLP,
but the S4 entry gate correctly forbids treating that structured checkpoint
as the world-model control policy.

Silently inserting the standalone MLP after Qwen would create a second policy
that can change physical commands without being conditioned on the mandatory
world model. That would violate the project rule that the world-model
mainline performs prediction and selection. Enabling residual values also
changes the formal bundle, runtime mapping, exact-plan digest, physical
receipt, and safety evidence contracts. A human ADR must therefore select and
freeze the architecture before S5 training or execution.

M2B provides read-only physical residual-pair evidence and an offline result
supporting translation correction. It does not provide M2C closed-loop
evidence, does not authorize reuse of an M2B adapter, and does not support an
M2C r6d/gripper claim. No prior record may be relabelled as M2C S5 execution.

## Mutually exclusive options

### A — Qwen-conditioned translation residual; freeze r6d/gripper (recommended)

Add a versioned residual MLP to the formal Qwen world-model bundle. Its input
must include the same Qwen pooled multimodal hidden state used by the three
discrete heads plus the exact geometric nominal action. Its output remains the
existing 10-D protocol
`[dx,dy,dz,r6d_0..r6d_5,gripper]`, but only `dx/dy/dz` are trainable and
nonzero. The six r6d dimensions and gripper dimension are hard-masked to exact
zero in training, checkpoint loading, inference, mapping, and receipts.

The ADR must freeze:

- the residual head architecture, initialization source, optimizer, loss,
  label mask, tensor shapes, label order, and checkpoint revision;
- the public-only Qwen feature and nominal-action input contract;
- the 10-D frame, units, horizon, frequency, normalization, clipping, and
  finite-value rules;
- the skills for which translation residual is permitted;
- the frozen physical hard-label dataset and split/key exclusions;
- the exact zero-mask guard for r6d/gripper and a reason/limitation statement;
- the rule that the same residual values and digest enter preflight,
  `ExactExecutionPlanV2`, execution, and the physical receipt; and
- paired zero-residual versus MLP-residual closed-loop evaluation on identical
  frozen keys, with no adaptive retries or hidden replanning.

Freeze rationale: current evidence supports only translation residual. Keeping
r6d/gripper at exact zero prevents unsupported actuation while still answering
the S5 question of whether an MLP produces a measurable closed-loop change.
The report must state that conclusions do not cover orientation or gripper
residuals.

### B — Qwen-conditioned full 10-D residual after new physical supervision

Use the same Qwen-conditioned architecture, but authorize r6d and gripper only
after collecting new, hash-bound, non-degenerate physical correction labels
for all ten dimensions. The ADR must add dimension-specific coverage,
reconstruction, range, independent-execution, split-isolation, and closed-loop
safety gates. A zero-filled label does not count as supervision.

Trade-off: this can test a broader controller, but expands collection and
safety-review scope and cannot inherit an r6d/gripper claim from M2B's
translation-only offline result.

### C — do not authorize a residual architecture; take D3/COARSE_ONLY

Do not add a residual head to the formal Qwen bundle. If S4 passed, record that
S5 could not execute under an approved world-model residual contract and keep
the verdict `GO_QRM_COARSE_ONLY`. Do not report the absence of execution as a
measured zero effect. Continue only with the formally permitted S6 comparison
and final audit.

Trade-off: no new model or physical semantics, but S5 cannot measure MLP versus
zero residual.

## Non-negotiable runtime and evidence rules

- The Qwen world model remains the prediction-and-selection mainline. The MLP
  may refine the selected action; it may not select or replace the skill.
- No Teacher soft label, Teacher response, Teacher adapter, or Teacher runtime
  component is permitted. Any occurrence kills the affected run.
- Entity/prim identity, perfect pose, injected failure truth, contact truth,
  and task-success truth remain unavailable as policy inputs.
- B0, schema, stale-track, frame/unit, IK, joint-limit, swept-collision,
  controller, and safety gates remain unchanged and run before execution.
- A residual rejected by schema/range/preflight may not be clipped into a
  formally successful model action unless the exact clipping rule is frozen
  by the ADR and the clipped value is the value bound into the exact plan.
- Any B0 fallback or fixed continuation excludes strict pure-model success.
- Zero and MLP arms use identical frozen keys and nominal actions. Every real
  model decision has a unique, hash-verified physical receipt.
- A measurable positive or negative difference satisfies the S5 measurement
  gate; neither direction may be hidden. Collision/safety violations remain
  disqualifying, not a performance trade-off.
- Offline loss, fixture, dry-run, or synthetic receipt is not closed-loop
  evidence.

## Required S5 report fields

The accepted implementation must produce
`reports/m2c-s5-residual-closed-loop.json` and `.md` with:

- selected ADR option, accepted ADR path/SHA/commit, implementation commit,
  bundle/checkpoint/data/key-manifest hashes, and immutable runtime bindings;
- explicit `r6d_disposition` and `gripper_disposition`, each either
  `TRAINED_WITH_PHYSICAL_EVIDENCE` or `FROZEN_EXACT_ZERO`, plus evidence or
  freeze reason and limitations;
- paired key count, zero and MLP execution counts, per-arm success/safety/time
  metrics, the pre-registered effect estimate and interval, and whether a
  measurable difference was observed;
- per-decision exact residual/action/plan/physical-receipt bindings;
- Teacher, privileged-truth, world-model-mainline, B0, and gate attestations;
- all exclusions, infrastructure failures, and negative results; and
- changed files, tests, failures, blockers, and one next command.

## Human approval fields

- Selected option: `A | B | C`
- Machine-readable marker for an accepted Option-A ADR (exact standalone
  line): `M2C-S5-SELECTED-OPTION: A`. Option B requires a new full-dimension
  evidence schema and its own exact marker before this V1 verifier may accept
  it; the translation-only V1 contract intentionally rejects B.
- Accepted ADR ID/path (required for A or B):
- Approver, role, timestamp, timezone:
- Formal bundle/checkpoint revision:
- Residual head architecture and initialization source:
- Physical hard-label dataset and frozen split/key manifests:
- Trainable output dimensions:
- r6d disposition and evidence/freeze reason:
- gripper disposition and evidence/freeze reason:
- Frame, units, dimensions, horizon, frequency, normalization:
- Per-skill residual allowlist and bounds:
- Exact-plan and receipt schema revisions:
- Paired S5 estimand, interval method, and minimum keys/executions:
- Teacher use attestation: `NONE`
- Privileged-truth policy-input attestation: `NONE`
- B0 modification authorized: `NO`
- Safety-gate weakening authorized: `NO`
- Independent model/provenance reviewer:
- Independent physical-safety reviewer:

Until an option is accepted in a separate human ADR, residual values must
remain disabled in the formal M2C runtime and no S5 execution may begin.

## Task report

- Changed file: this human ADR request only.
- Tests: documentation readback and repository whitespace checks only; no
  training or physical result is claimed.
- Failures: none; the missing approved architecture is a governance blocker.
- Blockers: S4 has no valid disposition; no accepted S5 residual ADR; no
  residual-enabled formal Qwen bundle, exact-plan primitive, or physical
  receipt path.
- Next command: human reviews this file after selecting the two S4 ADR
  requests, then selects exactly one S5 option if S4 is allowed to proceed.
