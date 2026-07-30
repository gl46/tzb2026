# M1B Z-envelope: two hard geometric bounds, and a noise-dominated measurement

Status: **candidate centreline NOT adopted; the model is untested by this
experiment; the protocol is the limiting instrument.**

> **Correction (supersedes the previous header of this file).** The previous
> version of this section claimed the 81-trial campaign at 118 mm "confirmed the
> geometric model on every binding point," citing the +10 mm Z grid point going
> 4/6 → 6/6. **That claim is withdrawn.** The two campaigns differ in six
> variables, not one: the centreline *and* all five reliability fixes. The H120
> raw evidence records `calibration_hand_y_centerline_bias_m = 0.001` (fixes
> absent); the H118 campaign records `0.0` (fixes active). The fixes alone can
> produce a 4/6 → 6/6 move, so no per-band difference between the two runs is
> attributable to the 2 mm centreline change. Worse, *every* run that validated
> the five fixes executed while the constant was 118 mm (set 07:43, reverted
> 13:23), so the shipped configuration — 120 mm with the fixes — had never been
> measured. Campaign v3 supplies that missing cell. Detail:
> `reports/m1b-adr0016b-centreline-118-campaign.json` → `confounded_comparison`.

What survives the correction, and why the revert still stands: the *official*
signed-monotonic closure got **worse** on Z (5 mm → 0 mm) at 118 mm, because the
+5 mm point drew one descent-corridor rejection and one single-sided contact —
two independent ~1-in-6 events on one grid point — and the closure truncates
there. Total Z reliability was statistically unchanged (15/27 → 16/27).
**The production centreline is therefore reverted to 120 mm**, the value the
committed acceptance rests on: adopting 118 mm against the project's own metric,
on a physical justification this experiment did not isolate, would trade a
certified GO for a noise draw. One model prediction does survive as a
consistency check — −15 mm still fails 0/3, and a geometric interference bound
cannot be lifted by a reliability fix.

The reported envelope moving *opposite* to the continuous contact-window metric
(Z passing-window median 352 ms → 799 ms, replayed over all 162 trials with
162/162 verdict reproduction) is the clearest available evidence that the
measurement protocol, not the hardware, is the binding constraint — though that
comparison carries the same confound. Raising per-trial reliability needs no ADR
and is the cheap lever; changing the repetition count or the closure rule is an
ADR-level decision and is not taken here. The full arithmetic, and why the
reliability lever beats the repetition lever by an order of magnitude in cost,
is in `reports/m1b-adr0016b-closure-reproducibility.md`.

> **Correction.** An earlier version of this paragraph described separating
> descent-corridor admission from grasp tolerance as something "§3 already
> requires." That is withdrawn as imprecise. §3 is a *scene-generation* gate —
> collision-free IK for the pregrasp and final-contact poses, empty scene and
> populated scene, recorded separately, per spawn point, failing closed on
> either. It says nothing about how the tolerance campaign scores a trial, and
> the campaign deliberately offsets the target by up to ±20 mm away from the
> pre-scanned spawn point, so an offset pose was never in §3's scope.
> Excluding pre-close failures from the tolerance denominator would be a **new**
> protocol decision, not the application of an existing requirement.

The immediate reliability defect found and fixed: a **+1 mm hand-chain bias
measured on the pre-ADR-0016 hand** was still being applied against a measured
**±2.5 mm** both-pad contact band, consuming ~40 % of the error budget for no
geometric reason.

The ADR-0016b campaign measured a Z tolerance envelope of only 5 mm (versus
15 mm on X and Y), which left the perception gate passing by just 0.92 mm
(`0.6 × 5 mm = 3.0 mm` limit vs measured p90 2.080 mm). That thin margin — not
perception accuracy — is what makes individual grasps unreliable and the
demo unstable. The 5 mm was assumed to be grasp-quality noise. It is not: the
Z axis is clamped by **two different hard geometric bounds, one per sign.**

## The model (all values from the committed URDF)

With `Rx(pi)` mapping the hand's local +Z to world-down, a point at hand-frame
local z maps to world `hand_z − z`:

| element | hand-frame local z | world extent (relative to hand) |
| --- | --- | --- |
| palm collision box (max +z) | 0.0660 | lowest palm point = `hand_z − 0.066` |
| grasp plate (`collision`) | 0.0584 … 0.1122 | `hand_z − 0.1122` (tip) … `hand_z − 0.0584` |

The target cylinder has half-length 0.040 m, so its top face is
`target_z + 0.040`. With contact centreline `H` and a Z target offset `δ`
(the planner's target is `δ` above the true centre), `hand_z = true_z + δ + H`:

- **Negative-δ bound — the palm hits the cylinder's top face.**
  `palm_bottom − cylinder_top = (H − 0.066) − 0.040 + δ ≥ 0`
  → **`δ ≥ 0.106 − H`**. At `H = 0.120` this is `δ ≥ −14 mm`.
- **Positive-δ bound — the plate rides too high and the free cylinder tips.**
  The plate tip sits at `H − 0.1122 + δ` above the centre; measured failures
  begin once that exceeds ≈ **+17.8 mm**, i.e. **`δ ≤ 0.130 − H`**. At
  `H = 0.120` this is `δ ≤ +10 mm`.

## The model reproduces every campaign Z result

| δz | palm−cylinder clearance @ H=120 | measured | failure mode recorded |
| --- | --- | --- | --- |
| −20 mm | **−6.0 mm (interference)** | 0/3 | all three: descent `CARTESIAN_JOINT_JUMP` / `WAYPOINT_IK` |
| −15 mm | **−1.0 mm (interference)** | 0/3 | all three: descent IK rejected |
| −10 mm | +4.0 mm | 3/3 | — |
| −5 mm | +9.0 mm | 3/3 | — |
| 0 | +14.0 mm | 2/3 | 1× unrelated reobservation gate |
| +10 mm | plate tip exactly +17.8 mm | 1/3 | 2× **single-sided contact** (693 / 729 samples on one pad) |
| +20 mm | plate tip +27.8 mm | 1/3 | 2× **single-sided contact** |

The negative side fails as a *collision-aware IK rejection* — the descent
cannot be planned at all — which is exactly how a palm/target interference
presents. The positive side fails as *single-sided contact* — the pads meet
the cylinder near its top, and squeezing that far above the centre of mass
tips the free body away from the first pad. Two different signatures, two
different bounds, both predicted by the geometry.

## Confirmation experiment

Raising the centreline must move the negative bound and nothing else. At
`H = 0.130` the same `δ = −15 mm` point has `+9 mm` clearance instead of
`−1 mm`:

| point | H = 120 mm | H = 130 mm |
| --- | --- | --- |
| z δ = −15 mm, slots 1/2/4 | **0/3** (all descent-IK rejected) | **3/3** — descent OK, bilateral contact (497/603, 197/823, 408/146), attach confirmed |

Run directory `node2:/tmp/m1b-z130-probe`. This is the predicted flip, and it
rules out grasp noise as the cause of the negative-side failures.

## The optimum centreline

The two bounds move in opposite directions with `H`, so the symmetric envelope
`E = min(H − 0.106, 0.130 − H)` is maximised where they meet:

```
H = (106 + 130) / 2 = 118 mm   →   δ ∈ [−12, +12] mm,  E ≈ 12 mm
```

| H | δ range | symmetric E |
| --- | --- | --- |
| 112 mm | [−6, +18] | 6 mm |
| 116 mm | [−10, +14] | 10 mm |
| **118 mm** | **[−12, +12]** | **12 mm** |
| 120 mm (current) | [−14, +10] | 10 mm |
| 130 mm | [−24, 0] | 0 mm |

Note the current production value of 120 mm is *not* the optimum: it buys
negative-side headroom the campaign never needed and pays for it on the
positive side, where the +10 mm grid point lands exactly on the tipping bound
(hence its 1/3). Because the campaign offset grid has 5 mm resolution, the
measurable envelope is quantised — passing ±10 mm requires
`H ∈ [116, 120] mm`, and 118 mm centres the margin at 2 mm on both bounds.

## Expected gate effect

| | envelope | gate limit (0.6×) | p90 | margin |
| --- | --- | --- | --- | --- |
| current (H=120) | 5 mm | 3.0 mm | 2.080 mm | **0.92 mm** |
| target (H=118) | 10 mm | 6.0 mm | 2.080 mm | **3.9 mm** (4.2×) |
| geometric ceiling | 12 mm | 7.2 mm | 2.080 mm | 5.1 mm (5.6×) |

The perception gate already passes; the point of widening Z is **per-trial
reliability**, which is what a stable demonstration needs. The measured
per-trial rate over the 81-trial campaign was 53/81 = 65 %, and its single
largest failure mode was single-sided contact (12 of 28 failures) — the same
mechanism as the positive-Z bound, and it is provoked by exactly this kind of
zero-margin geometry.

## Next lever if 12 mm is not enough

The palm bound comes from a collision box that is the **axis-aligned bounds of
the whole `hand.stl`**, which extends 7.6 mm past the finger root
(`local z 0.0584 → 0.0660`) and therefore fills the jaw channel the fingers
travel in. The physical hand is open between the fingers. Splitting the palm
into two boxes flanking that channel would move the palm bound by 7.6 mm
(`δ ≥ 0.0984 − H`), giving `H ≈ 114 mm` and `E ≈ 16 mm`. That is a robot-model
change and carries the full revalidation cascade, so it is recorded as the
next lever rather than taken here.

---

## Addendum: the envelope numbers are noise-dominated, and that is the deeper finding

The 118 mm revalidation was stopped after 22 of 81 trials because its partial
X-axis results exposed a problem with the measurement itself rather than with
the centreline:

| X offset | H = 120 mm (81-trial run) | H = 118 mm (partial run) |
| --- | --- | --- |
| −15 mm | 2/3 | 2/3 |
| −10 mm | 3/3 | 2/3 |
| −5 mm | 2/3 | **1/3** |
| 0 | 3/3 | 2/3 |
| +5 mm | 2/3 | **1/3** |
| +10 mm | 3/3 | 2/3 |
| per-trial | 65 % | 60 % |

A 5-point swing in per-trial reliability moved individual grid points across
the 2-of-3 threshold in both directions, and the ±5 mm failures would truncate
the monotone closure to **0 mm** — a *worse* X envelope than the 15 mm measured
at 120 mm, from a change that geometry says should barely affect X at all.

**The measurement is a lottery at this reliability.** With per-trial success
`p`, a 3-repetition point passes with probability `3p²(1−p) + p³`, and the
signed monotone closure needs four consecutive points (±5, ±10) to pass before
it can report 10 mm:

| per-trial p | single point passes | reports ≥10 mm | reports ≥15 mm |
| --- | --- | --- | --- |
| 60 % | 65 % | **18 %** | 7 % |
| 65 % | 72 % | **27 %** | 14 % |
| 70 % | 78 % | 38 % | 23 % |
| 80 % | 90 % | 64 % | 52 % |
| 90 % | 97 % | 89 % | 84 % |
| 95 % | 99 % | 97 % | 96 % |

So the original X = Y = 15 mm was a 7–14 % draw, and Z = 5 mm was an unlucky
one. **Envelope width is not the limiting quantity — per-trial reliability is**,
and it is also exactly what an unattended demonstration needs. This is the
mechanism behind the reported "acceptance passed when recorded, will not replay
stably": at ~65 % per trial, any particular replay is close to a coin flip.

### Where the unreliability comes from

Reliability is not uniform in offset, and it is not dominated by the large
artificial offsets alone (both runs pooled, 102 trials):

| ⏐δ⏐ band | per-trial success |
| --- | --- |
| ≤ 5 mm | **72 %** |
| 6–10 mm | 79 % |
| 11–15 mm | 67 % |
| 16–20 mm | 22 % |
| all | 64 % |

Production residual error is the current-geometry perception p90 of
2.3 / 4.8 / 2.1 mm, i.e. entirely inside the ≤ 5 mm band — where reliability is
still only 72 %. So even with perfect targeting roughly one grasp in four
fails, and that is the demo blocker.

Characterising every ≤ 5 mm failure (10 of them) gives:

- **5 single-sided contact** — and the descent barely moved the cylinder
  (0.5–1.2 mm, median 0.65 mm versus 0.58 mm on successes), so the target was
  essentially centred and one pad still never registered contact.
- 2 descent `CARTESIAN_JOINT_JUMP` (the separate IK-branch-fold issue),
- 2 bilateral contact achieved but attach unconfirmed (552/1384 and 199/1186
  samples) — an attach-publication issue, not grasp physics,
- 1 reobservation gate rejection.

### The error budget, and the 1 mm that was being wasted

At the close stall the collision gap is 25 mm against the 30 mm cylinder, so
**both pads register only while the target is within about ±2.5 mm** of the jaw
centreline. Against that budget the pipeline was still applying a **+1 mm**
`M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M` hand-chain correction measured on the
*pre-ADR-0016 sideways-pad hand*. For the franka-copy hand it is unjustified:

- **by construction** — both finger joints sit at origin `(0, 0, 0.0584)` with
  axes ±y and the two grasp-plate boxes are mirrored and equal-width, so the
  jaw midpoint is the hand `y = 0` axis;
- **by measurement** — the ADR-0009 hand probe's recorded link poses put the
  jaw midpoint at `y = −0.000416 m` at every commanded opening
  (`q = 0.01 / 0.02 / 0.04`), constant to within **5 µm**.

That correction was therefore consuming ~40 % of a ±2.5 mm budget for no
reason, and it is retired to zero. Its effect on reliability is measured
directly against the same nine small-offset trials.

### Measured effect of retiring the bias, and what it exposed underneath

The same nine small-offset trials (x, δ = 0 / ±5 mm, slots 1/2/4) rerun at
H = 118 mm with the bias retired:

| δx | H=120, bias +1 mm | H=118, bias +1 mm | **H=118, bias 0** |
| --- | --- | --- | --- |
| −5 mm | 2/3 | 1/3 | 2/3 |
| 0 | 3/3 | 2/3 | **3/3** |
| +5 mm | 2/3 | 1/3 | 1/3 |
| total | 7/9 (78 %) | 4/9 (44 %) | 6/9 (67 %) |
| **single-sided failures** | — | — | **5 → 0** |

The headline number barely moved, but the **failure mode changed completely**:
single-sided contact went from 5 cases in this offset band to **zero**. Every
one of the nine trials now registers contact on *both* pads against the same
cylinder. The bias was indeed causing the single-sided failures.

What the three remaining failures show is a different defect — **the evidence
window, not the grasp**:

| trial | left / right samples | simultaneous overlap | broker needs |
| --- | --- | --- | --- |
| δ=−5 mm slot1 | 930 / 914 | **0.000 s** | ≥ 0.100 s |
| δ=+5 mm slot1 | 77 / 1575 | **0.075 s** | ≥ 0.100 s |
| δ=+5 mm slot4 | 99 / 110 | **0.097 s** | ≥ 0.100 s |
| successes | — | 0.280 – 0.755 s | — |

The overlap distribution is bimodal: solid grasps sit at 0.28–0.76 s (3–7×
the requirement) while these sit at 0–0.097 s. The last one misses the
threshold by **3 milliseconds**. The cause is that the post-close observation
window was only **0.35 s**, so a pad that engages late in the 1.2 s close has
its overlap truncated by the end of observation rather than by physics.
`M1B_POST_CLOSE_OBSERVATION_S` is therefore raised to 1.0 s — observing
sustained bilateral same-entity contact for longer is strictly more evidence
and never a relaxation of the ADR-0013 predicate.

(The 0.000 s case is genuinely different: its two windows abut exactly, i.e.
contact transferred from one pad to the other rather than being simultaneous.
A longer window cannot rescue that one, and should not.)
