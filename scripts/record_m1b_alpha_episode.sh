#!/usr/bin/env bash
set -euo pipefail
output_dir="${1:-data/episodes/m1b-alpha}"
mkdir -p "$output_dir"
printf '%s\n' "This recorder must run next to a live ROS/Gazebo session; no synthetic video is emitted." >&2
python3 - <<'PY' "$output_dir"
import json, sys
from pathlib import Path
out = Path(sys.argv[1]) / "recording-blocked.json"
out.write_text(json.dumps({"status": "BLOCKED_NO_LIVE_ROS_SESSION", "required": ["rgb", "depth", "camera_info", "tf", "joint_states", "rosbag2"]}, indent=2) + "\n")
PY
exit 2
