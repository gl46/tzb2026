#!/usr/bin/env bash
# Bounded P0 smoke test.  It records only observed runtime evidence; a passed
# controller action is deliberately not promoted to a pick-place success.
set -euo pipefail

mkdir -p reports
python_bin="python3"
if [[ -x .venv/bin/python ]]; then python_bin=".venv/bin/python"; fi

status="BLOCKED_SYSTEM_DEPENDENCY"
reason="ros2 and Gazebo Harmonic are not both available on this host"
platform_host="local"
project_remote_root="${PROJECT_REMOTE_ROOT:-}"
remote_output=""

if [[ "${ALLOW_SIM_RUN:-1}" != "1" ]]; then
  status="NOT_RUN_GATE_DISABLED"
  reason="ALLOW_SIM_RUN is not 1"
elif [[ -n "${SIM_HOST:-}" ]]; then
  platform_host="${SIM_HOST}"
  sim_user="${SIM_USER:-}"
  if [[ -z "$sim_user" ]]; then
    case "$SIM_HOST" in
      node2) sim_user="gl" ;;
      chxy) sim_user="fx" ;;
      *) sim_user="${USER}" ;;
    esac
  fi
  # A remote project path is intentionally constrained before it is passed as
  # an argument to the remote shell, avoiding arbitrary command construction.
  if [[ -n "$project_remote_root" && ! "$project_remote_root" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    status="BLOCKED_INVALID_PROJECT_REMOTE_ROOT"
    reason="PROJECT_REMOTE_ROOT must be a simple relative path"
  else
    remote_output="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "${sim_user}@${SIM_HOST}" "bash -s -- '${project_remote_root}'" <<'REMOTE'
set -e
project_root="$1"
source /opt/ros/jazzy/setup.bash
if [ -n "$project_root" ]; then
  source "$HOME/$project_root/robot_ws/install/setup.bash"
fi
tmp=$(mktemp -d)
log="$tmp/launch.log"
action="$tmp/action.log"
probe="$tmp/probe.log"
pid=""
cleanup() {
  if [ -n "$pid" ]; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -f "$log" "$action" "$probe"
  rmdir "$tmp" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ -n "$project_root" ]; then
  setsid ros2 launch xh_bringup bringup.launch.py headless:=true >"$log" 2>&1 & pid=$!
  smoke_kind=PROJECT_CONTROL
else
  setsid gz sim -s -r --headless-rendering /opt/ros/jazzy/share/ros_gz_sim_demos/worlds/default.sdf >"$log" 2>&1 & pid=$!
  smoke_kind=PLATFORM_DEFAULT_WORLD
fi

sleep 12
if ! kill -0 "$pid" 2>/dev/null; then
  echo "GAZEBO_HEADLESS_DID_NOT_STAY_UP:$smoke_kind"
  sed -n '1,120p' "$log"
  exit 0
fi
echo "GAZEBO_HEADLESS_STARTED:$smoke_kind"

if [ "$smoke_kind" = PROJECT_CONTROL ]; then
  services=$(gz service -l 2>/dev/null || true)
  if grep -q '/world/xh_p0_pick_place' <<<"$services"; then echo PROJECT_WORLD_SERVICE_FOUND; fi
  scene_info=$(gz service -s /world/xh_p0_pick_place/scene/info --reqtype gz.msgs.Empty --reptype gz.msgs.Scene --timeout 3000 --req '' 2>/dev/null || true)
  for entity in panda_controller panda_p0_stub object_red_cube object_blue_cylinder object_green_sphere bin_a front_rgbd; do
    if grep -Fq "name: \"$entity\"" <<<"$scene_info"; then echo "SCENE_ENTITY_FOUND:$entity"; fi
  done

  controllers=$(timeout -k 1 6 ros2 control list_controllers 2>&1 || true)
  for controller in joint_state_broadcaster panda_arm_controller panda_hand_controller; do
    if grep -Eq "^${controller}[[:space:]].*[[:space:]]active$" <<<"$controllers"; then
      echo "CONTROLLER_ACTIVE:$controller"
    fi
  done

  # Execute conservative trajectories only after the controllers themselves
  # are observed active.  The action result and state reading are checked
  # independently.
  if grep -Eq '^panda_arm_controller[[:space:]].*[[:space:]]active$' <<<"$controllers"; then
    timeout -k 2 18 ros2 action send_goal /panda_arm_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
      '{trajectory: {joint_names: [panda_joint1, panda_joint2, panda_joint3, panda_joint4, panda_joint5, panda_joint6, panda_joint7], points: [{positions: [0.12, -0.25, 0.15, -0.20, 0.10, 0.15, -0.10], time_from_start: {sec: 3}}]}}' >"$action" 2>&1 || true
    if grep -q 'Goal finished with status: SUCCEEDED' "$action"; then echo ARM_ACTION_SUCCEEDED; fi
  fi
  if grep -Eq '^panda_hand_controller[[:space:]].*[[:space:]]active$' <<<"$controllers"; then
    timeout -k 2 15 ros2 action send_goal /panda_hand_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
      '{trajectory: {joint_names: [panda_finger_joint1, panda_finger_joint2], points: [{positions: [0.03, 0.03], time_from_start: {sec: 2}}]}}' >"$action" 2>&1 || true
    if grep -q 'Goal finished with status: SUCCEEDED' "$action"; then echo HAND_ACTION_SUCCEEDED; fi
  fi

  timeout -k 1 6 ros2 topic echo --once /joint_states >"$probe" 2>&1 || true
  if grep -q 'panda_joint1' "$probe"; then echo JOINT_STATE_MESSAGE_RECEIVED; fi
  timeout -k 1 6 ros2 topic echo --once /tf >"$probe" 2>&1 || true
  if grep -q 'child_frame_id:' "$probe"; then echo TF_MESSAGE_RECEIVED; fi
  for topic in /xh/camera/rgbd/image /xh/camera/rgbd/depth_image /xh/camera/rgbd/camera_info; do
    timeout -k 1 7 ros2 topic echo --once "$topic" >"$probe" 2>&1 || true
    if [ -s "$probe" ] && ! grep -qE 'timeout|ERROR|error' "$probe"; then
      echo "ROS_MESSAGE_RECEIVED:$topic"
    fi
  done
fi
REMOTE
)" || true

    if grep -q 'GAZEBO_HEADLESS_STARTED:PROJECT_CONTROL' <<<"$remote_output"; then
      if grep -q 'PROJECT_WORLD_SERVICE_FOUND' <<<"$remote_output"; then
        status="PARTIAL_CONTROL_AND_PERCEPTION_VERIFIED"
        reason="node2 project world, spawned controller-backed arm, ROS control, bounded arm/gripper actions, joint state, TF and RGB-D probes were observed; grasp/release, object transfer, supervision and episode recording remain unverified"
      else
        status="BLOCKED_PROJECT_WORLD_UNVERIFIED"
        reason="xh launch stayed alive but did not expose the expected xh_p0_pick_place world service"
      fi
    elif grep -q 'GAZEBO_HEADLESS_STARTED:PLATFORM_DEFAULT_WORLD' <<<"$remote_output"; then
      status="PARTIAL_PLATFORM_ONLY"
      reason="Gazebo Harmonic actually started headlessly on ${sim_user}@${SIM_HOST}; the xh project workspace was not selected"
    else
      status="BLOCKED_PLATFORM_SMOKE_FAILED"
      reason="remote Gazebo smoke did not start on ${sim_user}@${SIM_HOST}: $(tr '\n' ' ' <<<"$remote_output" | cut -c1-260)"
    fi
  fi
elif command -v ros2 >/dev/null 2>&1 && command -v gz >/dev/null 2>&1; then
  status="NOT_RUN_PROJECT_NOT_BUILT"
  reason="compatible commands found, but no verified built xh_bringup launch package is available"
fi

scene_world_verified=false
robot_spawned=false
rgbd_image_verified=false
rgbd_depth_verified=false
rgbd_camera_info_verified=false
panda_visual_stub_spawned=false
rgbd_sensor_spawned=false
joint_state_verified=false
tf_verified=false
arm_controller_active=false
hand_controller_active=false
arm_action_executed=false
hand_action_executed=false
objects_spawned=0
if grep -q 'PROJECT_WORLD_SERVICE_FOUND' <<<"$remote_output"; then scene_world_verified=true; fi
if grep -q 'SCENE_ENTITY_FOUND:panda_controller' <<<"$remote_output"; then robot_spawned=true; fi
if grep -q 'SCENE_ENTITY_FOUND:panda_p0_stub' <<<"$remote_output"; then panda_visual_stub_spawned=true; fi
if grep -q 'SCENE_ENTITY_FOUND:front_rgbd' <<<"$remote_output"; then rgbd_sensor_spawned=true; fi
if grep -q 'ROS_MESSAGE_RECEIVED:/xh/camera/rgbd/image' <<<"$remote_output"; then rgbd_image_verified=true; fi
if grep -q 'ROS_MESSAGE_RECEIVED:/xh/camera/rgbd/depth_image' <<<"$remote_output"; then rgbd_depth_verified=true; fi
if grep -q 'ROS_MESSAGE_RECEIVED:/xh/camera/rgbd/camera_info' <<<"$remote_output"; then rgbd_camera_info_verified=true; fi
if grep -q 'JOINT_STATE_MESSAGE_RECEIVED' <<<"$remote_output"; then joint_state_verified=true; fi
if grep -q 'TF_MESSAGE_RECEIVED' <<<"$remote_output"; then tf_verified=true; fi
if grep -q 'CONTROLLER_ACTIVE:panda_arm_controller' <<<"$remote_output"; then arm_controller_active=true; fi
if grep -q 'CONTROLLER_ACTIVE:panda_hand_controller' <<<"$remote_output"; then hand_controller_active=true; fi
if grep -q 'ARM_ACTION_SUCCEEDED' <<<"$remote_output"; then arm_action_executed=true; fi
if grep -q 'HAND_ACTION_SUCCEEDED' <<<"$remote_output"; then hand_action_executed=true; fi
for object in object_red_cube object_blue_cylinder object_green_sphere; do
  if grep -q "SCENE_ENTITY_FOUND:${object}" <<<"$remote_output"; then objects_spawned=$((objects_spawned + 1)); fi
done

"$python_bin" - "$status" "$reason" "$platform_host" "$scene_world_verified" "$robot_spawned" "$panda_visual_stub_spawned" "$rgbd_sensor_spawned" "$objects_spawned" "$rgbd_image_verified" "$rgbd_depth_verified" "$rgbd_camera_info_verified" "$joint_state_verified" "$tf_verified" "$arm_controller_active" "$hand_controller_active" "$arm_action_executed" "$hand_action_executed" <<'PY'
import json, sys
from pathlib import Path

as_bool = lambda index: sys.argv[index] == "true"
data = {
    "status": sys.argv[1], "reason": sys.argv[2], "platform_smoke_host": sys.argv[3],
    "gazebo_started": sys.argv[1] in {"PARTIAL_PLATFORM_ONLY", "PARTIAL_CONTROL_AND_PERCEPTION_VERIFIED"},
    "scene_world_verified": as_bool(4), "robot_spawned": as_bool(5),
    "panda_visual_stub_spawned": as_bool(6), "rgbd_sensor_spawned": as_bool(7),
    "objects_spawned": int(sys.argv[8]),
    "rgbd_image_verified": as_bool(9), "rgbd_depth_verified": as_bool(10),
    "rgbd_camera_info_verified": as_bool(11), "joint_state_verified": as_bool(12),
    "tf_verified": as_bool(13), "arm_controller_active": as_bool(14),
    "hand_controller_active": as_bool(15), "action_executed": as_bool(16),
    "hand_action_executed": as_bool(17), "pick_place_completed": False,
    "episode_recorded": False,
}
data["topics_verified"] = [
    topic for topic, verified in {
        "/joint_states": data["joint_state_verified"], "/tf": data["tf_verified"],
        "/xh/camera/rgbd/image": data["rgbd_image_verified"],
        "/xh/camera/rgbd/depth_image": data["rgbd_depth_verified"],
        "/xh/camera/rgbd/camera_info": data["rgbd_camera_info_verified"],
    }.items() if verified
]
Path("reports/p0-simulation-status.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/p0-simulation-status.md").write_text("# P0 simulation status\n\n" + "\n".join([
    f"- Status: `{data['status']}` — {data['reason']}",
    f"- Gazebo / project world / controller-backed arm: **{data['gazebo_started']}** / **{data['scene_world_verified']}** / **{data['robot_spawned']}**",
    f"- Active arm / hand controllers: **{data['arm_controller_active']}** / **{data['hand_controller_active']}**; bounded arm / hand actions: **{data['action_executed']}** / **{data['hand_action_executed']}**",
    f"- RGB / depth / camera info: **{data['rgbd_image_verified']}** / **{data['rgbd_depth_verified']}** / **{data['rgbd_camera_info_verified']}**; joint state / TF: **{data['joint_state_verified']}** / **{data['tf_verified']}**",
    f"- Physical props: **{data['objects_spawned']}**; pick-place: **False**; episode recorded: **False**",
]) + "\n")
PY

printf '%s\n' "$remote_output"
echo "$status: $reason"
