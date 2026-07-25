# M1A runtime grasp status

- Overall: `PASS`
- S0: `CONTACT_TELEMETRY_CALIBRATED`
- S1: `VERIFIED_MOVEIT_EXECUTION`
- Hand actuation: `HAND_MIMIC_Q2_MASTER_NOT_VERIFIED`; controller probe verified: `False`; same current URDF: `False`.
- Bullet capability audit: `M1A_BULLET_CAPABILITY_VERIFIED`; same current URDF: `True`.
- Bullet counterfactuals: `M1A_BULLET_SIGN_HYPOTHESIS_RESOLVED_CLEAN`.
- Static actuation audit: `M1A_CLEAN_SIGN_CONFIRMED_PASSIVE_HOLD_BLOCKED`.
- S2: `FRICTIONAL_GRASP_NOT_VERIFIED`; S3: `CONTACT_GATED_CONSTRAINT_VERIFIED`; S4: `B1_ORACLE_EXECUTION_VERIFIED`.
- Final grasp mode: `PASS_CONTACT_GATED_CONSTRAINED_GRASP`; B1: `10/10`.
- Collision-policy exception: the attached-cube/work-table ACM exception was temporary for lift and restored in every B1 episode: `True`.
- Tests: `0 passed`, `0 failed`; `scripts/validate_project.py` passed.
- Changed files: `9` (the complete list is in JSON).
- Blockers: `[]`.
- Next command: `M1A execution gates are complete; review the final audit and preserve the raw logs.`
- Teacher did not block M1A. `READY_FOR_M1B=true`.
