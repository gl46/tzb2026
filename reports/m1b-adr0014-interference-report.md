# M1B ADR-0014 physical interference report

Status: **MEASURED_PHYSICAL_BLOCKER**

The 30 mm-cylinder revalidation did not fail at perception. Across all 81
production-primitive trials, 69 terminal contact-descend IK requests failed
with code `-31`; six trials did not execute approach, leaving only five
terminal descents and closes.

| Observation | Count |
| --- | ---: |
| Trials | 81 |
| Contact-descend IK solved / failed / not reached | 5 / 69 / 7 |
| Close succeeded | 5 |
| Bilateral same-target contact | 0 |
| Attach command sent | 0 |
| Trials with any contact sample | 4 |

The four nonempty contact traces identify 1,123 table-contact samples (right
finger 732, left finger 391) and 466 right-finger samples against
`cylinder_09`. Their commanded target was `cylinder_07`; no target-contact
sample was recorded.

Thus the immediate engineering problem is a collision-safe, terminal
contact-descend path that clears the table and neighboring cylinders. This is
an evidence-backed diagnosis, not a license to relax any gate. After a
corrective motion/geometry change, the full 81-trial envelope and the unchanged
p90 gate must be rerun before either acceptance exercise.
