# Recorder boundary

Map joint state, trajectory, gripper, TF, RGB, depth, camera info, perceived tracks, contact and
collision to `ObservationV0` and a separately persisted `SimulatorSupervisionV0`. Never inject
ground-truth pose/contact/collision/task success into the observation topic or policy input.
