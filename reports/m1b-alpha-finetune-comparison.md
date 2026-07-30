# M1B-alpha post-training comparison

`color_prototype_adapter_v1` is a lightweight post-training semantic head: it
uses train-only count supervision to select RGB cosine threshold 0.95 and saves
no scene seed, entity identifier, pose or test label in the online config.
Validation used the separate 30-scene seed split.

| Held-out metric (30 scenes) | Pre-calibration 0.97 | Calibrated 0.95 |
| --- | ---: | ---: |
| Valid output rate | 96.7% | 96.7% |
| Median absolute track-count error | 6.0 | 0.0 |
| Matched-track recall | 39.0% | 91.5% |
| Leftmost-target selection | 40.0% | 96.7% |
| 3D position median error | 2.24 cm | 2.17 cm |
| Orientation-state accuracy | 34.7% | 37.1% |

The detailed calibration and test records are
`reports/m1b-alpha-v2-color-calibration.json`,
`reports/m1b-alpha-v2-precalibration-heldout.json`, and
`reports/m1b-alpha-v2-calibrated-heldout.json`.

GroundingDINO-tiny was selected under Apache-2.0 code terms and its runtime
dependencies were installed in a dedicated environment. Its official Hugging
Face configuration endpoint did not respond within 15 seconds, so no weight,
pretrained metric, fine-tuned checkpoint or claimed open-vocabulary result is
present. This is the declared limitation; the calibrated non-Oracle RGB-D
fallback is the Beta input.
