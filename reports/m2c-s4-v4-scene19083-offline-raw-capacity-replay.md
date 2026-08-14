# M2C S4 V4 scene 19083 offline raw-capacity replay

- Status: **PASS_OFFLINE_REPLAY_EXCLUDED_UNCHANGED_PHYSICAL_FAILURE**
- Scope: offline replay only; no Isaac launch, retry, replacement, training, or Q-B evaluation
- ADR-0025 Option A: raw capacity 32; final candidate K remains 8
- Immutable raw counts: `7, 13, 11, 7, 8, 9, 10, 10`
- Host replay: 8 steps, candidate counts `[7, 8, 8, 7, 8, 8, 8, 8]`
- Physical outcome: `final_task_success=false`; terminal `CONTACT_GATE_REJECTED`
- Training eligibility: `false`; persisted samples: 0
- Exclusion reasons: `['FINAL_TASK_NOT_SUCCESSFUL', 'STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8', 'STEP_7:CONTROLLER_GATE_NOT_PASSING']`
- Teacher used: false; privileged simulator truth as policy input: false

The replay makes the immutable public capture history parseable under the approved
32-detection envelope. It does not reinterpret the physical failure or create a
training row. The unchanged K=8 and training predicates remain authoritative.
