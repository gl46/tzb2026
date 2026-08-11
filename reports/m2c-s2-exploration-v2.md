# M2C S2 exploration v2 — public contract invalid

- Verdict: **not counted for Q-A**. `B0_final_task_success_rate` and `b0_headroom` remain undefined.
- Scene 7018: physical EMPTY_GRASP passed with only `6.14e-8 m` target motion, but the public failure predicate was not admitted, so it is not a Student-usable recovery episode.
- Scene 7037: public RGB-D produced no selectable yellow target and no actuation evidence.
- The remaining eight keys were stopped before a counted outcome.
- Frozen B0 source, parameters, retry count, gates, and success definition were unchanged; Teacher and privileged policy inputs were absent.

## Task report

- Changed files: this JSON/Markdown exploration record.
- Tests: 2 real Isaac executions started; 0 admissible Q-A executions.
- Failures: missing public failure predicate on 7018; missing public target on 7037.
- Blockers: none; V3 retains the original object geometry and changes layout only.
- Next command: `make m2c-s2-domain-v3`
