# ADR-0016 S0 recalibration

- Status: `CONTACT_TELEMETRY_CALIBRATED`
- Run: `m1a-adr0016-inline-s0-final-20260720-1220`
- Result: `13/13` independently reset conditions passed; all `9/9` finger-target positive windows passed; all `13/13` idle baselines passed.
- Bilateral contact overlaps: `0.254 s`, `0.277 s`, and `0.247 s` (required: at least `0.1 s`).
- Model match: local and node2 Gazebo URDF SHA-256 were both `13f8c715948d602388b0024b38f0ab354359e5232f981596d854f866a5eee854`.
- Provenance: `CALIBRATION_ONLY_INITIALIZATION_PER_LABEL`; runtime oracle was used only for the S0 calibration fixture, never for the online M1B policy path.
- Aggregate evidence SHA-256: `c7d1361fdcb23b8221e701e59ac68ac39b619aa01fa562a96b088677c0f362b8`.
