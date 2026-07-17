# M1A S0 contact telemetry calibration

- Status: `CONTACT_TELEMETRY_CALIBRATED`
- Reason: 13/13 independently reset approved conditions passed.
- Runtime oracle pose source: `gz model runtime query before every isolated label`
- Completed condition trials: `13/13`
- Every motion trial records cube pose, MoveIt/IK result, finger action, pad FK, minimum AABB separation, and raw contact pairs.
- Full S0 runs reset Gazebo and the calibration target before every labelled condition.
- No grasp is claimed by this calibration audit.
