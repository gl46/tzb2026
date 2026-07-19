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

## Initial height-scan result and correction (2026-07-19)

The reset-isolated, no-motion scan evaluated target lifts of 0, 10, 20, 30,
40, 60, 80, and 100 mm with the virtual cylinder collision scene updated at
each candidate. Contact-pose planning first succeeded at **30 mm**; 20 mm had
an IK solution but no plan. It initially selected **40 mm**: the first feasible
30 mm cell plus one 10 mm scan-resolution margin. The scan source is
`/tmp/m1b-adr0015-height-scan-20260719/raw/trial-000.json`; it executed no
grasp motion, close, attach, or transport.

That initial scan moved only the target collision object virtually. A physical
40 mm pedestal necessarily moves every cylinder, so the initial result was not
geometry-equivalent to the physical fixture and is **not** a promotable
production dimension. The isolated physical follow-up,
`reports/m1b-adr0015-pedestal40-followup.json`, verified reset non-coupling and
executed/converged the pregrasp, but the contact descend still failed IK (-31);
there was no close, bilateral contact, or attach. The height scan now translates
the entire collision fixture for every candidate. It must be rerun before any
further physical candidate or 81-trial campaign is authorized.

## Approval

Project owner approved ADR-0015 calibration measurement and the ensuing
measurement-derived implementation in the Codex conversation on 2026-07-19.
