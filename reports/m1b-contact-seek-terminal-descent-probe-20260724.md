# M1B contact-seeking terminal-descent calibration probe (2026-07-24)

Status: **`CALIBRATION_CANDIDATE_REJECTED`** — M1B remains **`NO_GO`**.

## Scope and guardrails

This is a zero-offset, calibration-only probe of the candidate authorized by
ADR-0013 Amendment 2.  It uses supervision only to initialize the target
centre.  The stop decision uses only the production broker's bilateral
same-entity contact window; no simulator truth, contact entity, or target pose
is an online policy input.  A failed contact window must not close or attach.

The scene is the real Gazebo scene
`/tmp/m1b-normal-height-scan/scenes/scene-5017.sdf` on node2 (SHA-256
`56c7affe…`); its supervision sidecar is SHA-256 `29f7…`.

## Measured probes

| Probe | Raw evidence SHA-256 | Result |
| --- | --- | --- |
| r2 | `916e0f9026ea…` | First fully-staged descent reached the 120 mm terminal point only as a rejected Cartesian joint jump (3.313 rad); no close or attach. |
| r3 | `a27423ccbac2…` | Carrying the previous IK endpoint reduced the rejected terminal jump to 0.443 rad, but did not make it executable; no close or attach. |
| r4 | `6d066ed3fb1e…` | Yaw retry produced raw contacts but never a bilateral same-entity window; no close or attach. |
| r5 | `0dc18fb87b4…` | The measured continuous baseline reached 120 mm, then 115 and 110 mm staged moves executed and converged.  All 223 raw contacts were from the left finger with `cylinder_01`; the right finger had none.  The 105 mm waypoint was rejected by IK (`-31`).  The broker returned `bilateral_contact_window_incomplete`; close was not sent and attach was rejected. |

The r5 baseline's maximum final joint error was `9.12e-7` rad.  The two
staged waypoints also converged (maximum final errors `1.08e-6` and
`5.35e-7` rad), so the rejection is not a completion/sampling artefact.

Raw records remain on node2 at
`/tmp/m1b-contact-seek-probe-zero-r{2,3,4,5}/raw/trial-000.json`.

## Decision

The candidate has not produced bilateral contact even at the nominal centre,
and its next 5 mm descent is not IK-feasible.  It therefore cannot enter the
81-trial tolerance campaign or trigger a new perception p90 comparison.  No
threshold was relaxed and no ADR-0013 acceptance round-trip or wrong-object
drill was run from this candidate.

The measured M1B envelope/p90 result remains the previous `NO_GO`: tolerance
X/Y/Z = 15/15/5 mm, perception p90 = 9.88/15.13/17.30 mm, versus limits
9/9/3 mm.  A further attempt needs a materially different, explicitly
reviewed kinematic/contact primitive rather than another threshold or retry
tweak.
