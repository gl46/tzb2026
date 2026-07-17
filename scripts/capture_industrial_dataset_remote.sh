#!/usr/bin/env bash
# Capture one RGB-D frame per seed from seed-specific Gazebo worlds.
set -eo pipefail
if [[ $# -ne 2 ]]; then echo "usage: $0 SEED_START COUNT" >&2; exit 2; fi
seed_start="$1"
count="$2"
source /opt/ros/jazzy/setup.bash
set -u
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
gz_pid=""
bridge_pid=""
cleanup() {
  for pid in "$bridge_pid" "$gz_pid"; do
    [[ -z "$pid" ]] && continue
    kill -INT "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
for ((offset=0; offset<count; offset++)); do
  seed=$((seed_start + offset))
  output="data/generated/m1b_alpha_v1/frames/$seed"
  [[ -f "$output/recording.json" ]] && continue
  mkdir -p "$output" logs
  gz sim -s -r "data/generated/m1b_alpha_v1/scenes/scene-$seed.sdf" >"logs/m1b-alpha-dataset-$seed.log" 2>&1 &
  gz_pid=$!
  bridge_pid=""
  sleep 4
  ros2 run ros_gz_bridge parameter_bridge "/xh/camera/rgbd/image@sensor_msgs/msg/Image[gz.msgs.Image" "/xh/camera/rgbd/depth_image@sensor_msgs/msg/Image[gz.msgs.Image" "/xh/camera/rgbd/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo" >"$output/bridge.log" 2>&1 &
  bridge_pid=$!
  sleep 2
  python3 scripts/record_m1b_alpha_ros.py --sensor-only --output-dir "$output" --duration-s 12 --max-skew-ms 200
  cleanup
  gz_pid=""
  bridge_pid=""
  echo "CAPTURED seed=$seed"
done
