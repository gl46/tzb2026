# ADR-0016b top-contact height and close-squeeze calibration (franka-copy hand)

Status: **measured single-point selection; not a tolerance-envelope result**.

The production top-down primitive (free-gap yaw, seeded-waypoint vertical
descent, two-stage close) was executed with evaluator-only supervision for
its zero-offset initialization on scene 5017 slot 1.

| Centreline | Squeeze | Close | Bilateral + attach | Result |
| --- | --- | --- | --- | --- |
| 100 mm | 2 mm | single | corridor IK branch jump | reject |
| 110 mm | 2 mm | single | 1/2 (repeat: single-sided ghost contact) | reject |
| 110 mm | 0 mm (kiss) | single | 0/1 — no stall, no bilateral | reject (control) |
| 120 mm | 2 mm | single | 1/2 (repeat: single-sided ghost contact) | evidence for two-stage |
| **120 mm** | **2 mm** | **two-stage** | **2/2, overlaps 0.663 s / 0.201 s, both `cylinder_01: attached`** | **select** |

Selected: **120 mm centreline, 2 mm window-edge squeeze, two-stage close**
(pre-close 2 mm clear of the modelled skin → 0.4 s settle → 1.2 s squeeze).
The single-stage rows are retained as the measured record of the
bullet-featherstone per-pair force-response dead band; kiss (squeeze 0) is
the measured control confirming a zero-force close cannot produce a
bilateral window.  Raw-run paths and SHA-256 values are in
`m1b-adr0016b-top-contact-height-calibration.json`.
