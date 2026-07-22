# ADR-0016: Inline hand topology — fingers along the tool axis

Date: 2026-07-20 (Asia/Shanghai)
Status: **APPROVED — implementation authorized by project owner in Codex conversation**

## Diagnosis: one topology defect explains every grasp-geometry failure to date

In the current model the finger prismatic joints sit at mid-palm height
(`origin 0 0 0.055`) and the pads extend along **+x_hand**, sideways out of
the palm. The real Panda hand extends its fingers along **+z_hand** — the tool
axis — so wrist, palm and fingers are colinear. Ours is an orthogonal fork.
Consequences, all previously measured:

1. **NOTE-0007 (M1A)**: level side grasps are impossible near the table —
   the palm extends 55 mm below the finger axis. Root cause: fingers attached
   mid-palm, a direct artifact of the sideways topology.
2. **M1A top-down family**: pointing x̂_hand down forces ẑ_hand (the wrist
   approach axis) horizontal — a contorted crane configuration whose IK is
   feasible only in a narrow pocket. M1A succeeded because the single cube sat
   inside that pocket; this was survivorship, not generality.
3. **M1B 81-point envelope (post-ADR-0014 hand)**: 69/81 trials fail with IK
   −31 at the final-contact descent; the ADR-0015 whole-field elevation scan
   (0–100 mm, 8 candidates) found **no elevation with a feasible terminal
   pose** — elevation cures palm–table interference but not wrist contortion,
   which is exactly the discriminating signature of the topology defect.
4. RGB-D is not the blocker: real-frame p90 is X 7.0 / Y 12.1 / Z 12.2 mm.

Pad slimming (ADR-0014) was necessary but attacked clearance, not topology.
No orientation family, elevation, or parameter can make the natural pose
natural while the fingers point sideways.

## Decision requested

### 1. Inline hand topology (robot model change)

- Palm becomes a compact block between wrist and fingers (collision ≈
  70×60×60 mm, hand frame z ∈ [0, 0.06]).
- Finger prismatic joints move to the palm's distal face
  (`origin 0 0 0.06`); prismatic axes stay **±y_hand** (closing direction
  unchanged).
- Pad boxes re-orient to extend along **+z_hand**: main pad 0.08 long,
  0.010 thick (y), 0.022 wide (x), plus the existing 0.02 tapered tip —
  fingertips reach hand-frame z ≈ 0.16.
- **Unchanged contracts**: joint names, `[0, 0.04] m` limits, metres,
  q2-master mimic (ADR-0008/0009), controller/action interfaces, broker
  boundary (ADR-0011/0013), contact-sensor topic names (sensors re-bind to
  the re-oriented collision elements; collision element names retained).
- Hand mount yaw −π/4 on `panda_link8` retained (Panda convention).

### 2. Primitive consolidation

- **Primary and only M1B pick family: top-down vertical tool axis**, yaw
  selected from the perceived free-gap direction. With inline topology this
  is the canonical Panda configuration — the pose every real Panda tabletop
  deployment uses — and is expected to be IK-feasible across the validated
  annulus.
- The horizontal side-grasp family is **retired** for M1B (the NOTE-0007
  zombie). Tilted-tool variants may return later for special cases via their
  own measured feasibility scan.
- Note: a lying (tipped) cylinder is grasped across its diameter by the same
  top-down family; inverted equals normal for the pick phase. One family is
  expected to cover all three pose classes for picking; pose correction is a
  placement-phase concern.

### 3. New permanent gate: orientation-feasibility pre-scan

The FK reachability gate validated **position** density only; zones passed
while every grasp **orientation** at them was infeasible. Scene generation
must additionally verify per spawn point and per bin cell:

1. collision-free IK exists for the vertical-tool **pregrasp** pose and the
   **final-contact** pose in an empty scene (pure kinematic feasibility); and
2. the same poses remain feasible with the populated scene (corridor
   feasibility), recording both results separately so wrist infeasibility and
   clutter blockage are never conflated again.

Scene generation fails closed on either check.

### 4. Pre-authorized fallback (no fourth round-trip)

If the inline topology still yields a zero envelope on any axis, the next
step is **not** another homemade iteration: replace the hand with a
primitive-approximated copy of the official `franka_description` hand
geometry (same joint contract), i.e., stop designing hands and copy the
reference. This fallback is approved together with this ADR and carries the
same revalidation cascade.

## Mandatory revalidation cascade (in order, all scripted)

1. Home self-collision gate on the new model;
2. S0 13-condition contact calibration (finger collision geometry moved);
3. S1 ten-trial MoveIt execution gate (model hashes update);
4. Orientation-feasibility pre-scan over the current scenes (gate 3 above);
5. One zero-offset real grasp: approach → descent → bilateral same-entity
   contact → attach (first-ever live proof for this scene);
6. 81-point envelope re-run — nonzero per-axis envelopes required;
7. Perception p90 gate: per-axis p90 ≤ 0.6 × envelope;
8. ADR-0013 acceptance 3 (round-trip) and 4 (wrong-object drill);
9. M1A cube regression re-run under the new hand.

## Approval record

- Human approver: **project owner, approved in Codex conversation on 2026-07-20**
- Inline hand topology: **APPROVED**
- Side-grasp retirement / top-down consolidation: **APPROVED**
- Orientation-feasibility pre-scan gate: **APPROVED**
- Pre-authorized franka-geometry fallback: **APPROVED**
- Implementation SHA: **`7bca346`** (`feat: adopt ADR0016 inline top grasp topology`)
- Measured follow-up: `reports/m1b-adr0016-top-contact-height-calibration.json`
  selects the 120 mm top-contact centreline from physical zero-offset probes;
  it does **not** satisfy the required 81-trial envelope or perception gate.
- Completed revalidation: the 81-trial campaign is recorded in
  `reports/m1b-adr0016-tolerance-envelope.json` (summary SHA-256
  `bb602416012693c3225de9e342f35ee29bd049c8bc3072ffa74f50d9ec335a3d`).
  Zero-offset success was X/Y/Z = 0/3, so every signed-monotonic envelope is
  unmeasured. The actual RGB-D p90 comparison is **NO-GO** in
  `reports/m1b-adr0016-perception-reachability-gate.json`; ADR-0013
  acceptance items 3 and 4 remain unrun.

## §4 fallback executed (2026-07-22 → 07-23)

The inline hand's 81-trial campaign yielded a zero envelope on every axis —
exactly the pre-authorized §4 trigger. The fallback (primitive-approximated
copy of the official `franka_description` hand geometry, same joint contract)
was implemented and revalidated; full detail and per-step evidence in
`reports/m1b-adr0016b-franka-hand-fallback.md`.

Diagnosis of the inline campaign's 0/9 zero-offset failures found three
mechanisms, none of them the pad topology: a zero-force kiss-gap close, an
OMPL joint-space "descent" that bowed sideways and shoved the free target
10–18 mm, and slot-3 pregrasp IK −31 (the §3 scan's exact target). The
fallback build additionally had to compensate three measured
bullet-featherstone contact behaviours (first-collision-element-only physics
on the spawned multibody; a shallow-penetration dead band that rejects small
convex pads; a per-pair force-response lottery cured by a two-stage close).

Fallback revalidation result:
- Model URDF SHA-256 `6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8`.
- Gates 0–3 (bullet audit, home self-collision, S0 13/13, S1 10/10): **pass**.
- §3 corridor-extended pre-scan: scene 5017 admits 12/17 (slots 1/2/4 used);
  the r ≲ 0.27 m inner annulus fails the descent corridor — a scene-generation
  follow-up, tracked in the fallback report.
- Height/squeeze calibration: **120 mm centreline, 2 mm squeeze, two-stage
  close** (`reports/m1b-adr0016b-top-contact-height-calibration.json`).
- 81-trial envelope: **X 0.015 / Y 0.015 / Z 0.005 m** (nonzero on every
  axis — the §4 success criterion), summary SHA-256 `1e758295…`,
  `reports/m1b-adr0016b-tolerance-envelope.json`.
- Perception p90 gate: **NO-GO**, but now because measured p90 exceeds
  0.6×measured-envelope (worst on Z), not because the envelope is unmeasured
  — a perception-accuracy problem with an already-coded reobservation path.
- ADR-0013 acceptance 3 (round-trip): **pass**
  (`reports/m1b-adr0016b-attached-roundtrip.json`). Acceptance 4 (live
  wrong-object drill) remains; its logic is unit-verified.
- M1A cube regression: blocked on a dirty working tree (commit required).
- Unit suite 110/110, `validate_project` PASS.
