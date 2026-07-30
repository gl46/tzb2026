# ADR-0017: Dual RTX 3080 Isaac data engine for M2A

- Status: Accepted for M2A
- Date: 2026-07-31
- Human direction: execute the new M2A goal
- Baseline: `codex/m1b-beta-closed-loop` at `5984298`

## Context

M1B has a verified Isaac Sim 6.0.1 migration using NVIDIA's official Franka
asset and a public RGB-D / offline SimulatorSupervision boundary. M2A needs a
versioned data path without consuming A100 training capacity or weakening that
boundary.

## Decision

1. `root@labserver` generates Isaac data on two physical RTX 3080 GPUs.
2. One independent Isaac process owns each GPU. The GPUs are not treated as
   pooled memory.
3. Kit initialization is serialized. Both workers enter a shared START barrier
   before concurrent capture.
4. Every worker receives disjoint scene seeds and writes a distinct raw root.
5. Raw frames remain local until Canonical episodes pass validation.
6. Shards move only `WRITING -> VALIDATING -> READY -> SYNCED`; failures move
   to `QUARANTINED`.
7. Only READY shards may be synchronized to the A100 host.
8. Scene seed is the split group. Adjacent transitions never cross splits.
9. Isaac is a physics environment and data engine, not an online learned
   future-video model.

## Non-Oracle boundary

Runtime RGB-D, calibration, named robot state, public tracks and task fields
are policy-visible. Prim paths, entity names, perfect poses, contacts and task
success remain under `simulator_supervision.training_and_evaluation_only`.
File names and public track IDs are audited for entity leakage.

## Consequences

- Dataset version: `isaac-industrial-v1-pilot`.
- Default data root is outside Git.
- A cold-start failure may be retried only if it produced no hash-valid output.
- Retried Isaac launches use a measured 120-second driver/container settle
  window; failed pre-READY attempts are retained and never overwritten.
- Throughput reports retain crash/restart counts and do not discard semantic
  failures.

## Teacher boundary and kill rules

No Teacher participates. Nano remains `CANDIDATE`, BWM remains
`CANDIDATE_LICENSE_PENDING`, and Super remains `PARKED`. Teacher kill-rule
events for this ADR: **none**, because no Teacher is loaded or called.
