# M1B Z-envelope: the 5 mm limit is two hard geometric bounds, not grasp noise

Status: **root cause proven; optimum contact centreline derived and under measurement.**

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
