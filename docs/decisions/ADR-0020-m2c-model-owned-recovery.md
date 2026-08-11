# ADR-0020: M2C model-owned recovery under unchanged execution gates

- Status: Accepted for the bounded M2C experiment
- Date: 2026-08-12
- Human direction: execute `CODEX_GOAL_M2C_HEADROOM.md`
- Parent evidence: M2B commit `141e45dabddcaf59bb49ab958d9d5273d1f54d88`

## Context

M2B established valid prospective mapping and 30 physically executed model
decisions. On its frozen matched domain, B0 and QRM-Coarse-FC both reached a
final task success rate of 1.0. Every FC success still used fixed B0
continuation, so pure model-owned recovery remained zero and model gain over
B0 was not measurable.

## Decision

1. M2C first searches for a harder, physically recoverable evaluation domain.
   It may alter scenes and failure composition, but it may not weaken B0,
   reduce retries, loosen gates, or redefine success.
2. Q-B work is gated on B0 final task success below 0.8 on frozen matched
   keys, plus a successful human or scripted recovery proving recoverability.
3. Only after Q-A passes may the coarse model own the complete recovery chain.
   It selects one registered skill at a time, execution passes the unchanged
   schema, track, frame/unit, range, IK, collision, controller, and safety
   gates, and the system obtains a new public observation before replanning.
4. An invalid or rejected decision still falls back to B0. Any episode with
   B0 fallback, fixed B0 continuation, or human intervention after the first
   failure is excluded from `pure_model_success_episode`.
5. `fc_gain_over_b0`, not NoFC-vs-FC alone, is the primary M2C comparison.
6. M2B reports and artifacts remain read-only. The B0 implementation,
   parameters, retry count, runtime registry, transforms, and gates are frozen
   by `configs/m2c_b0_freeze.json` and checked before every formal stage.

## Runtime and action protocol

Coarse outputs use the versioned `CoarseIntentV1` registry. Every runtime
action declares its frame, units, required parameters, supported task phase,
and fallback in `configs/qrm_runtime_mapping.yaml`; mappings are never guessed.
The optional residual protocol remains 10-D
`[dx,dy,dz,r6d_0..r6d_5,gripper]`, `camera_optical`, `m_rad_norm`, 1 Hz,
horizon 1, with no normalization. M2C does not activate residuals until S5.

## Information boundary

Policy inputs are public RGB-D, public tracks, robot state, TaskSpec, and
FailureContext. Entity or prim identity, perfect pose, contacts, injection
truth, and task-success truth remain training/evaluation labels and may not
enter test-time selection. A re-observation is required after each executed
recovery skill.

## Governance scope

This human-directed ADR authorizes only the bounded M2C experiment. It does
not replace the mandatory world-model mainline, B0 delivery fallback, or any
safety/controller component, and it does not authorize a mainline merge.

## Teacher boundary and kill rules

Teachers are unused. Nano remains `CANDIDATE`, BWM remains
`CANDIDATE_LICENSE_PENDING`, and Super remains `PARKED`. The affected run is
killed if Teacher soft labels enter Student training/evaluation, a Teacher
adapter or response enters the control stack, or a Teacher is silently
replaced or upgraded. Current Teacher kill-rule events: **none**.
