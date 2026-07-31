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
