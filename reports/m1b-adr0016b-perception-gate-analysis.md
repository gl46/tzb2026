# M1B perception p90 gate — structural analysis (ADR-0016b franka hand)

Status: **NO_GO is measured, not unmeasured; Z axis is the structural blocker.**

The gate (`src/xh_agent/grasp/tolerance_envelope.py`) is, per axis,
`p90_error ≤ 0.6 × measured_tolerance`. With the ADR-0016b envelope
(X 0.015 / Y 0.015 / Z 0.005 m) and the actual-Gazebo RGB-D perception p90
(`reports/m1b-alpha-perception-metrics.json`, 235 matched tracks):

| axis | envelope | gate threshold (0.6×) | measured p90 | over by | reduction needed |
| --- | --- | --- | --- | --- | --- |
| x | 15.0 mm | 9.0 mm | 9.88 mm | 0.9 mm | 9 % |
| y | 15.0 mm | 9.0 mm | 15.13 mm | 6.1 mm | 41 % |
| z | **5.0 mm** | **3.0 mm** | **17.30 mm** | **14.3 mm** | **83 % (5.8×)** |

## Can near-pregrasp reobservation close it?

`--enable-near-pregrasp-reobservation` (already coded in
`run_m1b_tolerance_trial.py`) captures 3 fresh public RGB-D frames at pregrasp
(~0.30 m from the target) and re-estimates the centre, versus the fixed
overhead camera at ~1.0 m. Moving ~3× closer improves triangulation-limited
error roughly proportionally but leaves the depth sensor's distance-independent
floor:

- **x, y (lateral)** need 9 % and 41 % reductions — plausibly within reach of
  a 2–3× lateral-error improvement from the closer frames.
- **z (depth)** needs a **5.8× (83 %)** reduction, from 17.3 mm to 3.0 mm.
  RGB-D depth error does not shrink 5.8× by moving 3× closer, so **the Z gate
  is not closable by reobservation alone.**

## The Z blocker is dual, and the real lever is the descent, not perception

Z is doubly constrained: a **large depth p90 (17.3 mm)** against a **tight
5 mm Z tolerance**. The 5 mm envelope is itself an artifact of the fixed-height
top-down descent — the campaign Z sweep is asymmetric and fails on the
positive side first (`+0.010 → 1/3`, `−0.010 → 3/3`). The measured failure mode
at `+0.010` is **unilateral contact** (693–729 post-close samples on the right
pad only, zero on the left): a perceived-high target offsets the fixed descent
height directly, so one pad engages the cylinder before the other and the close
never forms a bilateral window.

The structural fix is therefore to **widen the Z tolerance with a
contact-seeking descent** (descend until the finger-contact window opens rather
than to a fixed hand height), which makes the grasp Z-tolerant across the
cylinder's 80 mm sidewall and raises the Z envelope — and with a larger Z
envelope the `0.6×` threshold grows enough that the current depth p90 can pass.
Near-pregrasp reobservation then closes the modest x/y margins.

## Recommended sequence (follow-up, not done here)

1. Add a contact-seeking terminal descent to the top-down primitive; re-run the
   Z-axis campaign to measure the widened Z envelope.
2. Generate reobservation-enabled perception metrics (capture at pregrasp over
   the eval set) and re-audit x/y p90.
3. Re-run the gate against the widened envelope + reobserved p90.

Neither lever is another hand iteration; the ADR-0016b hand's grasp envelope
is nonzero and measured. This is a perception-accuracy / descent-tolerance
problem, cleanly separated from the topology work.
