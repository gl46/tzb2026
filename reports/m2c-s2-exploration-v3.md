# M2C S2 exploration V3 — Q-A not passed

- Verdict: **V3 stopped; not counted for Q-A**. The formal B0 success rate and
  `b0_headroom` remain undefined because the full pre-registered domain did
  not preserve the public contract and no complete existence proof passed.
- Frozen B0 did expose the intended gap on public-valid seeds 8018 and 8277:
  both retries were rejected before physical action by the unchanged 5 mm
  free-gap gate. Seeds 8039 and 8097 instead lacked a public yellow target and
  are invalid, not B0 failures.
- The scripted red-blocker relocation passed on 8018, 8038, and 8337 with zero
  transport collision violations, destination error at most 3.21 mm, and
  carried-object follow error at most 1.09 mm. None completed the yellow-target
  regrasp: two failed contact and one failed pregrasp IK. Seed 8039 lacked the
  public yellow target; 8277 lacked the public red blocker.
- The derived probe's broad top-level `PASS` is not treated as proof success;
  the nested target regrasp and public final predicates are mandatory.
- Per the frozen stop-loss rule, exactly one final domain candidate (V4) is
  allowed. A V4 non-pass triggers D1; a public-contract-invalid V4 also emits
  the required formal public-perception/predicate-admission finding.
- B0 sources, parameters, two-retry policy, IK/collision/safety gates, and
  success definition were unchanged. Teacher and privileged policy inputs
  were absent.

## Task report

- Changed files: this JSON/Markdown exploration record.
- Tests: 8 real B0 attempts; 5 real existence executions; 2 admissible B0
  failure examples; 0 complete existence proofs.
- Failures: two B0 keys lacked public yellow; two existence runs lacked a
  required public target; three target regrasp runs failed unchanged gates.
- Blockers: Q-A remains closed; only V4 remains. Q-B also remains blocked on
  the human ADR required by the expressivity pre-registration.
- Next command: pre-register V4 before any V4 Isaac execution.
