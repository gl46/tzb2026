#!/usr/bin/env bash
# ADR-0009 five fail-closed Bullet-Featherstone capability gates.
#
# Every gate owns a fresh Gazebo process.  Do not merge the five probes: doing
# so lets a preceding arm trajectory influence the no-contact hand gate.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_BULLET_AUDIT_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
mkdir -p logs reports
RAW_LOG="logs/$RUN_ID-bullet-capability-audit.log"
LOCAL_SHA="$(shasum -a 256 robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"

ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" \
  "bash -s -- '$PROJECT_REMOTE_ROOT'" >"$RAW_LOG" 2>&1 <<'REMOTE' || true
set -eo pipefail
root="$1"
source /opt/ros/jazzy/setup.bash
source "/home/$USER/$root/robot_ws/install/setup.bash"
set -u
if gz service -l 2>/dev/null | grep -qx '/world/xh_p0_pick_place/scene/info'; then
  echo PREEXISTING_SIM
  exit 0
fi

root_abs="/home/$USER/$root"
tmp_root="$(mktemp -d)"
pid=""; pgid=""; gate_tmp=""
stop_sim() {
  if [ -n "$pgid" ]; then
    # `setsid ... &` normally gives the launch a private process group.  On
    # some non-interactive shells, however, `$!` still reports the caller's
    # group briefly; killing that group terminates this ordered audit after
    # Gate 1.  Only signal a verified private group, otherwise signal the
    # recorded launch process itself.
    caller_pgid="$(ps -o pgid= -p "$$" | tr -d ' ')"
    if [ "$pgid" != "$caller_pgid" ]; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
      sleep 1
      kill -KILL -- "-$pgid" 2>/dev/null || true
    else
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  [ -z "$pid" ] || wait "$pid" 2>/dev/null || true
  pid=""; pgid=""
}
cleanup() { stop_sim; rm -rf "$tmp_root"; }
trap cleanup EXIT HUP INT TERM

start_sim() {
  local mode="$1" world="${2:-}"
  gate_tmp="$tmp_root/$mode-$(date +%s%N)"
  mkdir -p "$gate_tmp/generated"
  export XH_SIM_GENERATED_SDF_DIR="$gate_tmp/generated"
  if [ "$mode" = production ]; then
    setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=false \
      >"$gate_tmp/launch.log" 2>&1 </dev/null &
  else
    setsid ros2 launch xh_sim moveit_execution.launch.py calibration_mode:=true world_file:="$world" \
      >"$gate_tmp/launch.log" 2>&1 </dev/null &
  fi
  pid=$!; pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
  for _ in $(seq 1 60); do
    if ! kill -0 "$pid" 2>/dev/null; then return 1; fi
    if ros2 control list_controllers 2>/dev/null | grep -q 'panda_arm_controller.*active'; then
      return 0
    fi
    sleep 1
  done
  return 1
}
gate_failed() {
  # A false or malformed marker stops the ordered audit immediately.  Later
  # gates are explicitly reported as not evaluated, rather than as failures.
  local marker="$1" json="$2"
  local payload_file="$gate_tmp/${marker}.json"
  printf '%s' "$json" >"$payload_file"
  python3 - "$marker" "$payload_file" <<'PY'
import json, sys
from pathlib import Path
marker, payload_file = sys.argv[1:]
payload = Path(payload_file).read_text()
try:
    data = json.loads(payload)
except json.JSONDecodeError:
    raise SystemExit(0)
if marker == "GATE1":
    raise SystemExit(0 if data.get("success") is not True else 1)
if marker == "GATE2":
    raise SystemExit(0 if data.get("controls_verified") is not True else 1)
if marker == "GATE3":
    trial = next((x for x in data.get("trials", []) if x.get("label") == "bilateral_1"), {})
    contacts = trial.get("contacts", {})
    # The bilateral calibration target has its own contact sensor/topic.  The
    # client normalizes whichever target channel is active into
    # ``target_cube_events``; checking the static-cube-only ``cube`` channel
    # here would reject valid bilateral contact evidence before GATE4/5.
    ok = contacts.get("left_target") and contacts.get("right_target") and contacts.get("target_cube_events", 0) > 0
    raise SystemExit(0 if not ok else 1)
if marker == "GATE4":
    required = ("initial_detach", "attach", "attached_follow", "detach", "detached_decoupled")
    raise SystemExit(0 if not all(data.get(key) is True for key in required) else 1)
if marker == "GATE5":
    raise SystemExit(0 if data.get("stable") is not True else 1)
raise SystemExit(0)
PY
}
emit_skipped() { echo "$1:{\"status\":\"NOT_EVALUATED_AFTER_PRECEDING_GATE_FAILURE\"}"; }

echo "SOURCE_SHA:$(sha256sum "$root_abs/robot_ws/src/xh_sim/urdf/panda_controlled.urdf" | awk '{print $1}')"
echo PLUGIN_INFO_BEGIN
plugin="/opt/ros/jazzy/opt/gz_physics_vendor/lib/gz-physics-7/engine-plugins/libgz-physics7-bullet-featherstone-plugin.so.7.6.0"
export LD_LIBRARY_PATH="/opt/ros/jazzy/opt/gz_physics_vendor/lib:${LD_LIBRARY_PATH:-}"
gz plugin --info -p "$plugin" 2>&1 || true
echo PLUGIN_INFO_END
echo VERSION_INFO_BEGIN
printf 'gz_sim='; gz sim --versions 2>&1 || true
printf 'gz_plugin='; gz plugin --versions 2>&1 || true
printf 'gz_physics_bullet_featherstone='; sed -n 's/^set(PACKAGE_VERSION "\([^"]*\)").*/\1/p' \
  /opt/ros/jazzy/opt/gz_physics_vendor/lib/cmake/gz-physics7-bullet-featherstone-plugin/gz-physics7-bullet-featherstone-plugin-config-version.cmake | head -1
printf 'gz_ros2_control_prefix='; ros2 pkg prefix gz_ros2_control 2>&1 || true
echo VERSION_INFO_END

# Gate 1 — fresh production session, controller activation and one arm segment.
if ! start_sim production; then
  echo 'GATE1:{"success":false,"reason":"PRODUCTION_LAUNCH_OR_CONTROLLER_ACTIVATION_FAILED"}'
  sed -n '1,260p' "$gate_tmp/launch.log" || true
  emit_skipped GATE2; emit_skipped GATE3; emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi
python3 - "$gate_tmp/generated/panda_controller.manifest.json" <<'PY'
import json,sys
print("MANIFEST:"+json.dumps(json.load(open(sys.argv[1])),separators=(",",":")))
PY
ros2 control list_controllers 2>&1 || true
g1="$(PYTHONPATH="$root_abs/src:${PYTHONPATH:-}" python3 "$root_abs/scripts/m1a_bullet_controller_probe.py" 2>&1 | tail -n 1 || true)"
echo "GATE1:$g1"
stop_sim
if gate_failed GATE1 "$g1"; then
  emit_skipped GATE2; emit_skipped GATE3; emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi

# Gate 2 — a fresh home-state, no-arm-motion, no-contact physical-mimic probe.
if ! start_sim production; then
  echo 'GATE2:{"controls_verified":false,"reason":"PRODUCTION_LAUNCH_FAILED"}'
  sed -n '1,260p' "$gate_tmp/launch.log" || true
  emit_skipped GATE3; emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi
startup_hold=""
for _ in $(seq 1 12); do
  if ros2 topic list 2>/dev/null | grep -qx '/xh/panda_hand_startup_hold/status'; then
    startup_hold="$(timeout 5 ros2 topic echo --once /xh/panda_hand_startup_hold/status 2>&1 || true)"
    grep -q 'STARTUP_HOLD_SUCCEEDED:q2=0.020m' <<<"$startup_hold" && break
  fi
  sleep 1
done
echo "STARTUP_HOLD:$startup_hold"
if ! grep -q 'STARTUP_HOLD_SUCCEEDED:q2=0.020m' <<<"$startup_hold"; then
  echo 'GATE2:{"controls_verified":false,"reason":"STARTUP_HOLD_NOT_VERIFIED"}'
  stop_sim
  emit_skipped GATE3; emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi
ros2 control list_hardware_interfaces 2>&1 || true
grep -E 'mimic constraint|is mimicking joint' "$gate_tmp/launch.log" || true
g2="$(PYTHONPATH="$root_abs/src:${PYTHONPATH:-}" python3 "$root_abs/scripts/m1a_hand_actuation_probe.py" 2>&1 | tail -n 1 || true)"
echo "GATE2:$g2"
stop_sim
if gate_failed GATE2 "$g2"; then
  emit_skipped GATE3; emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi

# Gate 3 — fresh calibration world; its labelled bilateral contact must publish
# on both finger topics and the cube topic.
calibration_world="$root_abs/robot_ws/install/xh_sim/share/xh_sim/worlds/m1a_contact_calibration.sdf"
if ! start_sim calibration "$calibration_world"; then
  echo 'GATE3:{"status":"CALIBRATION_LAUNCH_FAILED"}'
  sed -n '1,260p' "$gate_tmp/launch.log" || true
  emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi
g3="$(M1A_CALIBRATION_SCOPE=one M1A_CALIBRATION_LABEL=bilateral_1 PYTHONPATH="$root_abs/src:${PYTHONPATH:-}" python3 "$root_abs/scripts/m1a_contact_calibration_client.py" 2>&1 | tail -n 1 || true)"
echo "GATE3:$g3"
stop_sim
if gate_failed GATE3 "$g3"; then
  emit_skipped GATE4; emit_skipped GATE5
  exit 0
fi

# Gate 4 — fresh production world, existing DetachableJoint interfaces only.
#
# DetachableJoint may preserve its creation-time attachment.  Every production
# episode must therefore establish a detached reset state before an attach can
# be interpreted.  This capability probe intentionally does not use the old
# M0 approach vector: proximity is not an input to this plugin's state machine.
if ! start_sim production; then
  echo 'GATE4:{"initial_detach":false,"attach":false,"attached_follow":false,"detach":false,"detached_decoupled":false,"reason":"PRODUCTION_LAUNCH_FAILED"}'
  emit_skipped GATE5
  exit 0
fi
g4="$(python3 - <<'PY'
import json,math,re,select,subprocess,time
ARM_JOINTS="[panda_joint1, panda_joint2, panda_joint3, panda_joint4, panda_joint5, panda_joint6, panda_joint7]"

def arm(positions):
    goal=("{trajectory: {joint_names: "+ARM_JOINTS+", points: [{positions: ["
          +", ".join(str(value) for value in positions)+"], time_from_start: {sec: 2}}]}}")
    result=subprocess.run(["ros2","action","send_goal","/panda_arm_controller/follow_joint_trajectory",
                           "control_msgs/action/FollowJointTrajectory",goal],capture_output=True,text=True,timeout=12)
    return {"succeeded":"Goal finished with status: SUCCEEDED" in result.stdout,
            "stdout":result.stdout[-1000:], "stderr":result.stderr[-1000:]}

def invoke(topic, expected):
    watcher=subprocess.Popen(["gz","topic","-e","-t","/xh/p0/red_cube/grasp_state"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    time.sleep(.1)
    sent=subprocess.run(["gz","topic","-t",topic,"-m","gz.msgs.Empty","-p","unused: true"],capture_output=True,text=True,timeout=3)
    lines=[]; end=time.monotonic()+3
    while time.monotonic()<end and watcher.stdout:
        ready,_,_=select.select([watcher.stdout],[],[],.05)
        if ready:
            line=watcher.stdout.readline()
            if not line: break
            lines.append(line.rstrip())
            if expected in line: break
    watcher.terminate()
    try: watcher.wait(timeout=1)
    except subprocess.TimeoutExpired: watcher.kill(); watcher.wait(timeout=1)
    return {"command_success":sent.returncode == 0,
            "state_transition_observed":any(expected in line for line in lines),
            "events":lines, "command_stdout":sent.stdout[-1000:], "command_stderr":sent.stderr[-1000:]}

def pose(model, link=None):
    command=["timeout","1.5","gz","model","-m",model]
    command.extend(["-p"] if link is None else ["-l",link])
    result=subprocess.run(command,check=False,capture_output=True,text=True,timeout=3)
    match=re.search(r"^\s*- Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]\s*\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]",result.stdout,re.MULTILINE)
    if not match:
        return None
    values=[float(value) for value in match.groups()]
    return {"xyz":values[:3],"rpy":values[3:]}

def rotation(rpy):
    roll,pitch,yaw=rpy; cr,sr=math.cos(roll),math.sin(roll); cp,sp=math.cos(pitch),math.sin(pitch); cy,sy=math.cos(yaw),math.sin(yaw)
    return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
            [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]]

def relative_vector(link,cube):
    if link is None or cube is None:
        return None
    delta=[cube["xyz"][index]-link["xyz"][index] for index in range(3)]
    matrix=rotation(link["rpy"])
    return [sum(matrix[row][column]*delta[row] for row in range(3)) for column in range(3)]

def norm(vector): return math.sqrt(sum(value*value for value in vector))
def vector_delta(first, second): return None if first is None or second is None else norm([second[index]-first[index] for index in range(3)])

initial_detach=invoke("/xh/p0/red_cube/detach","detached")
attach=invoke("/xh/p0/red_cube/attach","attached") if initial_detach["state_transition_observed"] else {"command_success":False,"state_transition_observed":False,"reason":"INITIAL_DETACH_NOT_CONFIRMED"}
time.sleep(.3)
attached_before={"link7":pose("panda_controller","panda_link7"),"cube":pose("object_red_cube")}
attached_move=arm([0.12,0,0,0,0,0,0]) if attach["state_transition_observed"] else {"succeeded":False,"reason":"ATTACH_NOT_CONFIRMED"}
time.sleep(.3)
attached_after={"link7":pose("panda_controller","panda_link7"),"cube":pose("object_red_cube")}
attached_relative_before=relative_vector(attached_before["link7"],attached_before["cube"])
attached_relative_after=relative_vector(attached_after["link7"],attached_after["cube"])
attached_relative_drift=vector_delta(attached_relative_before,attached_relative_after)
attached_link_motion=vector_delta(attached_before["link7"]["xyz"] if attached_before["link7"] else None,attached_after["link7"]["xyz"] if attached_after["link7"] else None)
attached_follow=bool(attached_move.get("succeeded") and attached_link_motion is not None and attached_link_motion >= .01 and attached_relative_drift is not None and attached_relative_drift <= .001)
detach=invoke("/xh/p0/red_cube/detach","detached") if attached_follow else {"command_success":False,"state_transition_observed":False,"reason":"ATTACHED_FOLLOW_NOT_VERIFIED"}
time.sleep(.3)
detached_before={"link7":pose("panda_controller","panda_link7"),"cube":pose("object_red_cube")}
detached_move=arm([0,0,0,0,0,0,0]) if detach["state_transition_observed"] else {"succeeded":False,"reason":"DETACH_NOT_CONFIRMED"}
time.sleep(.5)
detached_after={"link7":pose("panda_controller","panda_link7"),"cube":pose("object_red_cube")}
detached_relative_before=relative_vector(detached_before["link7"],detached_before["cube"])
detached_relative_after=relative_vector(detached_after["link7"],detached_after["cube"])
detached_relative_change=vector_delta(detached_relative_before,detached_relative_after)
detached_link_motion=vector_delta(detached_before["link7"]["xyz"] if detached_before["link7"] else None,detached_after["link7"]["xyz"] if detached_after["link7"] else None)
detached_decoupled=bool(detached_move.get("succeeded") and detached_link_motion is not None and detached_link_motion >= .01 and detached_relative_change is not None and detached_relative_change >= .01)
print(json.dumps({"initial_detach":initial_detach["command_success"] and initial_detach["state_transition_observed"],
                  "attach":attach["command_success"] and attach["state_transition_observed"],
                  "attached_follow":attached_follow,"detach":detach["command_success"] and detach["state_transition_observed"],
                  "detached_decoupled":detached_decoupled,"initial_detach_evidence":initial_detach,
                  "attach_evidence":attach,"attached_motion":attached_move,"attached_before":attached_before,"attached_after":attached_after,
                  "attached_link_motion_m":attached_link_motion,"attached_relative_drift_m":attached_relative_drift,
                  "detach_evidence":detach,"detached_motion":detached_move,"detached_before":detached_before,"detached_after":detached_after,
                  "detached_link_motion_m":detached_link_motion,"detached_relative_change_m":detached_relative_change,
                  "thresholds_m":{"minimum_link_motion":.01,"maximum_attached_relative_drift":.001,"minimum_detached_relative_change":.01}},separators=(",",":")))
PY
)"
echo "GATE4:$g4"
stop_sim
if gate_failed GATE4 "$g4"; then
  emit_skipped GATE5
  exit 0
fi

# Gate 5 — fresh, action-free production world: five seconds of cube rest.
if ! start_sim production; then
  echo 'GATE5:{"stable":false,"reason":"PRODUCTION_LAUNCH_FAILED"}'
  exit 0
fi
g5="$(python3 - "$root_abs/scripts" <<'PY'
import json,sys,time
sys.path.insert(0,sys.argv[1])
from m1a_contact_calibration_client import runtime_cube_pose
samples=[]; deadline=time.monotonic()+5
while time.monotonic()<deadline:
    pose=runtime_cube_pose()
    if pose: samples.append(pose["xyz"])
    time.sleep(.1)
peak=max((sum((a-b)**2 for a,b in zip(x,samples[0]))**.5 for x in samples),default=float("inf"))
print(json.dumps({"stable":len(samples)>=3 and peak<.001,"samples":len(samples),"maximum_excursion_m":peak},separators=(",",":")))
PY
)"
echo "GATE5:$g5"
stop_sim
REMOTE

python3 scripts/summarize_m1a_bullet_capability_audit.py "$RUN_ID" "$RAW_LOG" "$LOCAL_SHA"
