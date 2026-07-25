# M1B completion audit

Audited at `8556779`; completed and re-audited at `0ff7518`. Hand model: ADR-0016 §4 franka-copy fallback, URDF
SHA-256 `6678ff409d60f07428380587…`.

M1B is governed by **two** lists, and they are not the same list:

- **ADR-0013 "Acceptance before M1B-beta unblocks"** — six items.
- **ADR-0016 "Mandatory revalidation cascade"** — nine steps, triggered by the
  §4 fallback hand replacing the inline hand.

Every row below was checked against the evidence file, not against a prior
summary. Where a document quoted a SHA-256, the hash was recomputed.

## ADR-0013 acceptance (six items)

| # | item | verdict | evidence |
|---|---|---|---|
| 1 | Generated SDF has exactly N detachable blocks; whitelist diff + hash triple | **PASS** | `m1b-adr0013-per-object-spawn-provenance.json` (`2b319cb0…`): 11 per-cylinder contracts, whitelist delta only the finger mimic and the detachable plugin blocks |
| 2 | After reset broadcast, all N `grasp_state` observed `detached` | **PASS as amended** | Superseded by Amendment 1 (human-approved 2026-07-19), which replaced message-receipt with a physical non-coupling check because the Gazebo plugin publishes only on transition. `m1b-reset-physical-noncoupling.json` (`2ad8967f…`): `RESET_PHYSICAL_NONCOUPLING_VERIFIED`, EE displacement 24.28 mm against a 20 mm minimum |
| 3 | One-cylinder physical round-trip | **PASS** | `m1b-adr0013-current-geometry-attached-roundtrip.json`, SHA-256 `30c103a0…` — recomputed, matches the value quoted in `m1b-adr0016b-acceptance-status-20260724.md` |
| 4 | Wrong-object drill | **PASS** | `m1b-adr0013-current-geometry-wrong-object-drill.json`, SHA-256 `62e45bca…` — recomputed, matches |
| 5 | M1A cube regression still passes | **PASS** | re-run at HEAD 2026-07-26: bullet audit 5/5, home verified, S0 13/13 on the corrected fixture, S1 `VERIFIED_MOVEIT_EXECUTION` 10/10 with anti-teleport 10/10, S3 `CONTACT_GATED_CONSTRAINT_VERIFIED` 8/10 with release 8/8 |
| 6 | Unit tests: broker field-absence, reset fail-closed, per-class width clamp | **PASS** | `test_m1b_broker_selects_only_same_entity_and_hides_it_from_public_feedback`, `test_post_grasp_identity_routes_wrong_object_without_entity_leak`, `test_m1b_reset_requires_every_generated_detachable_state`, `test_m1b_amendment_reset_gate_is_physical_and_fails_closed_on_missing_pose`, `test_m1b_width_window_is_perception_derived_and_clamped`; suite 126 passed |

## ADR-0016 revalidation cascade (nine steps)

| # | step | verdict | note |
|---|---|---|---|
| 1 | Home self-collision gate on the new model | **PASS** | `HOME_SELF_COLLISION_VERIFIED` at HEAD |
| 2 | S0 13-condition contact calibration | **PASS** | `CONTACT_TELEMETRY_CALIBRATED` 13/13 at HEAD, and for the first time on the `d9938ad` corrected fixture |
| 3 | S1 ten-trial MoveIt execution gate | **PASS** | `VERIFIED_MOVEIT_EXECUTION` 10/10, `anti_teleport_verified_trials` 10 |
| 4 | Orientation-feasibility pre-scan over current scenes | **PASS** | `m1b-adr0016b-orientation-prescan3-5017.json` (`b678b2f5…`). Scene-level verdict is `FAIL_CLOSED`, which is the gate working: cylinders 03/06/07 have no empty-scene pregrasp IK. Per-spawn-point records for slots 1/2/4 each carry `passed: true`, and the campaign worklist uses exactly those three |
| 5 | One zero-offset real grasp | **PASS** | 17/18 with the reliability fixes active (three confirmation runs 9/9 plus a campaign's own 8/9) |
| 6 | 81-point envelope, nonzero per-axis required | **PASS** | campaign v3 measured the shipped configuration for the first time: **15/15/5 mm**, agreeing with the committed envelope on all three axes (`m1b-adr0016b-tolerance-envelope-v3.json`, summary SHA-256 `909d88ec…`) |
| 7 | Perception p90 gate: per-axis p90 ≤ 0.6 × envelope | **PASS** | recomputed independently from `…-current-geometry-perception-metrics.json` (`bfe89ead…`, held-out test split, 272 matched instances, 30 scenes, zero exclusions) → `GO`, agreeing with `…-current-geometry-reachability-gate.json` (`e38301e2…`) |
| 8 | ADR-0013 acceptance 3 and 4 | **PASS** | items 3–4 above |
| 9 | M1A cube regression under the new hand | **PASS** | same re-run as ADR-0013 item 5 |

## How the two open items were closed

Both remaining items were closed on 2026-07-26. Neither closed the way I first
expected, and the corrections are recorded here rather than quietly dropped.

### Step 6 — campaign v3

v3 measured the shipped configuration for the first time: the 120 mm contact
centreline **with** all five reliability fixes. No prior campaign measured that
combination — the previously committed 15/15/5 predates the fixes, and every
fix-validation run executed while the centreline constant was 118 mm.

It returned **15/15/5 mm**, agreeing with the committed envelope on all three
axes, at 51/81 = 63 % overall. The gate recomputed against it is `GO` with
per-axis margins of 6.70 / 4.21 / 0.92 mm. The acceptance basis is now a
measurement of what ships rather than an inherited one.

**This is a favourable draw, not proof the reliability problem is solved.** At
the measured near-band reliability the closure reports Z ≥ 5 mm only 41–67 % of
the time (`m1b-adr0016b-closure-reproducibility.md`). That was written down
before the result was known, and it stands unchanged now that the result is
known.

v3 also supplied the missing 2×2 cell and partially de-confounded the centreline
question that had to be withdrawn: at z = +10 mm the five fixes changed nothing
at a fixed centreline (1/3 → 1/3) while the 118 mm centreline gave 3/3 — the
direction the geometric model predicted. Pooled, 2/6 vs 3/3, Fisher one-sided
p ≈ 0.08: suggestive, not conclusive. The 118 mm revert is **not** reopened; it
rested on the official closure, which still scores it worse.

### Items 1, 2, 3, 5, 9 — the M1A re-run

Re-run from a clean detached worktree against a freshly deployed, hash-verified
node2 (URDF `6678ff40…`, calibration world `d163dd0b…`).

| stage | verdict |
|---|---|
| preflight | `can_start = true`, no blockers |
| m0 smoke | `PARTIAL_CONTROL_AND_PERCEPTION_VERIFIED` |
| ADR-0009 bullet capability audit | `M1A_BULLET_CAPABILITY_VERIFIED`, 5/5 gates |
| cascade 1 — home self-collision | `HOME_SELF_COLLISION_VERIFIED` |
| cascade 2 — S0 contact calibration | `CONTACT_TELEMETRY_CALIBRATED` 13/13, first run on the corrected fixture |
| cascade 3 — S1 MoveIt execution | `VERIFIED_MOVEIT_EXECUTION` 10/10, anti-teleport 10/10 |
| S2 friction | `FRICTIONAL_GRASP_NOT_VERIFIED` (4/5 threshold unmet) |
| cascade 9 / item 5 — S3 contact-gated grasp | `CONTACT_GATED_CONSTRAINT_VERIFIED` 8/10, release 8/8 |

S2 not meeting its threshold is not a regression: the committed baseline had it
at `FRICTION_TRIALS_BLOCKED_REVALIDATION_REQUIRED`, and
`FRICTIONAL_GRASP_NOT_VERIFIED` is one of the two states S3's own prerequisite
check accepts. S3 is the acceptance-relevant gate and it is met.

### Why node2's fixture mattered

Hashing all 34 tracked `robot_ws/` files against HEAD found exactly one
difference, and it was the S0 stage's own world:
`robot_ws/src/xh_sim/worlds/m1a_contact_calibration.sdf`. node2's copy hashed to
`0709cc1` (2026-07-17) and carried the **pre-ADR-0016 fixture** — a 30 mm oracle
post and a full-width 60 × 55 mm shelf. HEAD carries `d9938ad` (2026-07-20),
which narrows them to a 10 mm post and a 25 × 10 mm centre-only support
*specifically* so the ADR-0016 vertical pads stop colliding with the fixture
during a bilateral sidewall calibration. The URDF had reached node2 by some
targeted copy, but no full deploy happened after `0709cc1`, so the earlier
S0 13/13 was measured on a fixture the repository had already corrected.

### Three corrections

1. **The S1 zero-stamp failure was transient.** Commit `deaf8a5` said it was
   "reproduced on a standalone re-run, so it is not the transient class." That
   was honest against two consecutive reproductions and is **withdrawn**: a
   third run on a quieter host returned 10/10 with real sim stamps
   (12.68 → 16.36 s; 160/117/87 distinct per segment). Both failures fell within
   minutes of the 81-trial campaign ending. A runtime diagnostic had already
   shown nothing was structurally wrong — `/clock` published, `use_sim_time`
   true on `/controller_manager`, `/joint_state_broadcaster`, `/move_group` and
   `/robot_state_publisher`, sim clock advancing, and a subscription mimicking
   the client exactly receiving 490 samples with 490 distinct stamps — which is
   why re-running was the right move rather than patching.

2. **`reports/m1a-contact-gate.*` was nearly reported as a current pass.** A
   verdict table that iterates a fixed file list will happily print the
   committed `m1a-20260717-s4-b1-final-r1` record against URDF `84b0d2dc…` — the
   pre-fallback hand — as though it were today's result.

3. **ADR-0009 makes the bullet capability audit a prerequisite for S0**, and
   `run_m1a_validation.sh` does not include it. Because S0 reads the audit from
   disk while the preflight demands a clean tree, the audit has to be committed
   before the validation run.

### One real defect found and fixed

S3's first complete run was 7/10 against a ≥8/10 threshold. Two of the three
failures were `RELEASE_PLACEMENT_FAILURE` → `HAND_CONTROLLER_NOT_SUCCEEDED` with
`controller_result_succeeded: true` and `error_code: 0` — the controller met its
own 1 mm tolerance while `command_hand` judged a snapshot taken after a fixed
`for _ in range(3): spin_once(0.02)`. The same artifact had already appeared in
the bullet audit (`max_position_error_m` 0.00713 m, mimic tracking error
1.1 × 10⁻⁸ m, next read 0.039999 m of a 0.04 m command).

Fixed by counting joint-state *deliveries* and requiring three fresh ones after
the result, polling to a 2 s deadline. The 1 mm contract and its 0.1 mm sampling
slack are unchanged, so a hand that genuinely stops short still fails. That class
went from 2 of 10 episodes to **0**.

## Status

**All six ADR-0013 acceptance items and all nine ADR-0016 cascade steps pass at
`0ff7518`.** Every row was checked against its evidence file and every quoted
SHA-256 was recomputed.

The honest qualifier on that verdict: the Z axis of the envelope has zero grid
slack against the perception gate, and the closure that produces it reproduces
41–67 % of the time at the measured reliability. M1B is accepted on its own
stated criteria; it is not accepted on a measurement that would survive
repetition with high confidence, and the cheapest route to the latter is
per-trial reliability rather than more repetitions.

## Not blocking, carried forward

- **M1A bilateral contact window is at its own gate.** Three S3 episodes across
  two runs rejected at 0.096, 0.098 and 0.099 s against a 0.100 s requirement —
  all within 4 ms, which is systematic rather than noise. Every rejection was
  fail-closed and the gate is still met at 8/10, so it does not block
  acceptance, but it is the M1A analogue of the truncated evidence window
  already fixed on the M1B path.
- **Reset jog can clip a non-target cylinder.** 2 of 81 v3 resets (2.7 %) were
  rejected because the randomized home jog displaced a non-target cylinder
  ~22 mm (`cylinder_04` 21.25 mm, `cylinder_02` 23.08 mm). Both recovered on a
  fresh world. A rejected reset is never an episode, so it cannot contaminate a
  measurement.
- **Shared-host transients are real and slow.** Three separate measurement
  artifacts today — the bullet audit's `physical_mimic`, S1's zero stamps, and
  S3's release step — all traced to fixed wall-clock assumptions on a host
  sharing its GPU. Two were transient, one was a genuine defect. The lesson is
  that a fixed spin count or wall-clock wait is the first thing to suspect, and
  that two consecutive reproductions are not enough to rule out a transient.
- **Descent-corridor near-band losses.** All 16 descent rejections land in the
  final 1–5 waypoints at z ≈ 0.594 m with all three yaw retries exhausted. At
  |δ| ≥ 15 mm they are deterministic and correct; at |δ| ≤ 5 mm three trials
  abort on a 0.41–0.60 rad branch flip. A step-bisection retry is a candidate
  fix with an unproven success rate; settle it with a bounded offline IK probe
  before touching the production primitive.
- **Palm split.** Documented in `m1b-adr0016b-z-envelope-geometry.md`; would move
  the palm bound and widen the Z envelope, at the cost of the full revalidation
  cascade.
- **Protocol strengthening.** More repetitions per point is ADR-level (project
  rule 7) and costs ~34 h for 95 % confidence; raising per-trial reliability
  reaches the same confidence within the existing 2.8 h protocol and needs no
  ADR.

## Truth boundary

Simulator truth supplied only calibration-only target initialization. Contact,
broker, attach, and descent evidence are production-path records. Perception
metrics are offline-evaluation-only on the held-out test split. The wrong-object
drill's entity identifiers stay inside actuation and evaluation records and never
selected a public target.
