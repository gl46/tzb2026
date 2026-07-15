#!/usr/bin/env bash
# Bounded Gazebo constrained-transfer run. The DetachableJoint is explicit and
# must never be reported as a frictional finger-contact grasp.
set -euo pipefail

mkdir -p reports
python_bin="python3"; [[ -x .venv/bin/python ]] && python_bin=".venv/bin/python"
host="${PICK_PLACE_HOST:-${SIM_HOST:-}}"
user="${PICK_PLACE_USER:-${SIM_USER:-}}"
project_root="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
[[ -n "$host" ]] || { echo "PICK_PLACE_HOST or SIM_HOST is required" >&2; exit 2; }
[[ -n "$user" ]] || case "$host" in node2) user=gl;; chxy) user=fx;; *) user="$USER";; esac
[[ "$project_root" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "invalid PROJECT_REMOTE_ROOT" >&2; exit 2; }

remote_output="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$user@$host" "bash -s -- '$project_root'" <<'REMOTE'
source /opt/ros/jazzy/setup.bash
source "$HOME/$1/robot_ws/install/setup.bash"
set -eo pipefail
tmp=$(mktemp -d); pid=""
cleanup() {
  if [ -n "$pid" ]; then
    kill -TERM -- "-$pid" 2>/dev/null || true; sleep 1
    kill -KILL -- "-$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT INT TERM
arm() {
  timeout -k 2 22 ros2 action send_goal /panda_arm_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
    "{trajectory: {joint_names: [panda_joint1, panda_joint2, panda_joint3, panda_joint4, panda_joint5, panda_joint6, panda_joint7], points: [{positions: $1, time_from_start: {sec: $2}}]}}" >"$3" 2>&1 || true
  grep -q 'Goal finished with status: SUCCEEDED' "$3"
}
hand() {
  timeout -k 2 16 ros2 action send_goal /panda_hand_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory \
    "{trajectory: {joint_names: [panda_finger_joint1, panda_finger_joint2], points: [{positions: $1, time_from_start: {sec: 2}}]}}" >"$2" 2>&1 || true
  grep -q 'Goal finished with status: SUCCEEDED' "$2"
}
pose() {
  local label="$1" raw
  raw="$(gz model -m object_red_cube -p 2>/dev/null || true)"
  python3 - "$label" "$raw" <<'PY'
import re, sys
values = re.findall(r"\[(-?\d+\.\d+) (-?\d+\.\d+) (-?\d+\.\d+)\]", sys.argv[2])
if values:
    print(f"{sys.argv[1]}:{','.join(values[0])}")
PY
}
joint_state() {
  local label="$1" raw
  raw="$(timeout 5 ros2 topic echo --once /joint_states 2>/dev/null || true)"
  python3 - "$label" "$raw" <<'PY'
import re, sys
match = re.search(r"position:\n((?:- [-0-9.e+]+\n)+)velocity:", sys.argv[2])
if match:
    values = re.findall(r"- ([-0-9.e+]+)", match.group(1))
    print(f"{sys.argv[1]}:{','.join(values)}")
PY
}
end_effector() {
  local label="$1" raw
  raw="$(timeout 5 ros2 run tf2_ros tf2_echo world panda_link7 2>/dev/null || true)"
  python3 - "$label" "$raw" <<'PY'
import re, sys
translation = re.search(r"Translation: \[([-0-9., ]+)\]", sys.argv[2])
rotation = re.search(r"Quaternion \(xyzw\) \[([-0-9., ]+)\]", sys.argv[2])
if translation and rotation:
    values = [*translation.group(1).replace(" ", "").split(","), *rotation.group(1).replace(" ", "").split(",")]
    print(f"{sys.argv[1]}:{','.join(values)}")
PY
}
setsid ros2 launch xh_bringup bringup.launch.py headless:=true >"$tmp/launch.log" 2>&1 & pid=$!
sleep 14
pose INITIAL_CUBE
joint_state INITIAL_JOINTS
end_effector INITIAL_EE
gz topic -t /xh/p0/red_cube/detach -m gz.msgs.Empty -p 'unused: true' || true
arm '[-0.307, 1.06, 0.76, -2.148, -1.435, 2.274, 1.422]' 5 "$tmp/approach.log" && echo ARM_APPROACH_SUCCEEDED
hand '[0.0, 0.0]' "$tmp/close.log" && echo HAND_CLOSE_SUCCEEDED
(timeout 4 gz topic -e -t /xh/p0/red_cube/grasp_state >"$tmp/attach.log" 2>&1) & monitor=$!
sleep 1
gz topic -t /xh/p0/red_cube/attach -m gz.msgs.Empty -p 'unused: true'
wait "$monitor" || true
grep -q attached "$tmp/attach.log" && echo CONSTRAINT_ATTACHED
# Lift above the bin, then use a measured release waypoint inside it.
arm '[0, 0, 0, 0, 0, 0, 0]' 7 "$tmp/lift.log" && echo ARM_LIFT_SUCCEEDED
arm '[-1.9262, -1.6941, 2.8863, -1.9115, -0.9962, 3.0409, 2.2138]' 10 "$tmp/place.log" && echo ARM_PLACE_SUCCEEDED
pose CARRIED_CUBE
# The sensor is named by Gazebo from the model/link/sensor hierarchy. Listen
# across release and settling, but retain only a bounded sample in the log.
(timeout 12 gz topic -e -t /world/xh_p0_pick_place/model/object_red_cube/link/link/sensor/red_cube_contact/contact | head -n 120 >"$tmp/contact.log" 2>&1) & contact_monitor=$!
(timeout 4 gz topic -e -t /xh/p0/red_cube/grasp_state >"$tmp/detach.log" 2>&1) & monitor=$!
sleep 1
gz topic -t /xh/p0/red_cube/detach -m gz.msgs.Empty -p 'unused: true'
wait "$monitor" || true
grep -q detached "$tmp/detach.log" && echo CONSTRAINT_DETACHED
hand '[0.03, 0.03]' "$tmp/open.log" && echo HAND_OPEN_SUCCEEDED
sleep 6
wait "$contact_monitor" || true
[[ -s "$tmp/contact.log" ]] && echo OBJECT_CONTACT_SUPERVISION_RECEIVED
pose FINAL_CUBE
joint_state FINAL_JOINTS
end_effector FINAL_EE
REMOTE
)" || true

REMOTE_OUTPUT="$remote_output" "$python_bin" - "$host" <<'PY'
import json, os, re, sys
from pathlib import Path
host, output = sys.argv[1], os.environ["REMOTE_OUTPUT"]
def pose(label):
    match = re.search(rf"^{label}:([-0-9.]+),([-0-9.]+),([-0-9.]+)$", output, re.M)
    return [float(value) for value in match.groups()] if match else None
required = {"approach": "ARM_APPROACH_SUCCEEDED", "lift": "ARM_LIFT_SUCCEEDED", "place": "ARM_PLACE_SUCCEEDED", "hand_close": "HAND_CLOSE_SUCCEEDED", "hand_open": "HAND_OPEN_SUCCEEDED", "attached": "CONSTRAINT_ATTACHED", "detached": "CONSTRAINT_DETACHED"}
checks = {name: marker in output for name, marker in required.items()}
initial, carried, final = pose("INITIAL_CUBE"), pose("CARRIED_CUBE"), pose("FINAL_CUBE")
def numeric_line(label):
    match = re.search(rf"^{label}:([-0-9.e+,]+)$", output, re.M)
    return [float(value) for value in match.group(1).split(",")] if match else None
initial_joints, final_joints = numeric_line("INITIAL_JOINTS"), numeric_line("FINAL_JOINTS")
initial_ee, final_ee = numeric_line("INITIAL_EE"), numeric_line("FINAL_EE")
inside = bool(final and abs(final[0] - .51) <= .17 and abs(final[1] + .06) <= .17 and .47 <= final[2] <= .56)
success = all(checks.values()) and initial is not None and carried is not None and inside
data = {"status": "VERIFIED_CONSTRAINED_PICK_PLACE" if success else "FAILED_CONSTRAINED_PICK_PLACE", "host": host, "grasp_mode": "GAZEBO_DETACHABLE_JOINT_CONSTRAINT", "finger_contact_grasp_verified": False, "robot_collision_model": "VISUAL_INERTIAL_ONLY_OBJECT_AND_BIN_COLLISIONS_RETAINED", "initial_cube_pose_xyz": initial, "carried_cube_pose_xyz": carried, "final_cube_pose_xyz": final, "initial_joint_positions": initial_joints, "final_joint_positions": final_joints, "initial_end_effector_pose": initial_ee, "final_end_effector_pose": final_ee, "bin_center_xyz": [.51, -.06, .45], "checks": checks, "object_contact_supervision_observed": "OBJECT_CONTACT_SUPERVISION_RECEIVED" in output, "object_inside_bin_after_settle": inside, "pick_place_completed": success, "episode_recorded": False, "raw_output": output}
Path("reports/p0-constrained-pick-place-status.json").write_text(json.dumps(data, indent=2) + "\n")
Path("reports/p0-constrained-pick-place-status.md").write_text("# P0 constrained pick-place status\n\n" + f"- Status: `{data['status']}` on `{host}`.\n- Initial / carried / final cube xyz: `{initial}` / `{carried}` / `{final}`.\n- Object inside bin after settle: **{inside}**.\n- Grasp is an explicit Gazebo DetachableJoint constraint, not a verified finger-contact grasp.\n- Robot-link collisions are disabled for this primitive controller model; object/bin collisions remain physical.\n")
print(json.dumps({"status": data["status"], "inside_bin": inside, "checks": checks}))
PY
printf '%s\n' "$remote_output"
