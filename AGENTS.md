# Project rules

1. The world-model mainline is mandatory; safety/state machines cannot replace prediction and selection.
2. P0 Gazebo closed loop takes precedence over every large Teacher task.
3. The Student world model must train and run without Teacher soft labels.
4. Teachers are pluggable through the stable adapter and cannot enter the control stack.
5. Current Teacher state is Nano `CANDIDATE`, BWM `CANDIDATE_LICENSE_PENDING`, Super `PARKED`.
6. Codex must not silently replace or upgrade a Teacher.
7. Formal model changes require a human ADR.
8. Gates: P0 on 2026-07-20 and Teacher lock on 2026-07-22 (Asia/Shanghai).
9. Teacher kill rules must be reported explicitly.
10. Privileged simulator truth must never become test-time policy input.
11. Action frame, units, dimensions, frequency, and normalization are explicit protocol fields.
12. No model action mapping may be guessed without official evidence.
13. Supervision priority: simulator hard truth > Teacher soft label > semantic pseudo-label.
14. `TeacherResponse` is optional in `EpisodeTransition`.
15. Safety/event/controller components may not replace the world-model role.
16. Every new code path has a test or verification command.
17. Never fabricate experiment, throughput, VRAM, or success metrics.
18. Never expose secrets or commit large artifacts.
19. Each task report lists changed files, tests, failures, blockers, and one next command.
