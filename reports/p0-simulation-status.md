# P0 simulation status

- Status: `VERIFIED_CONSTRAINED_P0_GATE` on `node2`.
- Gazebo / project world / controller-backed arm: **True** / **True** / **True**.
- Active arm / hand controllers: **True** / **True**; bounded arm / hand actions: **True** / **True**.
- RGB / depth / camera info: **True** / **True** / **True**; joint state / TF: **True** / **True**.
- Physical props: **3**; constrained pick-place: **True**; EpisodeTransition recorded: **True**.
- Contact supervision was observed. The cube settled inside `bin_a` after release.
- The transfer used an explicit Gazebo DetachableJoint constraint. It is not a verified frictional finger-contact grasp; the documented finger-contact experiment failed.

## Evidence scopes

- The original bounded control/perception smoke is retained as `PARTIAL_CONTROL_AND_PERCEPTION_VERIFIED` in the JSON report.
- The subsequent constrained-transfer evidence is recorded in `reports/p0-constrained-pick-place-status.json` and `data/episodes/p0-constrained-transfer.json`.
