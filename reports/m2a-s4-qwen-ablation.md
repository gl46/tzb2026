# M2A S4 Qwen FailureContext ablation

- status: **PASS_WITH_LIMITATIONS**
- paired seeds: 20260731, 20260732
- mean accuracy delta (on - off): 0.000000
- mean macro-F1 delta (on - off): 0.000000

| seed | off accuracy | on accuracy | delta | off macro-F1 | on macro-F1 |
|---:|---:|---:|---:|---:|---:|
| 20260731 | 0.700000 | 0.700000 | 0.000000 | 0.411765 | 0.411765 |
| 20260732 | 0.740000 | 0.740000 | 0.000000 | 0.425287 | 0.425287 |

## Limitations

- Each paired run uses one epoch, at most 120 train samples, and 50 held-out test samples.
- Two seeds on one 550-episode Pilot dataset cannot establish deployment benefit.
- Physical EMPTY_GRASP, RELEASE_FAILURE, and WRONG_OBJECT cases are absent.
- FailureContext did not improve held-out accuracy for every seed.
