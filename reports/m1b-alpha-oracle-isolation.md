# M1B-alpha Oracle isolation audit

- `PerceptionInputV1` rejects undeclared perfect-pose/entity/success fields.
- `PerceptionResultV1.track_id` must be a public `track-<hash>` value.
- `GeometricRGBDBaseline` accepts only caller-provided depth and intrinsics; it
  has no simulator imports.
- `NonOracleGraspBroker` exposes generic feedback while retaining entity routing
  only in a supervision return for the actuator/evaluator boundary.
- `SimulatorLabel.actual_sim_entity_id` lives only in `perception.evaluator`.
- Automated tests: `tests/unit/test_m1b_alpha_perception.py`.
