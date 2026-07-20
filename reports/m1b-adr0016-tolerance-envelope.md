# M1B ADR-0016 tolerance-envelope measurement

Status: **COMPLETE_CALIBRATION_ONLY; zero envelope; NO-GO input**.

The complete 81-trial campaign completed on node2. It used the production
grasp primitive and production contact/broker/attach gates, with simulator
truth limited to calibration-only target initialization. The immutable summary
is `/tmp/m1b-tolerance-adr0016-run/m1b-tolerance-envelope.json` (SHA-256
`bb602416012693c3225de9e342f35ee29bd049c8bc3072ffa74f50d9ec335a3d`).

The 2-of-3 zero-offset point failed on every axis (X 0/3, Y 0/3, Z 0/3).
Therefore the signed monotonic closure measured no positive tolerance on X, Y,
or Z. This is a physical grasp-primitive result, not a perception-gate
relaxation.
