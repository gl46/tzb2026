# QRM-Real-V1 dataset

- samples: **381**
- episodes: **91**
- real/synthetic: 381/0
- failure/recovery fraction: 0.420
- synthetic train fraction: 0.000
- splits train/val/test: 285/50/46
- by source: `{"m1a-contact-gate": 140, "m1a-contact-gate-historical": 18, "m1a-friction-trials": 20, "m1a-friction-trials-historical": 60, "m0-empty-grasp": 100, "m1a-motion-execution": 30, "m1a-contact-calibration": 13}`
- gate checklist: `{"real_episodes_ge_50": true, "real_chunks_ge_300": true, "failure_frac_ge_0_30": true, "synthetic_train_frac_le_0_50": true, "episode_level_split": true, "oracle_not_in_online_obs_contract": true}`

Oracle poses are labels/nominal only; online observations use non-oracle track ids.
M1B non-oracle auto-import is reserved as QRM-Real-V2.
