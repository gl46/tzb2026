# M2C S4 frozen TRAIN collection batch 02 pre-registration

- Status: pre-registered before observing any batch-02 execution result
- Written: 2026-08-13 03:09 Asia/Shanghai
- Parent authorization: `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md`
- Frozen TRAIN/SMOKE manifest file SHA-256:
  `ca2162a898853ee04600aaf9246c121ac0604754638e497d1824b159c161fd94`
- Frozen S6 manifest file SHA-256:
  `ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba`
- Runtime implementation commit:
  `b6def060326ae78235826cf8600dbe10f29c1a58`

## Information observed before selection

Eight unique frozen TRAIN keys have been attempted. Six stopped fail-closed
because the public task target was outside the literal-ID canonical K=8 at
step 6. Two admitted the task target into K=8 but ended with
`CONTACT_GATE_REJECTED` on the scripted step-7 regrasp and
`final_task_success=false`. No eligible PATH_BLOCKED supervised episode has
been packaged. These are scripted public physical-supervision attempts, not
model rollouts, and they do not measure `pure_model_success_episodes`.

## Outcome-independent selection rule

1. Start from the 36 `training_keys` in the frozen manifest.
2. Exclude the eight already-attempted scene seeds:
   `12000, 12005, 12008, 12029, 12050, 12071, 12086, 12091`.
3. Partition the remaining keys by their frozen `sdf_sha256`.
4. In each of the three SDF partitions, select the record with the smallest
   numeric `scene_seed`.
5. Execute the resulting three records once each. Do not retry or replace a
   record based on its rollout outcome.

This rule selects exactly:

| Scene seed | Failure seed | Matched key | SDF SHA-256 |
| ---: | ---: | --- | --- |
| 12143 | 121437 | `m2c-s4-s6-47409cfba791cc436557e20aec69fd0bb2bcef7d6cb5c48331ff742f90da7869` | `2bd5a27d6d3a2ff42152024e4fbd9a68749840c153f3fe68e5b27085e58b1615` |
| 12169 | 121697 | `m2c-s4-s6-a43e239fbf1ae465f18bb88950fbbccce2ac72f865369426296996bdee4bc4ab` | `769d539378a899420e55c172a34c01cfaef19c1a83fe3eded3f7a4ba190c825d` |
| 12109 | 121097 | `m2c-s4-s6-2254c8eaf1e913d14e19fecda4d2cab332ead3d08c1084e1581ef33fb45fb4a0` | `e30efb66aef4ff948e48551cb26d03990c14b6bb25813b9a8fd6e8b7c9831cf7` |

All three records are `role=TRAIN`, `split=train`, and are disjoint from the
V4 Q-A keys, all frozen physical-prerequisite SMOKE keys, and all frozen S6
evaluation keys.

## Fixed execution and stop rules

- Use the hash-verified, read-only runtime snapshot of commit `b6def06` and
  the frozen upstream V4 probe SHA-256
  `6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87`.
- Candidate construction remains literal `track_id` ascending, K=8. No
  confidence filter, recapture rule, candidate expansion, or pointer fallback
  is introduced.
- Safety, IK, collision, controller, schema, stale-track, and frame/unit gates
  remain unchanged. A rejection is preserved as a failed attempt.
- Each matched key is create-only and is executed at most once in this batch.
- The batch stops after the three selected records regardless of outcomes.
- Packaging is allowed only when the existing strict builder accepts the full
  eight-step physical chain and `final_task_success=true`.
- Teacher use, model rollout, training, Q-B evaluation, and privileged truth
  as policy input are all forbidden in this batch.

## Task report

- Changed file: this operational pre-registration only.
- Tests: manifest identities and selected records are checked before every
  worker run by `run_path_blocked_collection_worker.py`.
- Failures: none observed for batch 02 at the time this document was written.
- Blocker entering the batch: 0 eligible PATH_BLOCKED training episodes.
- Next command: run a create-only dry-run for all three selected records, then
  execute them serially on Isaac GPU1 without changing the fixed contract.
