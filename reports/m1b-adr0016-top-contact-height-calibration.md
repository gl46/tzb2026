# ADR-0016 top-contact height calibration

Status: **measured single-point selection; not a tolerance-envelope result**.

The production top-down primitive was executed with evaluator-only supervision
for its zero-offset initialization.  No supervision value is read by the
online production path.  Each accepted probe first passed the mandatory
physical reset non-coupling check.

| Hand contact height | Final descent | Bilateral same entity | Attach confirmation | Result |
| --- | --- | --- | --- | --- |
| 100 mm | IK -31 | no | no | reject |
| 120 mm | executed | yes | `cylinder_01: attached` | select |
| 140 mm | executed | no contact samples | no | reject |

The selected production centreline is **120 mm**.  This is intentionally not
claimed as a continuous height envelope: the lower probe did not reach final
contact, while the upper probe did and had no contact.  The next evidence is
the complete 81-trial offset campaign, not an extrapolated success rate.

Raw-run paths and SHA-256 values are recorded in
`m1b-adr0016-top-contact-height-calibration.json`.
