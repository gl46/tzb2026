# Submission checklist

| Item | Owner | Status | Evidence |
| --- | --- | --- | --- |
| Simulation environment | M1B-alpha | in progress | industrial SDF and configuration |
| Perception module | M1B-alpha | software verified | `xh_agent.perception` tests |
| Virtual dataset and split | M1B-alpha | fixture verified | seed manifest generator |
| Fine-tuned open-domain model | M1B-alpha | pending | adapter only; no checkpoint claimed |
| Closed-loop task/recovery | M1B-beta | blocked by Alpha gate | not started |
| Demo/video/rosbag | M1B-alpha | pending live runtime | recorder contract only |
# M2A additions

- [ ] Publish the versioned READY manifest and dataset card.
- [ ] Retain a hash-verifiable RGB-D success example.
- [ ] Retain a representative perception/recovery failure without editing out
      the failure step.
- [ ] Retain one live QRM decision plus B0 fallback video/log.
- [ ] Package training and inference configuration without checkpoints or
      caches in Git.
- [ ] Confirm public observations and prompts contain no Isaac entity truth.
