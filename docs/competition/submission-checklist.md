# Submission checklist

| Item | Owner | Status | Evidence |
| --- | --- | --- | --- |
| Simulation environment | M2A | pass with retained dynamic limitations | Isaac Sim 6.0.1, dual RTX 3080, official Franka |
| Perception module | M2A | software/data-contract verified | public RGB-D and track audit; no Oracle input |
| Virtual dataset and split | M2A | READY | 550 valid episodes, 11 READY shards, 418/66/66 split |
| Fine-tuned open-domain model | M2A | pass with limitations | Qwen LoRA two-seed ablation; no FailureContext gain or generalization claim |
| Closed-loop task/recovery | M2B | pass with attribution limitation | 20 frozen matched keys; B0/FC system success 1.0, but FC used fixed B0 continuation |
| Demo/video/rosbag | M2C S1 | READY with sparse-capture disclosure | hash-bound task-success RGB-D plus WRONG_OBJECT and model/B0 attribution videos |
# M2A additions

- [x] Retain the versioned READY manifest and dataset card locally.
- [x] Retain a hash-verifiable RGB-D task-success example. M2C S1 exports
      `/Users/gl/tzb-m2c-evidence/m2c-s1/task-success-rgbd/manifest.json`,
      bound to the frozen M2B closed-loop episode `final_success=true`; the raw
      actuation probe has no `task_success` field and the manifest discloses
      that provenance explicitly.
- [x] Retain a representative QRM failure without editing out
      the failure step.
- [x] Retain one live QRM decision plus B0 fallback video/log; label it as
      failure, not success.
- [x] Package training and inference configuration without checkpoints or
      caches in Git.
- [x] Confirm public observations and prompts contain no Isaac entity truth.
- [x] Export 30 distinct-scene canonical transitions to a LeRobot v3 sample
      with no TeacherResponse or privileged simulator truth.
- [x] Capture synchronized WRONG_OBJECT recovery evidence. M2C S1 retains all
      four public RGB-D captures in monotonic source-timestamp order and an
      aligned decision-attribution video under
      `/Users/gl/tzb-m2c-evidence/m2c-s1/`. Both videos disclose that the
      source is sparse retained RGB-D evidence rather than a continuous camera
      recording, and that fixed B0 owns the final two recovery decisions.
