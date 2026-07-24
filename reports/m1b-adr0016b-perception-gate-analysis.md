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

---

## Addendum (2026-07-24): both premises of the analysis above have changed

This analysis was written against perception metrics measuring p90 X/Y/Z =
9.88 / 15.13 / 17.30 mm. Both of its inputs have since been superseded, and the
conclusion it reached — "Z needs a 5.8× depth-error cut that reobservation
cannot deliver" — is no longer the operative problem.

**1. The perception side was fixed, and it was not sensor accuracy.** The
17.30 mm Z p90 was a measurement artifact of cross-contaminated RGB-D capture,
not a depth-sensor limit. Isolating each capture into its own world and process
group (`fix: isolate each M1B RGB-D capture world`, `fix: isolate RGB-D capture
process groups`) and re-gating centres on public geometry brought the
current-geometry held-out p90 to **2.295 / 4.793 / 2.080 mm** — a 4–8× drop,
which no amount of moving the camera closer would have produced. The gate is
now measured `GO` (`reports/m1b-adr0016b-current-geometry-reachability-gate.json`).

**2. The recommended contact-seeking descent was implemented and measured-
rejected.** Its bounded zero-offset probe reached the 120 mm baseline and staged
115 and 110 mm, but all 223 contacts were left-finger-only and 105 mm was
rejected by IK −31; the broker correctly withheld close and attach
(`docs: record rejected M1B contact-seek probe`).

**3. What actually remained was the envelope side of the same ratio.** With the
perception numerator fixed, the gate passed but only by **0.92 mm** on Z
(`0.6 × 5 mm = 3.0 mm` limit vs 2.080 mm p90). Since the gate is a p90
statistic while a grasp needs per-trial accuracy, a sub-millimetre margin still
leaves a meaningful fraction of individual trials outside tolerance — which is
precisely the "acceptance passed when recorded, will not replay stably" gap.

The resolution is in `reports/m1b-adr0016b-z-envelope-geometry.md`: the 5 mm Z
envelope was two hard geometric bounds (palm-vs-cylinder-top below, plate-tip
tipping above) whose opposite sensitivity to the contact centreline meets at
**118 mm**, not the 120 mm in use. Re-deriving that constant doubles the
measurable envelope and takes the Z margin to ~3.9 mm. So the lever was neither
perception accuracy nor a new descent primitive — it was one geometry constant.
