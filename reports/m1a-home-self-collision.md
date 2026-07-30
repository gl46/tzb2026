# M1A approved-model home self-collision gate

- Status: `HOME_SELF_COLLISION_VERIFIED`
- MoveIt reports the approved home state as collision-free.
- Same URDF SHA-256: `6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8` / `6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8`
- Method: MoveIt `check_state_validity`, with no motion command.
- Changed files: no source files; this is runtime evidence for the approved URDF/SRDF.
- Tests: same-URDF hash comparison and `panda_arm` state-validity query at the SRDF home posture.
- Failures: see the immutable run-specific raw log; a non-verified result blocks S0.
- Blocker: `NONE`.
- Next command: `scripts/run_isolated_contact_calibration.sh`.
