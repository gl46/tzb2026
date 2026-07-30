# M1B-alpha preflight

- Baseline tag / local HEAD: `m1a-contact-gated-grasp` / `0709cc1`.
- Existing unit regression: `53 passed` before Alpha changes.
- Current Alpha unit regression: recorded after implementation in final status.
- Local host: macOS; no ROS/Gazebo. `node2` reports ROS 2 Jazzy, Gazebo 8.11,
  MoveIt and an A100 available.
- User worktree contained untracked Teacher-suite files and a PDF. They are not
  part of this Goal and are left untouched.
- The original `/home/gl/xh-202607-world-agent` deployment has no `.git`.
  M1B uses isolated `/home/gl/xh-202607-world-agent-codex-m1b`.
