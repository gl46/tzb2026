#!/usr/bin/env bash
# Fresh simulator half of the isolated two-finger controller probe.
set -eo pipefail

root="$1"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
tmp="$(mktemp -d)"
launch_log="$tmp/launch.log"
export XH_SIM_GENERATED_SDF_DIR="$tmp/generated"
setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=false >"$launch_log" 2>&1 </dev/null & pid=$!
launch_pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
cleanup() {
  kill -TERM -- "-$launch_pgid" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$launch_pgid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM
sleep 16
echo "M1A_HAND_PROBE_LAUNCH_PID:$pid"
installed_urdf="/home/$USER/$root/robot_ws/install/xh_sim/share/xh_sim/urdf/panda_controlled.urdf"
source_urdf="/home/$USER/$root/robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
echo "M1A_HAND_PROBE_LAUNCH_URDF_SHA256:$(sha256sum "$installed_urdf" | awk '{print $1}')"
echo "M1A_HAND_PROBE_SOURCE_URDF_SHA256:$(sha256sum "$source_urdf" | awk '{print $1}')"
if [ -f "$XH_SIM_GENERATED_SDF_DIR/panda_controller.manifest.json" ]; then
  echo -n "M1A_HAND_PROBE_GENERATED_SDF_MANIFEST:"
  jq -c . "$XH_SIM_GENERATED_SDF_DIR/panda_controller.manifest.json"
else
  echo "M1A_HAND_PROBE_GENERATED_SDF_MANIFEST_MISSING"
fi
ros2 control list_hardware_interfaces 2>&1 || true
grep -E 'mimic constraint|is mimicking joint' "$launch_log" || true
timeout -k 30 120 python3 "/home/$USER/$root/scripts/m1a_hand_actuation_probe.py"
