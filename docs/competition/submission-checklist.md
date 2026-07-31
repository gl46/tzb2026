# Submission checklist

| Item | Owner | Status | Evidence |
| --- | --- | --- | --- |
| Simulation environment | M2A | pass with retained dynamic limitations | Isaac Sim 6.0.1, dual RTX 3080, official Franka |
| Perception module | M2A | software/data-contract verified | public RGB-D and track audit; no Oracle input |
| Virtual dataset and split | M2A | READY | 550 valid episodes, 11 READY shards, 418/66/66 split |
| Fine-tuned open-domain model | M2A | pass with limitations | Qwen LoRA two-seed ablation; no FailureContext gain or generalization claim |
| Closed-loop task/recovery | M2A | smoke only | ten Isaac scenes, 50/50 B0 fallbacks; task success not established |
| Demo/video/rosbag | M2A | partial | one honest QRM representative-failure clip; success and WRONG_OBJECT clips missing |
# M2A additions

- [x] Retain the versioned READY manifest and dataset card locally.
- [ ] Retain a hash-verifiable RGB-D task-success example; the current Pilot
      has zero `task_success=true` episodes.
- [x] Retain a representative QRM failure without editing out
      the failure step.
- [x] Retain one live QRM decision plus B0 fallback video/log; label it as
      failure, not success.
- [x] Package training and inference configuration without checkpoints or
      caches in Git.
- [x] Confirm public observations and prompts contain no Isaac entity truth.
- [x] Export 30 distinct-scene canonical transitions to a LeRobot v3 sample
      with no TeacherResponse or privileged simulator truth.
- [ ] Capture a synchronized WRONG_OBJECT recovery video. The accepted M1B
      JSON evidence is not a substitute for this missing clip.
