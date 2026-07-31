# M2B S1 physical failure smoke

- status: **PASS_PUBLIC_FAILURES_AND_RECOVERIES**
- EMPTY_GRASP: close issued, no bilateral grasp/attachment; hand lift 0.049154 m, target motion 0.000000030 m; physical regrasp/lift passed.
- RELEASE_FAILURE: open issued while attachment remained; carried follow 0.079029 m, follow error 0.001064 m; retry detach/retreat passed.
- WRONG_OBJECT: actual contacted entity was attached and safely placed; public reassociation and target regrasp passed.
- Public RGB-D failure predicates: captured and validated for all three failures.
- Eligible recovery evidence: all three mandatory failure classes.
- Dataset V2 admitted: 0 (canonical episode packing pending).
- Teacher used: no.

## Limitations

- Canonical FailureContextV1/EpisodeTransition packing remains pending; raw smoke evidence is not yet Dataset V2.
