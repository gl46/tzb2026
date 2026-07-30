#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--dry-run" ]]; then
  printf '%s\n' "gz sim -r robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
  exit 0
fi
command -v gz >/dev/null || { echo "gz is required" >&2; exit 2; }
exec gz sim -r robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf
