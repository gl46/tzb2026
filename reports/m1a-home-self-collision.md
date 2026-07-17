# M1A approved-model home self-collision gate

- Status: `HOME_SELF_COLLISION_VERIFIED`
- MoveIt reports the approved home state as collision-free.
- Same URDF SHA-256: `84b0d2dc67dea0071a696e4e09211d0ff44d9694e57d7b2a3aa8978f37e5081c` / `84b0d2dc67dea0071a696e4e09211d0ff44d9694e57d7b2a3aa8978f37e5081c`
- Method: MoveIt `check_state_validity`, with no motion command.
- Changed files: no source files; this is runtime evidence for the approved URDF/SRDF.
- Tests: same-URDF hash comparison and `panda_arm` state-validity query at the SRDF home posture.
- Failures: see the immutable run-specific raw log; a non-verified result blocks S0.
- Blocker: `NONE`.
- Next command: `scripts/run_isolated_contact_calibration.sh`.
