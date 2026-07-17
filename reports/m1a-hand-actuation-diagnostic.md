# M1A Option 1 hand-actuation diagnostics

- Status: `HAND_ACTUATION_DIAGNOSTIC_BLOCKED`.
- Run: `m1a-20260716-option1-diagnostic-07`.
- Raw log: `logs/m1a-20260716-option1-diagnostic-07.log`.
- q1 world pose shows no close: `None`.
- Right world pose matches asymmetric command: `None`.
- Changed files: `scripts/m1a_hand_actuation_diagnostic.py`, remote/local runners, this report.
- Verification: fresh Gazebo session; explicit 1 mm hand-goal tolerance; spawned-SDF service dump.
- Failure/blocker: no source-level repair conclusion is asserted by this diagnostic alone.
- Next command: evaluate this report before the approved temporary mirror-axis overlay.
