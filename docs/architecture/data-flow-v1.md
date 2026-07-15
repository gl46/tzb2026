# Data flow v1

`ObservationV0` stores sensor URIs, calibration, robot state, perceived object tracks,
relationships, task/subgoal, coordinate definition and uncertainty. Privileged poses/contact/
collision/task success are stored only in `SimulatorSupervisionV0` with
`training_and_evaluation_only=true`. `EpisodeTransitionV0` joins before/after observation,
TaskSpec, skill, trajectory, supervision and optional Teacher/semantic labels.

`xh_agent.world_state.StudentWorldModel` consumes only `ObservationV0`, `TaskSpecV0`, a
`CandidateSkillV0`, and `ActionTrajectoryV0`. Its planned output contains predicted future
perceived tracks, contact/grasp/collision/slip probabilities, task progress, and uncertainty.
`rank_candidates` gates high-uncertainty/collision candidates; `attribute_residual` compares the
prediction only with the next `ObservationV0`. `SimulatorSupervisionV0` is never an execution-time
input. `SIM_ONLY` is therefore a complete path: supervision trains/evaluates Student offline while
runtime remains independent of Teacher and privileged truth.
