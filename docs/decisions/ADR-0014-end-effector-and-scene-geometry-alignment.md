# ADR-0014: End-effector and scene geometry alignment for graspable industrial cylinders

Date: 2026-07-19 (Asia/Shanghai)
Status: **ACCEPTED**

## Context: the measured impossibility

The 81-point tolerance-envelope experiment returned a **zero envelope on all
three axes**, with honest attribution: the current parallel fingers cannot
simultaneously satisfy MoveIt reachability, no-disturbance descent, and
bilateral contact. The measured geometry explains this exactly:

- Cylinder diameter **50 mm** (`CYLINDER_RADIUS_M = 0.025`), length 90 mm.
- Maximum gripper width = q1+q2 − pad thickness = 80 − 18 = **62 mm**.
- Per-side lateral budget at full opening: (62 − 50)/2 = **6 mm** — below the
  descent's own disturbance, so a zero envelope is the *correct* measurement,
  not an experimental failure.
- Measured perception p90: X 9.9 / Y 15.1 / Z 17.3 mm — 2.5× the lateral
  budget even before mechanics.
- The M1A cube (also 50 mm) never exposed this because its acceptance ran on
  oracle-quality poses; the envelope experiment was the first honest tolerance
  measurement of the primitive.
- Additional finding: `blue_partition_bin` is centered at `[0.36, 0, 0.45]`
  with a 0.42 m floor; its far cells lie up to **0.92 m** from the base —
  beyond the 0.855 m absolute Panda reach (ADR-0006 kinematics). Part of the
  reachability failures are on the *placement* side, independent of the hand.

Parameter tuning cannot fix a 6 mm budget. This ADR requests three coordinated
geometry changes, each sized from the measurements above.

## Decision requested

### 1. End-effector geometry revision (robot model change)

- Finger pad boxes: thickness 18 → **10 mm**, width 35 → **22 mm**, with a
  tapered tip section (final 20 mm tapering to ≈6 mm) to reduce descent
  disturbance in dense regions; pad length may shorten to 100 mm.
- Palm collision box: 100×80 → ≈**70×60 mm** cross-section (height may stay).
- Resulting maximum width: 80 − 10 = **70 mm**.
- **Unchanged contracts**: joint names, `[0, 0.04] m` limits, metres,
  controller/action interfaces, q2-master mimic (ADR-0008/0009), broker
  boundary (ADR-0011/0013). Contact sensors re-bind to the new collision
  names with **unchanged topic names**.

### 2. Scene realism correction (scene change)

- Cylinder diameter 50 → **30 mm**, length 90 → 80 mm, mass 60 → 45 g. This
  matches the official Q&A example imagery (slim metal pins in dense trays)
  better than the current cube-width cylinders, and is a correction toward
  the benchmark's intent, not away from it.
- Scenes and manifests regenerate; the perception audit MUST be re-run on the
  new object size (smaller targets may worsen p90 — the GO criterion is
  unchanged and re-measured, never assumed).

### 3. Reachability-constrained layout (scene change)

- Every incoming-zone spawn point and **every bin cell center** must pass the
  FK-based reachability gate (reuse the ADR-0006 sampler /
  `evaluate_m1b_reachability_gate.py`) before a scene is valid.
- The partition bin moves/rotates so all cells lie inside the validated
  annulus (indicatively: center near 0.55 m radial distance, long axis
  tangential).
- Scene generation fails closed on an unreachable cell.

### Margin model after the change set

| Configuration | Max width | Object | Per-side budget |
| --- | ---: | ---: | ---: |
| Current | 62 mm | 50 mm | 6 mm |
| New hand only | 70 mm | 50 mm | 10 mm |
| New hand + 30 mm cylinder | 70 mm | 30 mm | **20 mm** |

20 mm budget vs re-measured p90 (expected 10–18 mm with the mandatory
pregrasp close-range re-observation) is the first configuration where a
nonzero envelope and a GO are physically possible.

### 4. Placement primitive: drop-in release

- Placing into a partition cell while gripping requires cell width ≥ object +
  2×pad thickness; with current cells this is marginal. The place primitive
  is authorized as **drop-in release**: release 10–20 mm above the cell rim,
  then verify settle **inside the cell bounds** (adapted M1A release gate:
  explicit open, detach deadline, in-cell settle ≥ 1 s, no rigid follow).

## Mandatory revalidation cascade (in order, all scripted)

1. Home self-collision gate on the new model;
2. S0 13-condition contact calibration (sensors on new collision geometry);
3. S1 ten-trial MoveIt execution gate (model hash updates);
4. **81-point envelope re-run** — must now produce a nonzero per-axis
   envelope; if any axis remains zero, stop and return to the human with the
   recorded interference report (no silent iteration);
5. Perception re-audit on 30 mm objects (fresh p90);
6. GO/NO-GO: per-axis p90 ≤ 0.6 × envelope;
7. ADR-0013 acceptance 3 (round-trip) and 4 (wrong-object drill);
8. M1A cube regression re-runs under the new hand (historical M1A evidence
   stays valid for its recorded SHA; the regression must pass fresh, not be
   assumed).

## Approval record

- Human approver: **Project owner, 2026-07-19**
- End-effector geometry revision: **APPROVED**
- Cylinder 30 mm scene correction: **APPROVED**
- Reachability-constrained layout (incl. bin relocation): **APPROVED**
- Drop-in release placement primitive: **APPROVED**
- Implementation SHAs: `7e7f398` (hand/cylinder geometry) and `1bae81d`
  (FK-gated layout and complete standalone scene geometry)
