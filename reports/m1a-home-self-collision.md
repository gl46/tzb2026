# M1A approved-model home self-collision gate

- Status: `HOME_SELF_COLLISION_VERIFIED`
- MoveIt reports the approved home state as collision-free.
- Same URDF SHA-256: `49ffca858e22842b70b7c24ba4ae59e8163e9e50db7f26ff172d817a17e7b207` / `49ffca858e22842b70b7c24ba4ae59e8163e9e50db7f26ff172d817a17e7b207`
- Method: MoveIt `check_state_validity`, with no motion command.
- Changed files: no source files; this is runtime evidence for the approved URDF/SRDF.
- Tests: same-URDF hash comparison and `panda_arm` state-validity query at the SRDF home posture.
- Failures: see the immutable run-specific raw log; a non-verified result blocks S0.
- Blocker: `NONE`.
- Next command: `scripts/run_isolated_contact_calibration.sh`.
