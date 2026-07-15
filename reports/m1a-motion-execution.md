# M1A S1 MoveIt execution gate

- Status: `BLOCKED`
- Reason: MoveIt is configured with the official Panda resource rather than the Gazebo-controlled panda_controlled.urdf; no unsafe S1 trajectory was dispatched.
- Gazebo URDF sha256 (local/remote): `efc3abf467ccc79484a8ed0907e61a6df417420395f1327005bed40386ca343c` / `efc3abf467ccc79484a8ed0907e61a6df417420395f1327005bed40386ca343c`
- No controller trajectory is counted as MoveIt execution until the models and standard action chain are unified.
