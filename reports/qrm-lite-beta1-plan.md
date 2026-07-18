# QRM-Lite Beta-1 plan (post Alpha freeze)

## Freeze
- tag: `qrm-lite-alpha`
- commit: `0287d23`
- verdict: `GO_COARSE_AND_MLP_ONLY`
- Flow: `IMPLEMENTED_NOT_SELECTED`

## Core question
Does **FailureContext** reduce **same-failed-action repetition** and improve recovery skill selection on real data + minimal Gazebo recovery?

## Formal models
1. **Q0** Coarse-only
2. **Q1** Coarse + MLP residual (default continuous path)
3. **Q2** Q1 + FailureContext (core ablation)

Flow is appendix only.

## Workstream order
1. Import M1A → **QRM-Real-V1**
2. Train Q0 → Q1 → Q2
3. Offline Q1 vs Q2 ablation (repetition rate)
4. Resident Qwen latency service on **chxy**
5. 20-episode empty-grasp recovery loop on **node2** only if M1B idle
6. Gate: `GO_QRM_BETA_2` | `GO_QRM_COARSE_ONLY` | `STOP_QRM_ACTION_REFINER`

## Topology
| Host | Role |
| --- | --- |
| `fx@chxy` | train, Qwen service, offline ablations |
| `gl@node2` | 20-ep recovery only, no long train |
| local worktree | code/report, no main merge yet |
