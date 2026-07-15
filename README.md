# XH-202607 World Agent

This repository implements the M0-R, P0-first baseline for an industrial pick-place agent.
Gazebo/ROS simulation, the data protocol, rule/geometric B1, and a Student world-model
boundary are independent of large Teacher models. Teacher clients are lightweight service
adapters only; no model weight is imported by the root package.

Quick verification after creating the repository virtual environment:

```bash
make test validate baseline bakeoff-prepare
```

`make sim-smoke` is deliberately bounded and records `BLOCKED_SYSTEM_DEPENDENCY` when a
compatible local ROS 2 + Gazebo installation is absent. On the verified remote host, run
`SIM_HOST=node2 SIM_USER=gl PROJECT_REMOTE_ROOT=xh-202607-world-agent make sim-smoke` after the
explicitly gated deployment. It verifies controller/perception plumbing separately from
pick-place; see `reports/` for the actual evidence and `docs/roadmap.md` for gates.

`MOVEIT_HOST=node2 MOVEIT_USER=gl PROJECT_REMOTE_ROOT=xh-202607-world-agent make
moveit-plan-smoke` adds a bounded, headless Panda MoveIt planning check. It is planning-only and
does not claim Gazebo execution.
