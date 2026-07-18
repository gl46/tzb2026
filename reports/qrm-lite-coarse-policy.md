# QRM-Lite coarse policy

- samples: 100
- final skill accuracy: 1.000
- final loss: 0.017265
- overfit_verified: True
- checkpoint: `artifacts/qrm_lite/coarse_overfit.npz`

## Examples

```json
[
  {
    "sample_id": "p0-empty-grasp-01-0",
    "target_skill": "LIFT",
    "pred_skill": "LIFT",
    "target_fail": "EMPTY_GRASP",
    "pred_fail": "EMPTY_GRASP",
    "failure_context_used": "EMPTY_GRASP"
  },
  {
    "sample_id": "p0-empty-grasp-02-1",
    "target_skill": "PLACE",
    "pred_skill": "PLACE",
    "target_fail": "EMPTY_GRASP",
    "pred_fail": "EMPTY_GRASP",
    "failure_context_used": "EMPTY_GRASP"
  },
  {
    "sample_id": "p0-empty-grasp-03-2",
    "target_skill": "LIFT",
    "pred_skill": "LIFT",
    "target_fail": "EMPTY_GRASP",
    "pred_fail": "EMPTY_GRASP",
    "failure_context_used": "EMPTY_GRASP"
  },
  {
    "sample_id": "p0-empty-grasp-04-3",
    "target_skill": "APPROACH",
    "pred_skill": "APPROACH",
    "target_fail": "EMPTY_GRASP",
    "pred_fail": "EMPTY_GRASP",
    "failure_context_used": "EMPTY_GRASP"
  },
  {
    "sample_id": "p0-empty-grasp-05-4",
    "target_skill": "REOBSERVE",
    "pred_skill": "REOBSERVE",
    "target_fail": "EMPTY_GRASP",
    "pred_fail": "EMPTY_GRASP",
    "failure_context_used": "EMPTY_GRASP"
  }
]
```

FailureContext fields are part of the context vector (one-hot + residual counts).
