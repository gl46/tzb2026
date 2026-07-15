# ADR-0001: Student world-model boundary

The Student consumes non-privileged observation/object state, robot state, language goal, and a
candidate skill/action block. It predicts future object state, contact, grasp, collision, slip,
task progress and uncertainty. `SimulatorSupervisionV0` is training/evaluation-only and is never
part of `ObservationV0` or test-time policy input. Valid data modes are `SIM_ONLY`,
`SIM_PLUS_SEMANTIC`, and `SIM_PLUS_TEACHER`; `SIM_ONLY` is complete.
