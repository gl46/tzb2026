# M1B ADR-0016b acceptance status (2026-07-24)

Status: **`NO_GO`**.

The measured p90 gate remains closed: X/Y/Z perception p90 is 9.88 / 15.13 /
17.30 mm, while the corresponding `0.6 × tolerance` limits are 9.0 / 9.0 /
3.0 mm. The measured fallback-hand envelope is nonzero (15 / 15 / 5 mm), but
that does not authorize ADR-0013 acceptance items 3 or 4.

The existing `m1b-adr0016b-attached-roundtrip` and
`m1b-adr0016b-wrong-object-drill` files are diagnostic-only and must not be
counted as accepted Beta evidence: they were executed while the p90 gate was
`NO_GO`. The latter's former simulation-spawn proximity association has also
been removed; current code accepts a carried public track only when exactly
one pre-grasp public track is vacated, otherwise it fails closed and reobserves.

The valid next work is to measure a contact-seeking terminal-descent candidate
under the existing calibration-only boundary, then re-run the physical
tolerance envelope and the unchanged p90 comparison. No threshold may be
relaxed, and no acceptance drill may run unless that comparison becomes `GO`.

