# ADR-0016 §4 pre-authorized fallback execution: franka-geometry hand copy

Status: **IN REVALIDATION** (this file is updated as each cascade step lands).

## Trigger

The complete 81-trial ADR-0016 campaign measured a zero envelope on every
axis (zero-offset X/Y/Z = 0/3, `reports/m1b-adr0016-tolerance-envelope.json`,
summary SHA-256 `bb602416…`).  That is exactly the pre-authorized §4 fallback
condition: stop iterating on homemade hands and copy the official reference
geometry.

## Measured diagnosis of the zero-offset failures (campaign raws)

Per-trial raw records (`node2:/tmp/m1b-tolerance-adr0016-run/raw/`) separate
three independent mechanisms; none is the pad topology itself:

1. **Kiss-gap close (0 squeeze).**  The aperture rule selected
   `inner_gap = perceived diameter` (30 mm on a 30 mm cylinder).  A centred
   close therefore ends at zero contact force: trials 001/054 recorded **zero
   post-close contact samples**; trials 028/055 recorded hundreds of samples
   on **one finger only** and never a 0.1 s bilateral window.  All 4 campaign
   successes (009/010/039/044) happened where an offset or a descent shove
   *accidentally* created squeeze — e.g. 039 (y +10 mm) shows left-pad
   contact 0.34 s before the right pad joins: a push-recentred, force-loaded
   grasp.  Zero-offset trials had no such squeeze and failed 0/9.
2. **OMPL joint-space "descent" bows sideways.**  With the finger/target ACM
   exception enabled, the joint-space plan legally swept through the target:
   the calibration displacement diagnostic shows the free cylinder moved
   13–18 mm during the descent in trials 000/027/044
   (`descend_displacement_world_xyz_m`).  A displaced target then meets one
   pad only (trial 000: 678/678 samples on the right finger).
3. **Slot-3 pregrasp IK −31 (15/81 trials dead on arrival).**  Every scene
   5017 / object-slot 3 trial on the failing side of each axis failed the
   pregrasp with MoveIt NO_IK_SOLUTION, exactly the boundary the ADR-0016 §3
   orientation-feasibility pre-scan exists to reject at scene admission.

## Fallback implementation (this change)

- `robot_ws/src/xh_sim/urdf/panda_controlled.urdf`: palm and fingers replaced
  by the primitive-approximated copy of the official
  `moveit_resources_panda_description` collision meshes (node2
  `/opt/ros/jazzy`, jazzy binary release):
  - `hand.stl` sha256 `94493e94f30fe940f2c8ca2f155c3bbe67bbff406d3edf5e261670d2f0f6e2ed`
    → palm box 0.0633 × 0.2044 × 0.0919 m at (0, −0.0018, 0.02005) (its
    axis-aligned bounds).
  - `finger.stl` sha256 `2d07a740392f3b9b0816f65d64fff9927d3d57c897870fc4b6ff9c56fff3a0c8`
    → per finger, two boxes with the contract element names retained:
    `collision` = proximal body 0.021 × 0.0239 × 0.036 m (recessed 2.5 mm
    behind the pad face), `tapered_tip_collision` = distal pad
    0.0176 × 0.0143 × 0.0178 m whose face lies exactly on the finger-link
    y=0 plane (inner gap = 2q).  Finger joints move to the official
    0.0584 m root.  Mirrored for the −y right finger.
  - Unchanged: joint names, [0, 0.04] m limits, effort/velocity, q2-master
    mimic (ADR-0008/0009), controller blocks, inertials (S1-verified
    controller tuning is retained; the fallback mandate is geometry).
  - Both finger contact sensors now bind **both** collision elements; with
    franka geometry the distal pad is the grasp face and was previously
    unobserved.
- `scripts/run_m1b_tolerance_trial.py`:
  - board-thickness term → 0 (`inner_gap = 2q`);
  - `M1B_CLOSE_SQUEEZE_M` production constant plus a bounded
    `--calibration-close-squeeze-m` probe flag (window-clamped; the broker
    ADR-0013 window still bounds every command);
  - the final descent now uses MoveIt `computeCartesianPath` (straight
    vertical tool-axis segment, collision-checked, fraction ≥ 0.999
    fail-closed) instead of an OMPL joint-space plan.
- `scripts/m1a_contact_calibration_client.py` (S0 harness, calibration
  infrastructure): pad constants re-derived from the franka-copy geometry
  (root 0.1032 m, pad 0.0176 × 0.0143 × 0.0178 m, per-side pad centres),
  left/right hand offsets ±0.017 m (2 mm inset preserved), bilateral close
  0.025 m/side (50 mm kiss on the 50 mm cube), bilateral vertical offset
  0.020 m — the franka palm (hand-x ±0.0317 m) otherwise stalls on the
  **physical-only bilateral backstop** (top z 0.805, not a planning-scene
  object): measured stall at hand z 0.8716 = backstop 0.805 + palm 0.066 +
  contact margin, with zero contact telemetry.  Adds
  `move_hand_cartesian` (GetCartesianPath + uniform timing + the existing
  execute/convergence evidence path).

## Probe-measured corridor findings (step 5, slot 1, zero offset)

1. **Fixed yaw 0 is corridor-blind.**  The straight descent fail-closed at
   fraction 0.71: the open-jaw sweep intersects neighbour `cylinder_09` only
   70 mm away on the closing axis.  The historical OMPL "descent" bowed
   around this primitive — that bow is mechanism 2 above.  Fix: the ADR-0016
   §2 free-gap yaw is now derived for the calibration path from the
   supervision labels (max-clearance yaw over a 15° grid), the same
   calibration-only input class as the target centre.  Production keeps its
   perception free-gap input.
2. **Endpoint IK feasibility is not corridor feasibility.**  Walking the
   descent with seeded per-waypoint collision-aware IK (which replaced the
   silent-truncating MoveIt cartesian service) measured an IK-branch fold at
   hand offsets ≈ +0.125 m for base-axis radii ≲ 0.27 m: every yaw jumps
   0.38–0.46 rad within one 5 mm step although both endpoints solve.  The §3
   pre-scan now walks this corridor per contact height (0.11/0.12) per yaw
   candidate; scene 5017's corridor-valid annulus is r ≳ 0.27 m (cylinders
   03/06/07/10/11 rejected), the campaign instances are slots 1/2/4
   (r = 0.273/0.384/0.325, corridor yaws 270°/45°/90°), and a descend retry
   re-enters through home because the corridor is only admitted from the
   home-seeded pregrasp branch (measured: the same 270° descent completes
   home-seeded but jumps 0.38 rad when re-approached in place).
3. **bullet-featherstone物理接触三连坑 (all measured live on node2):**
   - The runtime-spawned multibody robot only instantiates each link's
     FIRST collision element physically (S0: 255/255 events on the first
     element while the second sat 2.5 mm deeper; world-embedded scratch
     models collide both).  The grasp surface therefore lives in element
     "collision", the recessed body in "tapered_tip_collision" (names
     retained; both stay bound to the finger contact sensors).
   - Small convex blocks have a shallow-penetration dead band against free
     dynamic bodies: the 17.8 mm pad block produced ZERO contact response
     even at 4.5 mm modelled overlap, while the proven old-hand element was
     an 80 mm plate.  The grasp element is therefore a full-length plate
     (0.021 × 0.0208 × 0.0538 m), and its face is modelled 6.5 mm proud of
     the finger-link y=0 plane while the public inner-gap mapping stays
     2q − 0.006, so a window-edge close lands its modelled overlap ~4.5 mm
     deep.  Measured result: real stall (fingers stop at 0.0203 m against a
     0.017 m command, mimic symmetric to 1e-5) with 30 Hz bilateral
     contact streams.  Heavier cylinders (0.2 kg, no velocity decay) did NOT
     fix the block-shaped element — shape, not mass, is the variable.
   - A stalled grasp close is a SUCCESS state: the close acceptance now
     admits the measured stall band (command → perceived-radius surface
     + 3 mm engine margin + 1 mm contract) while keeping mimic symmetry;
     the previous 1 mm free-space tolerance was silently discarding the
     entire post-close evidence window of every physically-correct grasp.
4. **Zero-offset production grasp: PASS.**  With all of the above, trial
   000 (h = 0.11, squeeze 2 mm, slot 1): straight descent converged with
   0.4 mm target displacement, close stalled symmetrically, post-close
   window 681 samples (340 left / 341 right), bilateral same-entity overlap
   0.339 s, `cylinder_01: attached` observed — the full
   bilateral+attach production predicate at zero offset.



| step | gate | status |
| --- | --- | --- |
| 0 | ADR-0009 bullet capability audit (S0 precondition) | **M1A_BULLET_CAPABILITY_VERIFIED** — all 5 gates, model_match true |
| 1 | Home self-collision | **HOME_SELF_COLLISION_VERIFIED** |
| 2 | S0 13-condition contact calibration | **CONTACT_TELEMETRY_CALIBRATED** — 13/13 conditions, 9/9 positive windows, 13/13 idle baselines |
| 3 | S1 ten-trial MoveIt execution gate | **VERIFIED_MOVEIT_EXECUTION** — 10/10 |
| 4 | Orientation-feasibility pre-scan (scene 5017) | **corridor-extended REJECTED at scene level** (`reports/m1b-adr0016b-orientation-prescan3-5017.json`): 12/17 pass; the 5 failing cylinders (03/06/07/10/11) sit at base-axis radius ≲ 0.27 m where the straight open-jaw descent hits a seeded-IK branch fold at both 0.11/0.12 heights and every yaw — a spawn-position defect, not a hand defect. Scene admission stays fail-closed; the campaign uses corridor-valid slots 1/2/4. **Follow-up: industrial scene generation must integrate the §3 corridor scan before the next Beta batch.** |
| 5 | Bounded height + close-squeeze calibration, zero-offset live grasp | **SELECT 120 mm / 2 mm / two-stage close** (`reports/m1b-adr0016b-top-contact-height-calibration.{json,md}`) — 2/2 bilateral + attach |
| 6 | 81-point envelope campaign | **COMPLETE_CALIBRATION_ONLY**, envelope **X 0.015 / Y 0.015 / Z 0.005 m** (was 0/0/0), summary SHA-256 `1e758295…` (`reports/m1b-adr0016b-tolerance-envelope.json`). **§4 fallback success criterion (nonzero per-axis envelope) met.** |
| 7 | Perception p90 gate | **NO_GO — but measured, not unmeasured** (`reports/m1b-adr0016b-perception-reachability-gate.json`): p90 exceeds 0.6×envelope on all axes (x 9.88 vs 9.0 mm, y 15.1 vs 9.0 mm, z 17.3 vs 3.0 mm). This is now a perception-accuracy-vs-tolerance-margin problem (worst on Z), not a grasp-physics problem. Remediation path is the already-coded `--enable-near-pregrasp-reobservation`, not another hand iteration. |
| 8 | ADR-0013 acceptance 3 (round-trip) | **PASS** (`reports/m1b-adr0016b-attached-roundtrip.json`): real grasp → rigid-follow (link/cyl 27.7 mm, drift 4 µm) → detach observed → decouple (link 33 mm, cyl left behind). |
| 8 | ADR-0013 acceptance 4 (wrong-object drill) | **PASS** (`reports/m1b-adr0016b-wrong-object-drill.json`, SHA-256 `c0725d41…`). Intended target `cylinder_01` (public track-550f6239); deliberately grasped non-target `cylinder_02`. The broker **attached cylinder_02** (physics honest — no target-id refusal, the seal on the M1A oracle leak). Pre/post public RGB-D perception (10→7 tracks) identified the carried track via the vacated-spawn method (track-b0b7a018 ≠ target) → `WRONG_OBJECT`; recovery triggered (Reobserve→SafePlaceNonTarget→ReassociateTarget→Approach→Regrasp); supervision recorded `wrong_object=true` (evaluation-only). Post-grasp occlusion vacated 3 tracks; the carried one is disambiguated by proximity to the attached entity's spawn (evaluation-only). |
| 9 | M1A cube regression | **RUN (clean worktree) — one real regression, root-caused to a full pose re-tune (bounded follow-up).** Under the new hand: bullet audit 5/5, home, S0 13/13, S1 10/10 pass. The M1A cube contact-gated grasp fails: with the old close (0.033) it is a clean `CONTACT_CLOSURE_FAILURE` (pads ~1.5 mm short); re-tuning the close to 0.027 (committed, S0-aligned) is necessary but **not sufficient** — a live-corridor probe shows the cube lands at hand-frame **(x 0.105, y 0.0006, z 0.055)** while the franka grasp plate occupies **x ∈ [−0.0105, 0.0105], y = ±0.0039, z-centre 0.027**, so the cube sits ~10 cm off the pads along hand-x and just past the plate tip along the tool axis. The grasp-anchor constants in `src/xh_agent/grasp/orientation_families.py` (`FINGER_LENGTH_M=0.12`, `FINGER_ROOT_Z_M=0.055`, `HAND_FINGER_LINE_X_M=0.06`) and the candidate pose families were tuned for the pre-franka pad location. **Follow-up: re-derive the orientation-family grasp anchor + close for the franka plate geometry and re-validate — a pose-geometry re-tune comparable to the M1B height/squeeze calibration, distinct from the M1B top-down family. (S0's vertical-offset bilateral pose already contacts the cube at 0.027, so the fixture geometry is sound; only the contact-gated approach family needs the re-derive.)** The regenerated worktree M1A reports were NOT committed. |
| — | Unit suite (acceptance item 6) | **111/111 pass** with the ADR-0016b hand contract + §3 corridor prefilter; `validate_project` PASS; changed scripts lint clean. Committed `ca39515`..`b53a99f`. |
