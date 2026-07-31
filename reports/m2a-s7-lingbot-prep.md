# M2A S7 LingBot / LeRobot preparation

- status: **PASS_BASELINE_PREP_ONLY**
- Teacher: disabled; this baseline is not connected to the control stack.
- canonical episodes exported: 30
- distinct scene groups: 30
- LeRobot dataset version: `v3.0`
- action: raw 9D named Panda joint-position target at 30 Hz; no remapping or normalization was applied
- maximum adjacent-frame alignment error: 0 ns
- privileged simulator truth exported: False
- Teacher response exported: False
- output bytes: 5429822
- official Hugging Face datasets image/action readback: PASS

## Baseline decision

- Current upstream candidate: LingBot-World v2 14B causal-fast.
- License: CC BY-NC-SA 4.0; commercial use is blocked pending human review.
- Official example uses eight GPUs. Disk, VRAM, and runtime must be measured in a separate authorized baseline task; they are not guessed here.
- Model repository metadata reports 86.07 GB; reserve about 180 GB planning headroom for weights, caches, and an isolated environment.
- Planning budget for environment setup, download, and one smoke: 4–8 hours. This is not a measured runtime or a training estimate.
- node2 has one A100 80 GB, while the official command uses eight GPUs; single-A100 feasibility is unvalidated.
- v1 remains recorded as an Apache-2.0 historical fallback, but was not silently selected because upstream marks it unmaintained.

## Limitations

- This is a format-validation sample, not LingBot training.
- Each canonical record has one action; no terminal action was invented.
- LingBot-World v2 is non-commercial CC BY-NC-SA 4.0.
- The official v2 example uses eight GPUs; no single-A100 runtime claim is made.
- No LingBot weight was downloaded and no VRAM/throughput metric was fabricated.
