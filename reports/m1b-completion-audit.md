# M1B completion audit

Audited at `8556779`. Hand model: ADR-0016 §4 franka-copy fallback, URDF
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
| 5 | M1A cube regression still passes | **OPEN — re-run required** | see below |
| 6 | Unit tests: broker field-absence, reset fail-closed, per-class width clamp | **PASS** | `test_m1b_broker_selects_only_same_entity_and_hides_it_from_public_feedback`, `test_post_grasp_identity_routes_wrong_object_without_entity_leak`, `test_m1b_reset_requires_every_generated_detachable_state`, `test_m1b_amendment_reset_gate_is_physical_and_fails_closed_on_missing_pose`, `test_m1b_width_window_is_perception_derived_and_clamped`; suite 126 passed |

## ADR-0016 revalidation cascade (nine steps)

| # | step | verdict | note |
|---|---|---|---|
| 1 | Home self-collision gate on the new model | **OPEN** | evidence exists and is `HOME_SELF_COLLISION_VERIFIED` with a matching URDF hash, but is uncommitted and predates a code change — refreshed by the item-5 re-run |
| 2 | S0 13-condition contact calibration | **OPEN** | `CONTACT_TELEMETRY_CALIBRATED` 13/13, same staleness — this is the stage whose client actually changed |
| 3 | S1 ten-trial MoveIt execution gate | **OPEN** | `VERIFIED_MOVEIT_EXECUTION` 10/10, same staleness |
| 4 | Orientation-feasibility pre-scan over current scenes | **PASS** | `m1b-adr0016b-orientation-prescan3-5017.json` (`b678b2f5…`). Scene-level verdict is `FAIL_CLOSED`, which is the gate working: cylinders 03/06/07 have no empty-scene pregrasp IK. Per-spawn-point records for slots 1/2/4 each carry `passed: true`, and the campaign worklist uses exactly those three |
| 5 | One zero-offset real grasp | **PASS** | 17/18 with the reliability fixes active (three confirmation runs 9/9 plus a campaign's own 8/9) |
| 6 | 81-point envelope, nonzero per-axis required | **OPEN — campaign v3 in flight** | committed value 15/15/5 mm (`m1b-adr0016b-tolerance-envelope.json`, `0bfb34e0…`) was measured *before* the five reliability fixes; v3 re-measures the shipped configuration |
| 7 | Perception p90 gate: per-axis p90 ≤ 0.6 × envelope | **PASS (conditional on step 6)** | recomputed independently from `…-current-geometry-perception-metrics.json` (`bfe89ead…`, held-out test split, 272 matched instances, 30 scenes, zero exclusions) → `GO`, agreeing with `…-current-geometry-reachability-gate.json` (`e38301e2…`) |
| 8 | ADR-0013 acceptance 3 and 4 | **PASS** | items 3–4 above |
| 9 | M1A cube regression under the new hand | **OPEN** | same re-run as ADR-0013 item 5 |

## The two open items

### Items 1, 2, 3, 5, 9 — one M1A re-run closes all of them

The M1A evidence on disk is **uncommitted and stale, not failing.** It reports
bullet audit 5/5 gates, home verified, S0 13/13, S1 10/10, and the contact-gated
grasp `CONTACT_GATED_CONSTRAINT_VERIFIED` at 9/10 (the single rejection was the
gate itself firing on `BILATERAL_CONTACT_INVALID` + `INVALID_SIM_TIMESTAMPS`,
i.e. fail-closed, not a silent pass). All five reports carry the ADR-0016b URDF
hash.

It is stale because it ran 2026-07-24 02:40 and `scripts/m1a_contact_calibration_client.py`
changed at 2026-07-25 10:05 (`e9ad5b8`, scaling the hand action-result wait with
the commanded trajectory). `run_contact_calibration.sh` and
`run_m1a_bullet_capability_audit.sh` use that module directly, and
`m1a_contact_gated_trial_client.py` imports `CalibrationClient` from it — so
three of the five stages exercised code that has since changed. The change only
makes the client wait longer, so the expected outcome is no worse; expected is
not measured, and stale evidence must not be committed as current.

Also note the working tree's `m1a-preflight.md` is from a *different, earlier*
run (`m1a-adr0016b-regression-20260723-0510`) and records
`BLOCKED_DIRTY_OR_MOVED_BASELINE`. Committing the set as-is would pair a
`BLOCKED` preflight with `VERIFIED` downstream gates. The re-run replaces both.

Serialization is forced, not chosen: the M1A remote stages launch their own
Gazebo on the same host, and `run_contact_calibration.sh` aborts on
`M1A_REMOTE_SIM_ALREADY_RUNNING`.

### Step 6 — what v3 can and cannot settle

v3 measures the shipped configuration (120 mm centreline **with** the five
fixes), which had never been measured: every fix-validation run executed while
the centreline constant was 118 mm.

It must be read against `m1b-adr0016b-closure-reproducibility.md`. The gate needs
Z ≥ 3.467 mm, the grid is 5 mm, so Z = 5 mm is the smallest passing value — zero
slack — and at the measured near-band reliability the closure reports Z ≥ 5 mm
only 41–67 % of the time. **A v3 result of Z = 0 is not a regression and Z = 5 mm
is not a fix.** Whatever it returns, the acceptance basis is a number with
sub-two-thirds reproducibility, and that is the honest headline for M1B.

## Not blocking, carried forward

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
