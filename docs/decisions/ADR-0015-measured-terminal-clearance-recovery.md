# ADR-0015: Measured terminal-clearance recovery

Status: **APPROVED FOR CALIBRATION MEASUREMENT ONLY**

## Context

ADR-0014's 30 mm configuration completed its 81-trial revalidation with no
measurable tolerance envelope. The measured blocker is terminal path
feasibility: 69 contact-descend IK failures, table interference, and no
bilateral same-entity contact. The existing horizontal, lateral, and
vertical-board pose families do not provide a promotable path.

## Decision

1. Run a reset-isolated, no-attach calibration scan of target-height and
   terminal-clearance candidates. It must update the evaluator-only planning
   scene consistently with every virtual target height and record IK and
   collision-checked planning outcomes from reset home.
2. Derive the minimum production elevation and required clearance margin from
   that scan. No fixed pedestal, scene height, finger geometry, or runtime
   primitive dimension is authorized before the result exists.
3. The first physical follow-up may exercise only the selected candidate in a
   calibration-only scene. It must preserve table and non-target collision
   checks, record both-finger contact identity, and perform no acceptance
   attach/transport claim.
4. A candidate is promotable only after a nonzero 81-trial production-primitive
   tolerance envelope and the unchanged p90 reachability gate pass. Only then
   may ADR-0013 acceptance items 3 and 4 run.

## Invariants

- Supervision remains calibration-only; it never enters online planning,
  contact selection, or policy observation.
- Reset physical non-coupling, bilateral same-entity selection, and all gate
  thresholds remain unchanged.
- No value may be selected because it makes a demo pass; every production
  dimension carries scan evidence and a declared margin.

## Evidence inputs

- `reports/m1b-adr0014-tolerance-envelope.md`
- `reports/m1b-adr0014-interference-report.md`
- `reports/m1b-adr0014-perception-reachability-gate.json`

## Approval

Project owner approved ADR-0015 calibration measurement and the ensuing
measurement-derived implementation in the Codex conversation on 2026-07-19.
