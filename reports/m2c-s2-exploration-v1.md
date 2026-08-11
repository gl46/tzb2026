# M2C S2 exploration v1 — invalid domain stopped

- Verdict: **not counted for Q-A**. `B0_final_task_success_rate` and `b0_headroom` remain undefined.
- Frozen candidate: `configs/m2c_headroom_domain.json`, domain SHA-256 `6630402d9e5ee4762cfef468f391af691dcef57b96bf8d2e2ac8b35cca337dd2`, committed before execution at `d46e7d7`.
- Scene 6017: public RGB-D produced no selectable yellow target; no actuation evidence was written.
- Scene 6019: EMPTY_GRASP was inadmissible because the horizontal free cylinder moved `0.0703829985 m`; the public target track was also missing.
- The remaining eight same-domain keys were stopped without a counted outcome to preserve the S2 compute budget.
- B0 probe / runner SHA-256 remained `1e32fa89...` / `7e68c9f...`; no source, parameter, retry, safety gate, or success definition was weakened.
- Teacher was absent; no privileged simulator truth entered policy input.

## Task report

- Changed files: this JSON/Markdown exploration record.
- Tests: 2 real Isaac executions started; 0 admissible Q-A executions.
- Failures: public target absence on 6017; natural-instability/public-track failure on 6019.
- Blockers: none; exploration continues with a separately pre-registered stable upright domain.
- Next command: `make m2c-s2-domain-v2`
