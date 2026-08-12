# M2C stage-gap fixes and 2026-07-29 Isaac review

This low-priority review is complete. The live-pose repair was implemented
after the S3 evidence tree and Dataset V3 were frozen, and before the
human-ADR-gated S4. It did not consume S2 or S4 execution time, change B0,
relax a gate, use a Teacher, feed privileged simulator truth to policy input,
or run Q-B training/evaluation.

## Results

1. **Perception `NO_GO` exit — fixed.** Commit
   `2c72ff0885a5a65fe20ad563022592e38ef87cb7` makes a measured `NO_GO`
   return process code 1. `GO` and audit-only pending states remain zero. The
   focused regression is
   `tests/unit/test_isaac_m1b_perception_gate_exit.py`.
2. **Detach gate/report wording — finding retained; gate unchanged.** Frozen
   B0 source SHA-256 remains `1e32fa89...`. The executable predicate requires
   attachment absence, hand motion of at least 20 mm, hand/object relative
   change of at least 20 mm, and a passing collision gate. The historical
   Markdown phrase `detached motion` is ambiguous because it describes
   diagnostic object displacement rather than the actual threshold. No B0
   source or threshold was edited.
3. **Dynamic `_world_pose_xyzw` — fixed and verified on Isaac Sim 6.0.1.**
   `scripts/isaac_m1b_dataset_benchmark.py` now reads hand and dynamic-object
   poses with `RigidPrim.get_world_poses()` from the PhysX tensor backend.
   Isaac's `wxyz` quaternion is explicitly serialized into the existing
   protocol's `xyzw` order. Metrics declare the source and state that old
   authored-transform records are not reinterpreted as live-pose evidence.
4. **Strict frame `shadow_candidate` mismatch — fixed.** The benchmark had
   unconditionally written an extra field into the strict runtime and
   supervision frame schemas. The field is now absent from both streams;
   candidate identity remains in `metrics.shadow_counterfactual.profiles`, its
   existing valid consumer. A final dynamic capture built 3 strict transitions
   with zero non-null Teacher responses and zero policy segmentation URIs.
5. **Tilted-cylinder support Z — already fixed.** Commit
   `872e7c31257973b11e3d0575d9c134a9629ce840` replaced the upright-only
   offset with projected half-length plus projected radius. The formula and
   scene-generation regression remain present.

## Frozen-history boundary

- The final fixed benchmark SHA-256 is
  `e153c0ce70e4fd3aef47b334cf1168ae107c88eb8e19ca493a174420d38116f8`.
- The frozen S3 collection plan remains bound to the pre-fix builder SHA-256
  `800a103035c87089367f64d8b7c191ef626f33aab709b59aa05b08efbf3050b1`.
- S3 reports and Dataset V3 were not rewritten. S3 acceptance came from
  `isaac_m1b_actuation_probe.py`, which already used PhysX `RigidPrim` live
  poses; no old benchmark record is promoted or reinterpreted.
- The read-only B0/M2B recheck passed: B0 sources match M2B, 116/116 artifact
  index entries verified, M2B report mismatches are zero, and local M2B
  artifacts match their frozen hashes.

## Isaac verification

- **Dynamic Student dataset:** PASS, 4 frames. The hand has 4 distinct live
  poses and moved 0.0113857482 m from first to last frame. All 9 dynamic
  objects have 4 live samples; cylinders 03, 06, and 09 moved about 0.029 m.
  All pose values are finite. The strict offline join produced 3 transitions.
  Evidence root:
  `/var/tmp/xh-data/isaac-industrial/m2c-live-pose-final-dynamic.N1dKy9`;
  81 files; ledger SHA-256
  `622c699e963b45f30bb18359f6aeba8ab6aa766706cc129969a0a1105ebe9ce1`;
  writable paths: 0.
- **Static perception audit:** PASS, 2 frames. All 9 cylinder rigid bodies were
  kinematically frozen; the output remains ineligible for Student training.
  Evidence root:
  `/var/tmp/xh-data/isaac-industrial/m2c-live-pose-final-static.ArBmng`;
  46 files; ledger SHA-256
  `7c11d8c4d8754da2902c660c9f61733bd6be89f75b968f6ff5cc96af697fd5c3`;
  writable paths: 0.
- **Shadow reset:** PASS after two retained native-startup failures, 3
  candidates × 2 frames. Three timeline stop/play resets produced finite live
  final-hand poses with pairwise position differences of 0.0079811642 m,
  0.0180386528 m, and 0.0128629132 m. Model action mapping was not used,
  privileged truth was not policy input, and training eligibility is false.
  Evidence root:
  `/var/tmp/xh-data/isaac-industrial/m2c-live-pose-final-shadow-last.YkSv67`;
  110 files; ledger SHA-256
  `82d44ddb63e52b49eb088b872f9bf333ab95b26ac943eacbae1d58a78c2bf10b`;
  writable paths: 0.

## Failures retained

- The first post-fix transition join rejected the historical extra
  `shadow_candidate` field. The field was removed, and the final fixed-SHA run
  passed the strict join with 3 transitions.
- Two fixed-SHA shadow startup attempts exited 139 inside native Isaac/RTX
  before metrics existed. Their logs were not deleted or relabelled:
  - `/var/tmp/xh-data/isaac-industrial/m2c-live-pose-final-shadow.roFT4D`,
    log SHA-256
    `e9610c3db98e20adb32d3b43196a246d4af339bcf1087015f9a330a3df6ab349`,
    ledger SHA-256
    `16ba02e89f088725f84794781e76f72dd81dd85661d19de6dcc201ffa55ad6ef`.
  - `/var/tmp/xh-data/isaac-industrial/m2c-live-pose-final-shadow-retry.OpQSER`,
    log SHA-256
    `cb03a73d218c8a525d9af2fa0d18b3a0960a97668e6bbe44da7e7da3bca2dd24`,
    ledger SHA-256
    `d378670a4576e3e2efcd34e1dc3d0db5af67017125ac2f68923f42c9b465a4b2`.
  Both directories are read-only. The final controlled attempt exited 0 and
  passed all shadow profile checks.

## Task report

- Changed files: `scripts/isaac_m1b_dataset_benchmark.py`,
  `tests/unit/test_isaac_m1b_scene.py`, this report, and
  `reports/m2c-gap-fixes.json`.
- Tests: 69 focused tests passed; full suite 440 passed; Ruff and
  `git diff --check` passed; B0/M2B read-only recheck passed; final-SHA dynamic,
  static-perception, and shadow-reset Isaac modes passed.
- Failures: one intermediate strict-schema failure was fixed; two native
  Isaac/RTX exit-139 attempts are retained above and in the JSON report.
- Blocker: Q-B remains forbidden until a separate human expressivity ADR is
  committed. Q-B training/evaluation executed: false.
- Teacher used: no; Teacher kill-rule events: none.
- Next command:
  `sed -n '1,240p' docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md`.
