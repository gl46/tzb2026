# M2C S2 Q-A gate — V4 passed

- Verdict: **Q-A PASS**. On the three pre-registered matched keys, unchanged
  B0 completed 0 tasks, so `B0_final_task_success_rate = 0/3 = 0.0` and
  `b0_headroom = 1.0`. All three keys had a valid public yellow target; each
  of the six frozen B0 attempts was rejected before action by the unchanged
  5 mm free-gap gate.
- Physical recoverability: seed 9077 completed the full strict chain: public
  red blocker grasp/lift, collision-gated transport to official bin cell 3,
  release, public yellow target reassociation, actual target regrasp/lift,
  `grasped=true`, `lifted=true`, recovery eligibility, and 0 collision
  violations across 13 reported collision gates.
- Result-blind boundary: V4 was generated and committed at `f40459d` before
  any V4 Isaac execution. Its manifest SHA-256 is `4e78c044...` and domain
  SHA-256 is `a08d0dee...`. The design honestly used V3 findings.

## Strict exclusions

The derived probe's broad top-level `PASS` was not used as the existence
predicate. Seed 9038 was excluded because target regrasp ended at
`CONTACT_GATE_REJECTED`; seed 9057 was excluded at
`PREGRASP_IK_GATE_REJECTED`. Both safely transported the blocker with zero
collision violations, but neither produced an executed target regrasp or the
required public `grasped=true` / `lifted=true` predicates.

## Governance

- B0 probe / runner SHA-256 remained `1e32fa89...` / `7e68c9f...`; retries,
  safety, IK, collision, schema, mapping, and success definitions were not
  changed.
- The existence probe remained `6623b1ce...`; Panda URDF remained
  `6678ff40...`; Isaac Sim image ID remained `783444c...`.
- The 167-file remote evidence tree is read-only. Its SHA-256 ledger is
  `/var/tmp/xh-data/isaac-industrial/m2c/headroom-v4/evidence-sha256.txt`,
  ledger SHA-256 `99ae0f4f...`.
- Teacher was not used. Privileged simulator truth was not policy input. The
  world-model mainline was not replaced.
- D1 is not triggered. V5 remains forbidden.
- **Q-B is still blocked.** The pre-registration at
  `docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md` found that current
  `CoarseIntentV1` cannot model-select both a public blocker track and a
  registered destination end to end. A separate human ADR is mandatory before
  any Q-B training or evaluation; Q-A passing does not supply that authority.

## Task report

- Changed files: `reports/m2c-s2-exploration-v4.json`, this report, and
  `tests/unit/test_m2c_s2_v4_report.py`.
- Tests/executions: 3 real stages, 6 frozen B0 attempts, 3 real existence
  executions, 1 complete strict proof, 0 collision violations.
- Failures: 9038 contact-gate rejection and 9057 pregrasp-IK rejection were
  retained and explicitly excluded from the proof count.
- Blocker: Q-B requires the separate human expressivity ADR.
- Next command:
  `sed -n '1,220p' docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md`.
