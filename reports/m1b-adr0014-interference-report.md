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

Two reset-isolated calibration diagnostics narrowed the cause further. With
target collision retained, a 60-degree candidate at 65 mm executed its
high-clear and low-clear stages but its final lateral pose could not be planned.
With a target-touch exception limited to the final 65 mm insert, the yaw-0
candidate again executed high-clear and low-clear, but final-insert IK failed
with `-31`; the exception was restored. Neither diagnostic closed the hand,
formed contact, attached an object, or changes the production primitive.

Finally, a non-moving vertical-board IK/planning scan considered 21 candidates
from reset home and found zero collision-checked plans. The current horizontal,
lateral, and vertical-board pose families therefore provide no physical path to
promote. A further production geometry/scene or primitive change requires a
new approved decision before the 81-trial measurement can resume.
