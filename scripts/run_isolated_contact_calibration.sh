#!/usr/bin/env bash
# S0 calibration with one fresh Gazebo/MoveIt session per required condition.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
mkdir -p logs
# Keep the whole 13-condition audit single-writer.  A child starts a fresh
# Gazebo session, so overlapping parents otherwise race the best-effort remote
# scene probe before either world is discoverable.  `mkdir` is atomic and is
# available on both macOS and the Linux simulator host (unlike `flock`).
lock_dir="$ROOT/logs/.m1a-isolated-contact-calibration.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
  printf 'M1A_S0_CAMPAIGN_ALREADY_RUNNING\n' >&2
  exit 75
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM
labels=(left_1 left_2 left_3 right_1 right_2 right_3 bilateral_1 bilateral_2 bilateral_3 object_environment_1 object_environment_2 table_1 table_2)
logs=()

for label in "${labels[@]}"; do
  child_run_id="${RUN_ID}-${label}"
  # Always continue to the next independent condition so a failed endpoint is
  # represented as missing evidence by the fail-closed aggregator, rather than
  # silently truncating the 13-condition audit under `set -e`.
  if ! M1A_RUN_ID="$child_run_id" M1A_CALIBRATION_SCOPE=one M1A_CALIBRATION_LABEL="$label" \
    bash "$ROOT/scripts/run_contact_calibration.sh"; then
    printf 'M1A_S0_CHILD_RUN_FAILED:%s\n' "$label" >&2
  fi
  logs+=("$ROOT/logs/${child_run_id}-s0-contact-calibration.log")
done

python3 "$ROOT/scripts/aggregate_isolated_contact_calibration.py" "$RUN_ID" "${logs[@]}"
