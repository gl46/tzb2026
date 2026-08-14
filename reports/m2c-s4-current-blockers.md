# M2C S4 current blockers

- Status: **BLOCKED_UNMEASURED_RAW_SCHEMA_AND_FORMAL_EXACT_PLAN_INTEGRATION**
- Checked HEAD: `f541059ccd6ff537b196957d88d156832acddce5`
- Q-A: **PASSED**
- Q-B: **UNMEASURED**
- `pure_model_success_episodes`: **null**, not zero
- D1 / D2: **false / false**

## PATH_BLOCKED training entry

The permission problem is resolved. Batch-04 consumed three preregistered V4
TRAIN keys but failed before Kit because the stage-output directory was not
writable. The subsequent immutable evidence shows progressive recovery of the
same execution path:

- Batch-06 passed stage construction and was stopped by an overly strict
  source-snapshot owner check before the probe could start Kit;
- Batch-07 started the probe's `SimulationApp` and was stopped before the
  physics timeline by a premature proprioception read;
- Batch-08 produced one complete eight-step raw public physical chain with
  eight physical-skill receipts and zero collision or safety violations.

Across V3 and V4, 19 distinct TRAIN identities have now been consumed: 11 V3
identities and 8 V4 identities. The immutable reports contain ten V3
eight-step chains and one V4 raw eight-step chain. None is currently eligible
for training, so packaged samples remain zero. Training, model rollout, and
formal Q-B evaluation have not run; `pure_model_success_episodes` must remain
null.

The remaining V4 collection blocker is not a permission failure. Scene 19083's
ordered public captures contain 7, 13, 11, 7, 8, 9, 10, and 10 raw detections.
The approved association contract currently limits the *raw* capture schema to
8 before association, independently of the final K=8 candidate window. The
host replay therefore correctly rejects five captures and does not package the
chain. Its physical result remains `final_task_success=false` with a terminal
contact-gate rejection; making the captures parseable cannot reinterpret that
outcome.

Changing the raw schema bound is one of ADR-0024's explicitly retained human
decision categories. The post-outcome request
`M2C-S4-V4-RAW-DETECTION-CAPACITY-ADR-REQUEST.md` therefore remains NOT
APPROVED: it records no selected option, no numeric capacity, no offline replay
authority, and no new collection or training authority. In particular, the
observed maximum 13 is not used as numeric authority.

## ADR-0022 / ADR-0024 Phase-2 entry

The A3 query-only deployment path is now executable with immutable permissions,
the pinned Isaac 6.0.1 image, float64 Bullet libraries, the controlled-Panda
URDF/SRDF and original collision meshes. It starts neither Kit nor Isaac and
performs zero articulation writes, simulation steps, scene mutations, Teacher
calls, or privileged-truth policy reads.

The final immutable query-only smoke checked all 76 non-ACM child pairs at the
same frozen joint state. Seventy-four are clear, two are fail-closed collision
rejections, and none is a query failure. The rejected pairs are
`panda_hand`–`panda_link7` and `panda_link2`–`panda_link4`; both already overlap
at the discrete start state and neither is disabled in the frozen SRDF. No
collision margin, padding, geometry, ACM entry, or safety threshold was changed
to force a pass.

Consequently the Phase-2 candidate addendum remains
`CONTRACT_SMOKE_ONLY_BLOCKED_UNMEASURED`. It is not physical evidence and does
not authorize formal execution. The four production bindings remain null.
The V4 host-orchestration/evidence contract and HTTP service shell now exist
and preserve terminal `NO_PHYSICAL_EXECUTION` without B0 substitution. The
service's production backend factory remains deliberately unbound. The V4
host-local verifier now replays both exact audit lifecycles, every HMAC
envelope, the consumed challenge, and variable one-to-eight-decision terminal
counts without an SSH/signing prerequisite. No real node2/labserver receipt
has been produced. Plan-specific eight-skill phase receipts, immutable
deployment/import closure, the real exact-plan Isaac executor, the deployed
read-only FK provider, and real-session endpoint evidence remain missing.

ADR-0024's B0 decision is preserved: invalid mapping or preflight rejection is
terminal `NO_PHYSICAL_EXECUTION`, never a relabelled B0 fallback. The independent
B0 comparison arm remains unchanged.

## Boundaries and verification

- Teacher use: **false**; Nano/BWM/Super remain CANDIDATE /
  CANDIDATE_LICENSE_PENDING / PARKED.
- Privileged simulator truth as policy input: **false**.
- B0 and M2B evidence: unchanged.
- Production safety/IK/collision/controller/schema gates: unchanged.
- V4 physical-supervision collection after Batch-03: **yes**, exactly as
  recorded by the Batch-04/06/07/08 reports.
- Training / Phase-2 physical smoke / formal Q-B evaluation:
  **false / false / false**.
- S6 frozen evaluation-manifest SHA:
  `ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba`.
- Focused S6/status/entry regression: **33 passed**.

Failures: no product-test failure. The mainline remains deliberately
fail-closed at two boundaries: the governed V4 raw-detection schema decision
and the unbound formal exact-plan deployment/evidence path.

Next command:

```bash
.venv/bin/pytest -q tests/unit/test_m2c_s4_current_blockers_report.py
```
