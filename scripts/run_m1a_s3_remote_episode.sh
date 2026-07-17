#!/usr/bin/env bash
# Remote half of one S3 reset episode. Invoked only by run_contact_gated_grasp.sh.
set -eo pipefail

root="$1"
config_b64="$2"
config_json="$(printf '%s' "$config_b64" | base64 -d)"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo M1A_S3_REMOTE_SIM_ALREADY_RUNNING
  exit 0
fi
tmp="$(mktemp -d)"
launch_log="$tmp/launch.log"
setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=false >"$launch_log" 2>&1 & pid=$!
launch_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
cleanup() {
  kill -TERM -- "-$launch_pgid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$launch_pgid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$launch_log"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM
sleep 16
echo "M1A_S3_LAUNCH_PID:$pid"
echo "M1A_S3_LAUNCH_PGID:$launch_pgid"
installed_urdf="/home/$USER/$root/robot_ws/install/xh_sim/share/xh_sim/urdf/panda_controlled.urdf"
source_urdf="/home/$USER/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
echo "M1A_S3_LAUNCH_URDF_SHA256:$(sha256sum "$installed_urdf" | awk '{print $1}')"
echo "M1A_S3_SOURCE_URDF_SHA256:$(sha256sum "$source_urdf" | awk '{print $1}')"
if ! kill -0 "$pid" 2>/dev/null; then
  echo M1A_S3_LAUNCH_FAILED
  sed -n '1,220p' "$launch_log"
  exit 0
fi
timeout -k 30 300 env M1A_S3_CONFIGURATION_JSON="$config_json" \
  python3 "/home/$USER/$root/scripts/m1a_contact_gated_trial_client.py"
echo M1A_S3_LAUNCH_TAIL
tail -n 160 "$launch_log"
