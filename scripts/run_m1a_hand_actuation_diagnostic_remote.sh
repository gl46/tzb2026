#!/usr/bin/env bash
# Fresh-simulator side of the approved Option 1 diagnostic sequence.
set -eo pipefail

root="$1"
output_log="$2"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
tmp="$(mktemp -d)"
launch_log="$tmp/launch.log"
mkdir -p "$(dirname "$output_log")"
: >"$output_log"
exec >>"$output_log" 2>&1
ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=false >"$launch_log" 2>&1 & pid=$!
kill_tree() {
  local signal="$1" process="$2" child
  for child in $(pgrep -P "$process" 2>/dev/null || true); do
    kill_tree "$signal" "$child"
  done
  kill "-$signal" "$process" 2>/dev/null || true
}
cleanup() {
  # Keep this launch in the invoking shell's process tree.  A detached
  # ``setsid`` child can let SSH return before the diagnostic JSON is emitted.
  kill_tree TERM "$pid"
  sleep 1
  kill_tree KILL "$pid"
  wait "$pid" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM
sleep 16
echo "M1A_HAND_DIAGNOSTIC_LAUNCH_PID:$pid"
set +e
timeout -k 30 150 python3 "/home/$USER/$root/scripts/m1a_hand_actuation_diagnostic.py"
diagnostic_status=$?
set -e
if [[ "$diagnostic_status" -ne 0 ]]; then
  echo "M1A_HAND_DIAGNOSTIC_LAUNCH_LOG_TAIL"
  tail -n 160 "$launch_log" || true
fi
echo "M1A_HAND_DIAGNOSTIC_REMOTE_DONE:$diagnostic_status"
exit "$diagnostic_status"
