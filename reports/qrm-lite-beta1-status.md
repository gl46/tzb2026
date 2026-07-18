# QRM-Lite Beta-1 status

- status: **IN_PROGRESS_BOOTSTRAPPED**
- alpha freeze: tag `qrm-lite-alpha` @ `0287d23`, verdict `GO_COARSE_AND_MLP_ONLY`
- Flow: **IMPLEMENTED_NOT_SELECTED**
- branch: `codex/qrm-lite-beta1`

## Real-V1 gates
```json
{
  "real_episodes_ge_50": true,
  "real_chunks_ge_300": true,
  "failure_frac_ge_0_30": true,
  "synthetic_train_frac_le_0_50": true,
  "episode_level_split": true,
  "oracle_not_in_online_obs_contract": true
}
```
- samples/episodes: 381/91
- failure fraction: 0.420
- synthetic train frac: 0.0

## Q0/Q1/Q2
```json
{
  "Q0_COARSE_ONLY": {
    "val_skill_acc": 0.7,
    "beats_zero_residual": null,
    "uses_fc": false
  },
  "Q1_COARSE_MLP_RESIDUAL": {
    "val_skill_acc": 0.7,
    "beats_zero_residual": true,
    "uses_fc": false
  },
  "Q2_COARSE_MLP_FAILURE_CONTEXT": {
    "val_skill_acc": 0.7,
    "beats_zero_residual": true,
    "uses_fc": true
  }
}
```
- majority baseline: 0.14

## FailureContext ablation
Primary metric is same-failed-action repetition rate (Q1 vs Q2). Current offline pass is bootstrapped; Gazebo 20-ep loop still required for claim.

## Next
- rsync/codex branch to fx@chxy and stand up resident QwenPolicyService
- improve recovery supervision labels for Q1 vs Q2 discrimination
- run 20-episode empty-grasp recovery on node2 when M1B idle
- decide GO_QRM_BETA_2 / GO_QRM_COARSE_ONLY / STOP_QRM_ACTION_REFINER
