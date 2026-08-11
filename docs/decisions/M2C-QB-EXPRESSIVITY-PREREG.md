# M2C Q-B expressivity pre-registration

- Status: **pre-registered; Q-B blocked pending a human ADR**
- Authored: 2026-08-12 06:41 CST (Asia/Shanghai)
- Timing disclosure: this was written **after** observing V3 Q-A execution
  results, but **before any Q-B training or Q-B evaluation execution**. The
  observed V3 results were: seed 8018 B0 was rejected twice by the unchanged
  5 mm free-gap gate; seeds 8018 and 8038 safely relocated the blocker but did
  not complete the public target regrasp; seed 8039 had no selectable public
  yellow target. No statement below is represented as outcome-blind to V3.

## Pre-registered model-owned chain

Q-B may execute only one model-selected `CoarseIntentV1` at a time and must
re-observe before the next selection. The intended public-track chain is:

1. `GRASP(blocker_track_id, top_down)` and `LIFT(blocker_track_id)`;
2. `MOVE`/`PLACE`/`RELEASE` the same public blocker track into an explicitly
   registered safe destination, or use `SAFE_PLACE_NON_TARGET` only when its
   precondition (the non-target is already carried) is true;
3. `REOBSERVE`, then `REASSOCIATE_TARGET(task_target_track_id)`;
4. `REGRASP(task_target_track_id, top_down)` and complete the original task.

Every `target_track_id` must name a currently available public RGB-D track.
Entity/prim identity and perfect pose are forbidden policy inputs. Each step
must pass the existing schema, stale-track, frame/unit, IK, collision,
controller, and safety gates. Any B0 fallback or fixed continuation excludes
the episode from `pure_model_success_episode`.

## Expressivity audit and decision

The current schema has `skill_type` and `target_track_id`, and the runtime
adapter can validate a model-provided public track. The end-to-end learned
path is nevertheless insufficient:

- `decode_coarse_intent()` does not predict a track pointer, so formal Q0/Q1/Q2
  outputs leave `target_track_id=None`; the adapter then falls back to the task
  target and cannot select a resting blocker.
- `MOVE`, `PLACE`, and `SAFE_PLACE_NON_TARGET` declare an optional
  `destination`, but `CoarseIntentV1` has no destination/cell field and the
  adapter does not materialize one. No official bin-cell enum is registered.
- `SAFE_PLACE_NON_TARGET` is evidenced for an already-carried wrong object; it
  is not an approved semantic alias for grasping and clearing a blocker from
  the scene.

Therefore the existing model-to-runtime path cannot express the full chain
without guessing a target or destination. **No new label or mapping is
approved by this document, and Q-B remains blocked even if Q-A passes.** A
separate human ADR must be committed before any Q-B evaluation execution. It
must choose and fully specify either (a) a versioned intent with an explicit
public-track pointer plus registered destination-cell enum while retaining the
existing primitive skills, or (b) a new blocker-clearing skill with the same
explicit fields. The ADR must pin frame, units, dimensions, frequency,
normalization, public information boundary, runtime mapping, and unchanged
pre-execution gates; no action mapping may be guessed.

Before Q-B execution, tests must prove that the model—not TaskSpec fallback—
selects the blocker track, the safe destination resolves from a registered
public contract, every chain step is model-owned and actually executed, and a
fresh public observation gates each next decision. Teachers remain unused;
Nano/BWM/Super states and kill rules are unchanged.
