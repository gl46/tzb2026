# M2C S4 current blockers

- Status: **BLOCKED_UNMEASURED_ZERO_ELIGIBLE_YIELD_AND_FORMAL_EXACT_PLAN_INTEGRATION**
- Checked parent HEAD: `786b9640f60fd6192f56572a700d03012561f1ac`
- Q-A: **PASSED**
- Q-B: **UNMEASURED**
- `pure_model_success_episodes`: **null**, not zero
- D1 / D2: **false / false**

## PATH_BLOCKED training entry

ADR-0025 approved raw public-detection capacity 32 from the frozen scene-contract provenance, not from the observed maximum. The immutable scene-19083 bytes now pass the revised raw schema without truncation or filtering, but the physical result remains authoritative: terminal `CONTACT_GATE_REJECTED`, `final_task_success=false`, zero eligible rows, and no packaged sample.

Across the eighteen immutable V3/V4 collection reports, 53 distinct TRAIN identities produced 43 complete eight-step chains and zero eligible episodes. The updated ADR-0025 section-3 audit measures both per-key yield (0/53) and complete-chain conditional yield (0/43) as 0.0. At that observed point yield there is no finite evidence-based projection even for the trainer's code minimum of one eligible episode. This blocks training; it does not claim model capability is zero. Model rollout and formal Q-B evaluation have not run, so pure success remains `null`.

Ten complete V3 chains and the thirty-two Batch-09 through Batch-20 V4 chains passed gates for steps 0–6. Across all complete chains, twenty-eight terminate at the contact/controller gate, fourteen at pregrasp IK, and one lifts but fails the public success predicate. This supports a recurring terminal regrasp approach/contact-acceptance mismatch but does not isolate perception offset, approach geometry, or object state. No gate, threshold, B0 byte, or frozen eligibility predicate was changed.

Batch-20 preregistered the next three identity-disjoint V4 extension keys outcome-blind and consumed each exactly once. Scene 22008 reached Isaac startup before a stage exit-139 and never invoked the probe; scenes 22022 and 22025 completed strict eight-step chains with 16 physical receipts and zero safety violations, then remained ineligible at the unchanged REGRASP contact and pregrasp-IK gates respectively. The original V4 TRAIN manifest remains exhausted at 36/36; extension1 has consumed 6/36 with 30 unconsumed. No subsequent preregistration is active, so collection is fail-closed.

## ADR-0022 / ADR-0024 / ADR-0025 Phase-2 entry

ADR-0025 authorizes exactly two controlled-Panda start-state ACM pairs, each proven by the pinned official upstream MoveIt Panda SRDF: `panda_hand`–`panda_link7` (`Adjacent`) and `panda_link2`–`panda_link4` (`Never`). The controlled SRDF removes no pair and changes no margin, padding, hull, or threshold.

The corrected immutable query-only smoke executes 74 governed child-pair requests: 74 clear, zero collision rejection, and zero query failure. It starts neither Kit nor Isaac and performs zero articulation writes, simulation steps, or scene mutations. This closes the specific static-start ACM blocker but is not physical execution evidence.

The Phase-2 candidate remains `CONTRACT_SMOKE_ONLY_BLOCKED_UNMEASURED`. Real eight-skill plan-specific A3 evidence, immutable deployment/import closure, the reviewed synthesis/episode-I/O deployment, the real exact-plan executor, deployed read-only FK, and real endpoint/host-HMAC evidence remain absent. The two active production bindings remain unset; the withdrawn B0-wrapper and trusted-host signing prerequisites are not reinstated.

The 2026-08-20 bundle-smoke checkpoint is unchanged.

## Boundaries

- Teacher use: **false**; Teacher kill rules unchanged.
- Privileged simulator truth as policy input: **false**.
- B0 and M2B evidence: unchanged.
- Training / model rollout / formal Q-B: **false / false / false**.
- Query-only A3 smoke: **true**, with no physical execution.
- S6 frozen evaluation-manifest SHA: `ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba`.

Next command:

```bash
PYTHONPATH=src:scripts uv run pytest -q tests/unit/test_m2c_s4_current_blockers_report.py tests/unit/test_m2c_s4_v4_batch20_collection_audit.py
```
