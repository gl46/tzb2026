# ADR-0013 Amendment 3: Public-RGB-D geometry centre estimator

Date: 2026-07-24 (Asia/Shanghai)  
Status: **APPROVED — project owner authorized the next remediation in Codex conversation**

## Context

The ADR-0016b tolerance envelope is measured (X/Y/Z = 15/15/5 mm), but the
old p90 input cannot be used for the current gate: its captured frames contain
the superseded 50 mm × 100 mm cylinder, while ADR-0014's current production
scene contains the 30 mm × 80 mm cylinder.  Reusing that evidence would make a
GO/NO-GO comparison geometrically invalid.

The baseline public estimator also converts every visible surface point by one
camera-axis radius.  That is a deliberately conservative starting point, but
it does not use two already-public geometric measurements: the RGB-D support
plane under the component and the component's surface geometry.  No simulator
service, object pose, entity identity, or supervision field may enter the
runtime replacement.

## Decision

1. Capture a fresh, seed-disjoint current-geometry RGB-D corpus.  It contains
   200 real Gazebo scenes, with the generator's 140/30/30 train/val/test split;
   p90 is reported only on the 30 held-out test scenes.  Every capture uses a
   private Gazebo partition and ROS domain, and process-group cleanup must
   leave no prior-world camera publisher alive.
2. The runtime centre estimate remains rooted in the public RGB-D surface,
   perceived diameter, and versioned static TF from ADR-0013.  A frozen
   two-output affine residual may correct its world X/Y coordinates only when
   fitted on the *training* split.  Its features are public optical surface
   XYZ, perceived diameter, and the public orientation classifier output.
   The fitted input SHA-256, feature order, coefficient bounds, and model
   fingerprint are recorded.
3. The runtime Z coordinate is reconstructed from the public RGB-D support
   plane at the component centroid plus the versioned industrial-cylinder
   class support offset.  The offset is bounded by the 30 mm × 80 mm class and
   the approved tilt range; it is not read from a per-object label.  Missing,
   non-finite, or out-of-workspace support geometry fails closed.
4. Simulator supervision may be used only by the offline trainer/evaluator.
   The runtime trial records the two correction fingerprints and public
   geometry provenance, but not supervision values.  The public orientation
   classifier is never replaced by an evaluator orientation label.

## Revalidation

1. Verify the capture isolation probe (one real frame, no surviving bridge);
2. Fit only on fresh train frames and archive the fitting input hash;
3. Audit all fresh held-out frames against supervision offline, with no
   exclusions other than explicitly recorded invalid public geometry;
4. Apply the unchanged `p90 <= 0.6 × measured envelope` rule to the existing
   81-trial envelope;
5. Only `GO` permits fresh ADR-0013 round-trip and WRONG_OBJECT drills.

No gate threshold is relaxed by this amendment.

## Measured revalidation (2026-07-24)

The approved revalidation was executed on a fresh current-geometry corpus:

- Manifest `data/manifests/m1b-adr0016b-public-captured-r2.json`
  (SHA-256 `20818a05f40141edf4ec6258b46470d291736de7bbe6067a645afb4cf66f3919`)
  records 200 real Gazebo frames with the required 140/30/30 split.
- The frozen training-only X/Y correction is
  `configs/m1b_public_geometry_xy_correction.json`
  (SHA-256 `1347fddea4af627b1df928138d0540a651971f2fca1aa31f8f94b97ff8ef58da`).
- The held-out audit
  `reports/m1b-adr0016b-current-geometry-perception-metrics.json`
  (SHA-256 `bfe89ead610ca6a9f7e3c00a72f9a30e79bfb1af655617bb8de4ca2c088f9e5a`)
  evaluated 30 scenes and 272 matched instances with zero exclusions. Its
  all-instance absolute-error p90 is X/Y/Z = 2.295 / 4.793 / 2.080 mm.
- The 81-trial ADR-0016b measured tolerance envelope is X/Y/Z =
  15 / 15 / 5 mm, so the unchanged 0.6 limits are 9 / 9 / 3 mm. The resulting
  gate is **GO**, recorded in
  `reports/m1b-adr0016b-current-geometry-reachability-gate.json`
  (SHA-256 `e38301e28ae0a5bbab9bbd9c5e764403f526f4cd7d21c9f1f933e0d36d311e27`).

This GO authorizes only fresh, public-perception-driven ADR-0013 acceptance
3 (round-trip) and acceptance 4 (WRONG_OBJECT). The superseded 50 mm × 100 mm
audit and its diagnostic acceptance artifacts remain non-acceptance evidence.

## Fresh ADR-0013 acceptance evidence (2026-07-24)

Status: **PASS — acceptance 3 and 4 completed after the measured current-
geometry GO.**

Acceptance 3 is recorded in
`reports/m1b-adr0013-current-geometry-attached-roundtrip.json` (SHA-256
`30c103a07e9dbfdeb388a3c6315365e5adaf55937da02053cb3871756addac35`). The
production grasp was selected from public RGB-D track `track-349bcd6a`. Only
after the broker physically attached did the evaluator mirror the corresponding
**public** collision ID into MoveIt. Attached motion moved the link/object
28.523 / 28.503 mm with 0.0077 mm relative drift; detach was observed and the
post-detach decouple moved 34.511 mm relative to the released object. The
reset physical non-coupling input is SHA-256
`163c11ba555d4b151070f767f8d05bef653205277bd698c95b31382d34fd7861`.

Acceptance 4 is recorded in
`reports/m1b-adr0013-current-geometry-wrong-object-drill.json` (SHA-256
`8aedf30cdfacd135ac3f193cf25dd4f05f5044ccb48ed0b20a6dda0464f25626`). A
public pre-actuation task target (`track-edec3eae`) was deliberately not the
public commanded target (`track-349bcd6a`). The broker honestly attached the
non-target. A public-only, collision-checked 100 mm lift followed by a
collision-checked home observation retreat exposed the table without a detach.
Across three post-grasp public RGB-D observations, `track-349bcd6a` was the
unique persistent vacancy. The online public identity decision was therefore
`WRONG_OBJECT`, and it triggered
`Reobserve → SafePlaceNonTarget → ReassociateTarget → Approach → Regrasp`
before supervision was read. Evaluator scoring subsequently recorded
`wrong_object=true`.

The production public-lift evidence has no simulator-entity input and no
detach command; its source SHA-256 is
`59f1ae4277d40ff0fcc5a4f44142ed818b8e634d00948dfa4c032b9dbafc3628`.
