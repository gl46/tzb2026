# How reproducible is the number the M1B acceptance depends on?

Status: **the committed `GO` rests on a Z measurement that, re-run unchanged,
reproduces 41–67 % of the time.** This is an arithmetic property of the
acceptance protocol, not a defect in any one campaign, and it is the reason the
Z envelope has moved between every campaign. The cheap lever is per-trial
reliability, not more repetitions; raising reliability needs no ADR.

## The gate's Z term has zero slack

The perception gate is `per_axis_p90_m <= 0.6 * measured_tolerance_m`. Held-out
p90 is 2.295 / 4.793 / 2.080 mm (272 matched instances, 30 scenes, no
exclusions — `m1b-adr0016b-current-geometry-perception-metrics.json`). Inverting
the criterion against the 5 mm campaign grid:

| axis | needs `tol ≥ p90/0.6` | grid minimum | committed | slack |
|---|---|---|---|---|
| x | 3.825 mm | 5 mm | 15 mm | 2 grid steps |
| y | 7.988 mm | 10 mm | 15 mm | 1 grid step |
| **z** | **3.467 mm** | **5 mm** | **5 mm** | **0 grid steps** |

So the whole acceptance turns on Z being reported as ≥ 5 mm, and 5 mm is the
smallest value that can pass. Campaign v2 reported Z = 0.

## What the protocol reports, as a function of reliability

Exact binomial under the project's own rules (`point_pass_rule:
at_least_2_of_3`; `monotonic_closure:
both_signed_offsets_and_all_smaller_magnitudes_pass`, so Z ≥ 5 mm requires the
0, +5 and −5 grid points all to pass). No fitting, no simulation:

| per-trial p | P(a point passes) | **P(reports Z ≥ 5 mm)** | P(reports Z ≥ 10 mm) |
|---|---|---|---|
| 0.60 | 0.648 | 0.272 | 0.114 |
| **0.67** (v2 near band, 6/9) | 0.745 | **0.414** | 0.230 |
| 0.75 | 0.844 | 0.601 | 0.428 |
| **0.78** (H120 near band, 7/9) | 0.876 | **0.672** | 0.516 |
| 0.85 | 0.939 | 0.829 | 0.731 |
| 0.90 | 0.972 | 0.918 | 0.868 |
| 0.95 | 0.993 | 0.978 | 0.964 |

At the measured near-band reliability the protocol reports the value the gate
needs less than two times in three. **A campaign that re-runs and reports Z = 0
is therefore not evidence of a regression, and one that reports Z = 5 mm is not
evidence of a fix.** That is the single most important fact about the current
acceptance basis.

## Two levers, an order of magnitude apart in cost

Lever 1 — **more repetitions per point**, reliability unchanged at p = 0.67,
majority rule, at the measured 124 s/trial:

| target confidence | reps/point | trials | wall clock |
|---|---|---|---|
| 95 % | 37 | 999 | ~34 h |
| 99 % | 61 | 1647 | ~57 h |

Lever 2 — **raise per-trial reliability**, protocol untouched at 3 reps / 2-of-3,
still 81 trials / ~2.8 h:

| p | P(reports Z ≥ 5 mm) |
|---|---|
| 0.85 | 0.829 |
| 0.90 | 0.918 |
| 0.95 | 0.978 |

Lever 2 is both cheaper and reachable: with the five reliability fixes active,
zero-offset reliability measured **17/18 = 94 %** (three confirmation runs 9/9,
plus the campaign's own 8/9). The band that drags p down to 0.67 is |δ| = 5 mm.

Lever 1 changes a formal acceptance protocol and needs a human ADR (project
rule 7). Lever 2 is ordinary engineering and does not.

## Where the near-band losses actually come from

Replay of all 162 trials of the two finished campaigns through
`src/xh_agent/grasp/m1b_contact_window.py` (162/162 verdict reproduction against
the run-time record, so the replay is faithful). Failure taxonomy, by the stage
each failing trial reached:

| stage reached | h120 | v2 |
|---|---|---|
| never ready / open-hand failed | 1 | 1 |
| **descent not executed (corridor/IK)** | **8** | **8** |
| close failed | 5 | 3 |
| reached close — a real grasp attempt | 14 | 18 |
| total failures | 28 | 30 |

**Correction to an earlier statement of mine.** I reported that "26 of the 30
residual failures had one finger report no contact at all." That counted
both-fingers-silent trials as one-sided. The correct split of v2's 30 failures
is 17 both-silent, 9 one-silent, 4 both-reported-but-no-valid-window; for h120
it is 14 / 12 / 2. There is still no detectable side bias (13 left-silent vs
8 right-silent pooled, two-sided exact p = 0.38), consistent with the earlier
disproof of the follower-pad hypothesis. But the dominant class is *no contact
at all*, which is a positioning/descent outcome rather than pad-contact
marginality, so the engineering target is different from the one I named.

Near band (|δ| ≤ 5 mm), which is what the gate depends on: 42/54 pass. Four of
the twelve failures never reached a valid close. Counting only trials that
actually attempted a grasp, near-band reliability is **42/50 = 84 %** rather
than 78 %.

## The descent rejections are a single, well-localized mechanism

Every one of the 16 descent rejections across both campaigns lands in the
**final 1–5 waypoints of a ~155 mm descent** (fraction 0.81–0.97), at
z ≈ 0.593–0.595 m:

- `CARTESIAN_JOINT_JUMP_REJECTED` (8): observed single-step joint deltas 0.387,
  0.409, 0.488, 0.494, 0.594, 0.597, 0.723 and 4.184 rad against the
  `max_joint_step_rad = 0.35` guard in `move_hand_cartesian`. Seven of the eight
  are 0.39–0.72 rad — modestly over a threshold chosen by this implementation.
- `CARTESIAN_WAYPOINT_IK_REJECTED` (8): all MoveIt `code -31` (no IK solution)
  in the last waypoint or two.

Two distinct readings, and the data separates them:

1. At |δ| ≥ 15 mm the rejections are **deterministic and correct**. Trials
   069/070/071 (z −15 mm) and 075/076/077 (z −20 mm) fail the *same way at the
   same waypoint* in both campaigns. That is a real geometric wall being
   measured, and failing closed is right.
2. At |δ| ≤ 5 mm three trials (h120 x +5 mm, h120 z +5 mm, v2 z +5 mm) abort on
   a 0.41–0.60 rad jump in the **final** 5 mm step. A wrist branch flip near a
   singularity is not an infeasible pose. The guard is correct to refuse to
   *execute* a 0.6 rad jump in one 5 mm step — that would whip the hand — but
   aborting the whole trial is not the only correct response.

### The existing recovery fired and was exhausted

**All 16 of these failures had `calibration_yaw_retry_attempts == 3`** — every
available free-gap yaw candidate was tried and every one hit the same wall. The
retry is not broken: 18 of the 104 successes needed it (16 at one retry, one at
two, one at three). So yaw choice is not the remaining lever.

The §3 corridor pre-scan shows the same mechanism at the un-offset spawn point:
for `cylinder_01`, yaw 1.5708 rad fails with `stage: joint_jump`,
`max_observed_joint_step_rad = 0.431` at `failed_hand_z_offset_m = 0.125`, and
yaw 4.712 rad then completes — so the record's verdict is `passed: true`. With
an offset applied, all yaws fail instead. The wall moves with the offset.

### Candidate fix, and the evidence against it

**Candidate:** on a joint-jump rejection, bisect that waypoint's step
(5 → 2.5 → 1.25 mm) and retry, re-seeding from the last verified solution; fail
closed only if the jump persists at the finest step. This would preserve the
guard's safety property exactly — no large jump is ever executed.

**Evidence for:** at |δ| ≤ 5 mm the solver returns a *valid solution on another
branch* (a 0.41–0.60 rad jump), whereas at |δ| ≥ 15 mm it returns no solution at
all (`code -31`). A discrete branch flip is step-size dependent; an absent
solution is not.

**Evidence against:** all three yaw candidates fail identically, which is what a
genuine kinematic boundary looks like rather than a seeding artifact. If the
boundary is real, bisection will simply discover it at finer resolution and the
recovery rate will be zero.

So the effect is **a hypothesis with an unproven success rate**, not a
projection. It is worth one bounded offline probe — replay the three near-band
poses through IK at 2.5 and 1.25 mm steps and count how many stay on branch —
before touching the production primitive at all. That probe needs no campaign.

It is **not** implemented here: it modifies the production motion primitive and
starts its own revalidation cascade, and campaign v3 was already measuring the
shipped configuration when the diagnosis landed.

## Why the campaign runs on a scene whose §3 gate says `FAIL_CLOSED`

Worth stating explicitly, because it reads alarming out of context. Both
pre-scan records for scene 5017 carry
`status: ORIENTATION_FEASIBILITY_REJECTED` and `scene_admission: FAIL_CLOSED`.
That is the verdict on the **scene as a whole**, and it is correct: cylinders
03, 06 and 07 have no empty-scene pregrasp IK at all. §3 requires scene
generation to fail closed on exactly that, and it did.

The per-spawn-point records are separate, as §3 requires. Slots 1, 2 and 4 each
carry `passed: true` in the corridor-extended pre-scan, with the descent
corridor complete at both candidate contact heights. The campaign worklist uses
precisely those three slots — slot 3, the one with the −31 pregrasp IK, was
replaced. So the campaign runs only on admitted spawn points, and the scene-level
`FAIL_CLOSED` is the gate working rather than a bypassed check.

One caveat that follows from the correction above: §3 admits the *spawn point*.
The tolerance campaign then offsets the target by up to ±20 mm away from it, and
those offset poses were never in §3's scope.

## Truth boundary

Simulator truth supplied only the calibration-only target initialization.
Contact, broker, attach, and descent evidence are production-path records. The
perception metrics are offline-evaluation-only on the held-out test split. The
replay in this report reads recorded evidence and computes no new physics.
