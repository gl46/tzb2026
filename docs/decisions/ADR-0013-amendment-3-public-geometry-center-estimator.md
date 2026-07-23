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
