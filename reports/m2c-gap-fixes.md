# M2C stage-gap fixes and 2026-07-29 Isaac review

This low-priority review was completed during the S3 collection wait. It did
not consume S2 or S4 execution time, change B0, relax a gate, use a Teacher, or
feed privileged simulator truth to policy input.

## Results

1. **Perception `NO_GO` exit — fixed.** Commit
   `2c72ff0885a5a65fe20ad563022592e38ef87cb7` makes a measured `NO_GO`
   return process code 1. `GO` and audit-only pending states remain zero. The
   new focused test is
   `tests/unit/test_isaac_m1b_perception_gate_exit.py`.
2. **Detach gate/report wording — finding retained; gate unchanged.** Frozen
   B0 source SHA-256 remains `1e32fa89...`. The executable predicate requires
   attachment absence, hand motion at least 20 mm, hand/object relative change
   at least 20 mm, and a passing collision gate. The historical Markdown's
   short phrase `detached motion` refers to absolute object displacement and
   does not say that this number is diagnostic rather than the threshold.
   This is a documentation ambiguity, not evidence of a relaxed gate. B0 was
   not edited to repair historical wording.
3. **Dynamic `_world_pose_xyzw` — open finding.** In
   `scripts/isaac_m1b_dataset_benchmark.py`, the helper still uses
   `UsdGeom.XformCache().GetLocalToWorldTransform` for the dynamic hand and
   cylinder poses after timeline start. It can therefore report authored
   transforms rather than live PhysX poses in runtime, supervision, and shadow
   final-pose fields. Before any future dynamic benchmark is accepted, this
   helper must use the live PhysX pose API and be exercised on Isaac. Old
   authored-pose records must not be reinterpreted as live-motion evidence.

   This does not accept or reject S3 records: S3 recovery evidence is produced
   by `isaac_m1b_actuation_probe.py`, whose `_live_pose` calls
   `RigidPrim.get_world_poses()` on the PhysX tensor backend.
4. **Tilted-cylinder support Z — already fixed.** Commit
   `872e7c31257973b11e3d0575d9c134a9629ce840` replaced the reused upright
   offset with projected half-length plus projected radius. The formula and
   its scene-generation regression remain present.

## Verification

- Focused gate/scene tests: 35 passed.
- Full suite: 410 passed.
- Ruff and `git diff --check`: PASS.
- Frozen B0 probe hash: PASS (`1e32fa89...`).
- Failures: none in the local verification.

## Task report

- Changed files: `scripts/evaluate_isaac_m1b_perception_gate.py`,
  `tests/unit/test_isaac_m1b_perception_gate_exit.py`, this report, and
  `reports/m2c-gap-fixes.json`.
- Tests: focused 35 passed; full suite 410 passed; Ruff and diff checks passed.
- Failures: none. The authored-transform issue is an open finding, not a
  claimed fix.
- Blockers: live-pose repair needs a later Isaac runtime verification; Q-B
  still requires the separate human expressivity ADR.
- Next command:
  `ssh root@labserver 'python3 -m json.tool /var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/worker0/worker-status.json'`.
