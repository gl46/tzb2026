# M2B S1 physical failure smoke

- status: **PASS_PHYSICAL_ONLY_PUBLIC_RGBD_PENDING**
- EMPTY_GRASP: close issued, no bilateral grasp/attachment; hand lift 0.049021 m, target motion 0.000000557 m; physical regrasp/lift passed.
- RELEASE_FAILURE: open issued while attachment remained; carried follow 0.029030 m, follow error 0.000855 m; retry detach/retreat passed.
- WRONG_OBJECT: actual contacted entity was attached and safely placed; public reassociation and target regrasp remain pending.
- Dataset V2 admitted: 0 (public RGB-D pending).
- Teacher used: no.

## Limitations

- The actuation probe does not capture synchronized public RGB-D predicates.
- WRONG_OBJECT reassociation and target regrasp have not yet executed.
- These smokes prove physical injection/recovery mechanics only and are not Dataset V2 episodes.
