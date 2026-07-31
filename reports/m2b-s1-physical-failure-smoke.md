# M2B S1 physical failure smoke

- status: **PASS_PUBLIC_FAILURES_TWO_RECOVERIES_WRONG_RECOVERY_PENDING**
- EMPTY_GRASP: close issued, no bilateral grasp/attachment; hand lift 0.049021 m, target motion 0.000000557 m; physical regrasp/lift passed.
- RELEASE_FAILURE: open issued while attachment remained; carried follow 0.029031 m, follow error 0.000855 m; retry detach/retreat passed.
- WRONG_OBJECT: actual contacted entity was attached and safely placed; public reassociation and target regrasp remain pending.
- Public RGB-D failure predicates: captured and validated for all three failures.
- Eligible recovery evidence: EMPTY_GRASP and RELEASE_FAILURE; WRONG_OBJECT target regrasp pending.
- Dataset V2 admitted: 0 (canonical episode packing pending).
- Teacher used: no.

## Limitations

- WRONG_OBJECT reassociation and target regrasp have not yet executed.
- Canonical FailureContextV1/EpisodeTransition packing remains pending; raw smoke evidence is not yet Dataset V2.
