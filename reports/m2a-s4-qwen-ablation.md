# M2A S4 Qwen FailureContext ablation

- status: **PASS_WITH_LIMITATIONS**
- paired seeds: 20260731, 20260732
- mean accuracy delta (on - off): 0.000000
- mean macro-F1 delta (on - off): 0.000000
- Teacher used: `False`
- dataset manifest hash: `9843968cdbff17b6b4a291e30907f2c5dc855838ad3e4be7095a4bb8783449bc`
- training code revision: `5f5abb80665e3bb553d905f72e46630d2e244975`
- configured base revision: `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`
- raw runtime revision metadata: `['']`

| seed | off accuracy | on accuracy | delta | off macro-F1 | on macro-F1 |
|---:|---:|---:|---:|---:|---:|
| 20260731 | 0.700000 | 0.700000 | 0.000000 | 0.411765 | 0.411765 |
| 20260732 | 0.740000 | 0.740000 | 0.000000 | 0.425287 | 0.425287 |

## Limitations

- Each paired run uses one epoch, at most 120 train samples, and 50 held-out test samples.
- Two seeds on one 550-episode Pilot dataset cannot establish deployment benefit.
- Physical EMPTY_GRASP, RELEASE_FAILURE, and WRONG_OBJECT cases are absent.
- FailureContext did not improve held-out accuracy for every seed.
- The local Qwen snapshot did not retain Hub revision metadata; the configured base revision is recorded but not independently verified by the raw training reports.
