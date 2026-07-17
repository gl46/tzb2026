# M1A S4 B1 Oracle

- Status: `B1_ORACLE_EXECUTION_VERIFIED`
- Fresh B1 reset episodes: `10/10`; successes: `10`; positive releases: `10`.
- Runtime oracle was task geometry only, not an Observation field: `True`.
- A fresh 10-reset B1 batch used the runtime Gazebo pose only as oracle task geometry, then collision-checked IK and controller execution; at least 8 episodes completed contact-gated pick/place and positive release.
