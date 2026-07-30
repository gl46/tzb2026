# M1B ADR-0014 tolerance-envelope measurement

Status: **COMPLETE_CALIBRATION_ONLY — zero measurable envelope**

This is the 2026-07-19 remeasurement after the ADR-0014 end-effector and
30 mm-cylinder geometry change. It used the production grasp primitive and
all production gates; supervision was used only for the controlled offset
initialization.

| Axis | Envelope at >=2/3 success |
| --- | --- |
| x | unmeasured / zero (no point passed) |
| y | unmeasured / zero (no point passed) |
| z | unmeasured / zero (no point passed) |

All 81 trials recorded `bilateral_same_entity_contact = false`; therefore no
trial satisfied the attach success predicate. The raw trial files are retained
on node2 at
`/tmp/m1b-tolerance-campaign-adr0014-physical-r2-20260719/raw`; the complete
machine-readable envelope has SHA-256
`b3006faf752d685dfc96ef3576d32c9039cb58383b2bf625178128dbc11eac5a`.

This is a physical NO-GO evidence result, not an infrastructure failure and
not permission to relax a gate.
