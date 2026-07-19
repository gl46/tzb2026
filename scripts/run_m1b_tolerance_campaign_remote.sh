#!/usr/bin/env bash
# Execute the bounded ADR-0013 calibration campaign on one simulator host.
set -eo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 WORKLIST_JSON RUN_DIRECTORY" >&2
  exit 2
fi

worklist="$1"
run_dir="$2"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scene_dir="${M1B_TOLERANCE_SCENE_DIR:-$root/data/generated/m1b_beta_tolerance_baseclear/scenes}"
fixture_diameter_m="${M1B_TOLERANCE_FIXTURE_DIAMETER_M:-0.03}"
calibration_hand_y_bias_m="${M1B_TOLERANCE_CALIBRATION_HAND_Y_BIAS_M:-}"
keep_target_collision_through_descend="${M1B_TOLERANCE_KEEP_TARGET_COLLISION_THROUGH_DESCEND:-0}"
calibration_lateral_insertion="${M1B_TOLERANCE_CALIBRATION_LATERAL_INSERTION:-0}"
calibration_lateral_insertion_height_m="${M1B_TOLERANCE_CALIBRATION_LATERAL_INSERTION_HEIGHT_M:-}"
calibration_lateral_insert_target_touch_exception="${M1B_TOLERANCE_CALIBRATION_LATERAL_INSERT_TARGET_TOUCH_EXCEPTION:-0}"
calibration_vertical_board_ik_probe="${M1B_TOLERANCE_CALIBRATION_VERTICAL_BOARD_IK_PROBE:-0}"
calibration_target_height_scan="${M1B_TOLERANCE_CALIBRATION_TARGET_HEIGHT_SCAN:-0}"
calibration_hand_y_bias_args=()
if [[ -n "$calibration_hand_y_bias_m" ]]; then
  calibration_hand_y_bias_args=(--calibration-hand-y-bias-m "$calibration_hand_y_bias_m")
fi
keep_target_collision_args=()
if [[ "$keep_target_collision_through_descend" == 1 ]]; then
  keep_target_collision_args=(--calibration-keep-target-collision-through-descend)
fi
lateral_insertion_args=()
if [[ "$calibration_lateral_insertion" == 1 ]]; then
  lateral_insertion_args=(--calibration-lateral-insertion)
fi
lateral_insertion_height_args=()
if [[ -n "$calibration_lateral_insertion_height_m" ]]; then
  lateral_insertion_height_args=(--calibration-lateral-insertion-hand-z-offset-m "$calibration_lateral_insertion_height_m")
fi
lateral_insert_target_touch_args=()
if [[ "$calibration_lateral_insert_target_touch_exception" == 1 ]]; then
  lateral_insert_target_touch_args=(--calibration-lateral-insert-target-touch-exception)
fi
vertical_board_ik_probe_args=()
if [[ "$calibration_vertical_board_ik_probe" == 1 ]]; then
  vertical_board_ik_probe_args=(--calibration-vertical-board-ik-probe)
fi
target_height_scan_args=()
if [[ "$calibration_target_height_scan" == 1 ]]; then
  target_height_scan_args=(--calibration-target-height-scan)
fi
calibration_top_contact_height_m="${M1B_TOLERANCE_TOP_CONTACT_HEIGHT_M:-}"
top_contact_height_args=()
if [[ -n "$calibration_top_contact_height_m" ]]; then
  if ! [[ "$calibration_top_contact_height_m" =~ ^0\.(10|11|12|13|14)$ ]]; then
    echo "INVALID_TOP_CONTACT_HEIGHT_M:$calibration_top_contact_height_m" >&2
    exit 2
  fi
  top_contact_height_args=(--calibration-top-contact-height-m "$calibration_top_contact_height_m")
fi
trial_timeout_s="${M1B_TOLERANCE_TRIAL_TIMEOUT_S:-150}"
reset_max_attempts="${M1B_TOLERANCE_RESET_MAX_ATTEMPTS:-3}"
allow_resume="${M1B_TOLERANCE_ALLOW_RESUME:-0}"
spawn_manifest="$root/data/generated/m1b_beta_contact_probe/panda/panda.manifest.json"
start_index="${M1B_TOLERANCE_START_INDEX:-0}"
end_index="${M1B_TOLERANCE_END_INDEX:-80}"

[[ -f "$worklist" ]] || { echo "WORKLIST_MISSING:$worklist" >&2; exit 2; }
[[ -d "$scene_dir" ]] || { echo "SCENE_DIRECTORY_MISSING:$scene_dir" >&2; exit 2; }
[[ -f "$spawn_manifest" ]] || { echo "SPAWN_MANIFEST_MISSING:$spawn_manifest" >&2; exit 2; }
[[ "$start_index" =~ ^[0-9]+$ && "$end_index" =~ ^[0-9]+$ && "$start_index" -le "$end_index" && "$end_index" -le 80 ]] || {
  echo "INVALID_TRIAL_INDEX_RANGE:$start_index:$end_index" >&2
  exit 2
}
[[ "$reset_max_attempts" =~ ^[1-9][0-9]*$ ]] || { echo "INVALID_RESET_MAX_ATTEMPTS:$reset_max_attempts" >&2; exit 2; }
if [[ -e "$run_dir" ]] && [[ -n "$(find "$run_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  # A rejected reset is never an episode.  An operator may resume only from a
  # contiguous, worklist-bound raw prefix, so every retained raw file still
  # represents exactly one verified-reset production primitive.
  if [[ "$allow_resume" != 1 || "$start_index" -eq 0 ]]; then
    echo "RUN_DIRECTORY_NOT_EMPTY:$run_dir" >&2
    exit 2
  fi
  python3 - "$worklist" "$run_dir/raw" "$start_index" <<'PY'
import json, sys
from pathlib import Path

worklist = json.load(open(sys.argv[1], encoding="utf-8"))["trials"]
raw_dir, start = Path(sys.argv[2]), int(sys.argv[3])
for index in range(start):
    path = raw_dir / f"trial-{index:03d}.json"
    if not path.is_file():
        raise SystemExit(f"RESUME_MISSING_RAW_PREFIX:{path}")
    record = json.load(path.open(encoding="utf-8"))
    if record.get("provenance") != "CALIBRATION_ONLY_INITIALIZATION" or record.get("trial") != worklist[index]:
        raise SystemExit(f"RESUME_RAW_PREFIX_MISMATCH:{path}")
for path in raw_dir.glob("trial-*.json"):
    index = int(path.stem.removeprefix("trial-"))
    if index >= start:
        raise SystemExit(f"RESUME_RAW_ALREADY_EXISTS:{path}")
PY
fi
mkdir -p "$run_dir/raw" "$run_dir/logs" "$run_dir/trials"

source /opt/ros/jazzy/setup.bash
source "$root/robot_ws/install/setup.bash"
set -u
export PYTHONPATH="$root/src:$root/scripts:${PYTHONPATH:-}"
cd "$root"

cleanup_partition() {
  local partition="$1"
  local pid envfile
  for pid in $(pgrep -u "$(id -u)" || true); do
    envfile="/proc/$pid/environ"
    [[ -r "$envfile" ]] || continue
    if tr '\0' '\n' <"$envfile" 2>/dev/null | grep -qx "GZ_PARTITION=$partition"; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  sleep 2
  for pid in $(pgrep -u "$(id -u)" || true); do
    envfile="/proc/$pid/environ"
    [[ -r "$envfile" ]] || continue
    if tr '\0' '\n' <"$envfile" 2>/dev/null | grep -qx "GZ_PARTITION=$partition"; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

wait_for_m1b_controller_load() {
  local deadline=$((SECONDS + 90)) state
  while (( SECONDS < deadline )); do
    state="$(ros2 control list_controllers 2>/dev/null || true)"
    # The paused launch deliberately leaves these controllers inactive.  The
    # detach utility resumes the world and activates them only after all-N
    # detach has been issued, so requiring `active` here would deadlock the
    # reset lifecycle.  Confirm that all expected controllers are loaded;
    # m1b_reset_detach.py then fail-closes if its post-resume activation fails.
    if grep -Eq '^joint_state_broadcaster[[:space:]]+joint_state_broadcaster/JointStateBroadcaster[[:space:]]+(active|inactive)$' <<<"$state" \
      && grep -Eq '^panda_arm_controller[[:space:]]+joint_trajectory_controller/JointTrajectoryController[[:space:]]+(active|inactive)$' <<<"$state" \
      && grep -Eq '^panda_hand_physical_controller[[:space:]]+joint_trajectory_controller/JointTrajectoryController[[:space:]]+(active|inactive)$' <<<"$state"; then
      return 0
    fi
    sleep 1
  done
  printf 'M1B_CONTROLLERS_NOT_LOADED\n%s\n' "$state" >&2
  return 1
}

for index in $(seq "$start_index" "$end_index"); do
  trial_path="$run_dir/trials/trial-$(printf '%03d' "$index").json"
  python3 - "$worklist" "$index" "$trial_path" <<'PY'
import json, sys
worklist, index, output = sys.argv[1:]
trial = json.load(open(worklist))["trials"][int(index)]
with open(output, "w", encoding="utf-8") as handle:
    json.dump(trial, handle, indent=2)
    handle.write("\n")
PY
  read -r seed object_slot < <(python3 - "$trial_path" <<'PY'
import json, sys
trial = json.load(open(sys.argv[1]))
print(trial["scene_seed"], trial["object_slot"])
PY
)
  scene="$scene_dir/scene-$seed.sdf"
  supervision="$scene_dir/scene-$seed.supervision.json"
  [[ -f "$scene" && -f "$supervision" ]] || { echo "TRIAL_SCENE_MISSING:index=$index" >&2; exit 3; }
  reset_verified=0
  for reset_attempt in $(seq 1 "$reset_max_attempts"); do
    # A failed physical check destroys this world.  The next attempt is a new
    # episode, not a waiver or a re-use of the rejected reset.
    partition="m1b_tolerance_campaign_${index}_reset_${reset_attempt}"
    domain=$((130 + index))
    generated="$run_dir/generated-$index-reset-$reset_attempt"
    mkdir -p "$generated"
    env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" XH_SIM_GENERATED_SDF_DIR="$generated" \
      nohup bash -lc "source /opt/ros/jazzy/setup.bash; source '$root/robot_ws/install/setup.bash'; exec ros2 launch xh_sim simulation.launch.py world_name:=industrial_cylinder_v1 world_file:='$scene' m1b_scene_supervision:='$supervision' start_paused:=true" \
      >"$run_dir/logs/trial-$(printf '%03d' "$index")-reset-$reset_attempt-simulation.log" 2>&1 < /dev/null &
    sleep 25
    env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
      nohup bash -lc "source /opt/ros/jazzy/setup.bash; source '$root/robot_ws/install/setup.bash'; exec ros2 launch xh_sim m1b_moveit_server.launch.py" \
      >"$run_dir/logs/trial-$(printf '%03d' "$index")-reset-$reset_attempt-moveit.log" 2>&1 < /dev/null &
    sleep 5
    if ! (export GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain"; wait_for_m1b_controller_load); then
      cleanup_partition "$partition"
      echo "INVALID_RESET_RETRY:CONTROLLERS_NOT_LOADED:index=$index:attempt=$reset_attempt" >&2
      continue
    fi
    reset_record="$run_dir/trials/trial-$(printf '%03d' "$index")-reset-attempt-$reset_attempt.json"
    if ! timeout "$trial_timeout_s" env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
      python3 scripts/m1b_reset_detach.py --spawn-manifest "$spawn_manifest" --world-name industrial_cylinder_v1 --resume-world --activate-controllers \
      --output "$reset_record"; then
      cleanup_partition "$partition"
      echo "INVALID_RESET_RETRY:DETACH:index=$index:attempt=$reset_attempt" >&2
      continue
    fi
    # Amendment 1 deliberately makes one-shot grasp_state messages auxiliary.
    # A reset becomes valid only after the S1 MoveIt jog has physically shown
    # that all generated cylinders stay uncoupled.  This is evaluator-side
    # reset infrastructure, never an input to the tolerance primitive.
    reset_physical="$run_dir/trials/trial-$(printf '%03d' "$index")-reset-physical-attempt-$reset_attempt.json"
    if ! timeout "$trial_timeout_s" env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
      python3 scripts/verify_m1b_reset_noncoupling.py --spawn-manifest "$spawn_manifest" --scene-supervision "$supervision" \
      --world-name industrial_cylinder_v1 --output "$reset_physical"; then
      cleanup_partition "$partition"
      echo "INVALID_RESET_RETRY:PHYSICAL_NONCOUPLING:index=$index:attempt=$reset_attempt" >&2
      continue
    fi
    if ! python3 - "$reset_physical" <<'PY'
import json, sys
record = json.load(open(sys.argv[1]))
if record.get("status") != "RESET_PHYSICAL_NONCOUPLING_VERIFIED":
    raise SystemExit("reset physical non-coupling gate did not verify")
PY
    then
      cleanup_partition "$partition"
      echo "INVALID_RESET_RETRY:PHYSICAL_NONCOUPLING_STATUS:index=$index:attempt=$reset_attempt" >&2
      continue
    fi
    # The verifier pauses the world for its after-jog supervision snapshot;
    # the production-equivalent tolerance primitive must start with simulation
    # running, just as it does after the detach transaction.
    if ! env GZ_PARTITION="$partition" timeout 10 gz service --service /world/industrial_cylinder_v1/control \
      --reqtype gz.msgs.WorldControl --reptype gz.msgs.Boolean --req 'pause: false' | grep -q 'data: true'; then
      cleanup_partition "$partition"
      echo "INVALID_RESET_RETRY:POST_VERIFY_RESUME:index=$index:attempt=$reset_attempt" >&2
      continue
    fi
    reset_verified=1
    break
  done
  if [[ "$reset_verified" -ne 1 ]]; then
    echo "INFRASTRUCTURE_FAILURE:RESET_RETRY_EXHAUSTED:index=$index:attempts=$reset_max_attempts" >&2
    exit 3
  fi
  if ! timeout "$trial_timeout_s" env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
    python3 scripts/run_m1b_tolerance_trial.py --trial "$trial_path" --supervision "$supervision" --object-slot "$object_slot" \
    --calibration-fixture-diameter-m "$fixture_diameter_m" "${calibration_hand_y_bias_args[@]}" "${keep_target_collision_args[@]}" "${lateral_insertion_args[@]}" "${lateral_insertion_height_args[@]}" "${lateral_insert_target_touch_args[@]}" "${vertical_board_ik_probe_args[@]}" "${target_height_scan_args[@]}" "${top_contact_height_args[@]}" --output "$run_dir/raw/trial-$(printf '%03d' "$index").json"; then
    cleanup_partition "$partition"
    echo "INFRASTRUCTURE_FAILURE:TRIAL:index=$index" >&2
    exit 3
  fi
  python3 - "$run_dir/raw/trial-$(printf '%03d' "$index").json" <<'PY'
import json, sys
record = json.load(open(sys.argv[1]))
if not record.get("ready"):
    raise SystemExit("trial did not reach ready state")
PY
  cleanup_partition "$partition"
  echo "COMPLETED_TRIAL:$index"
done

if [[ "$end_index" -eq 80 ]] && [[ "$(find "$run_dir/raw" -maxdepth 1 -name 'trial-*.json' -type f | wc -l)" -eq 81 ]]; then
  python3 scripts/summarize_m1b_tolerance_campaign.py --worklist "$worklist" --raw-dir "$run_dir/raw" --output "$run_dir/m1b-tolerance-envelope.json"
else
  echo "PARTIAL_CAMPAIGN_COMPLETE:$start_index:$end_index"
fi
