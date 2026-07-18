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
fixture_diameter_m="${M1B_TOLERANCE_FIXTURE_DIAMETER_M:-0.05}"
calibration_hand_y_bias_m="${M1B_TOLERANCE_CALIBRATION_HAND_Y_BIAS_M:-}"
calibration_hand_y_bias_args=()
if [[ -n "$calibration_hand_y_bias_m" ]]; then
  calibration_hand_y_bias_args=(--calibration-hand-y-bias-m "$calibration_hand_y_bias_m")
fi
trial_timeout_s="${M1B_TOLERANCE_TRIAL_TIMEOUT_S:-150}"
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
if [[ -e "$run_dir" ]] && [[ -n "$(find "$run_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "RUN_DIRECTORY_NOT_EMPTY:$run_dir" >&2
  exit 2
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
  partition="m1b_tolerance_campaign_$index"
  domain=$((130 + index))
  generated="$run_dir/generated-$index"
  mkdir -p "$generated"
  env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" XH_SIM_GENERATED_SDF_DIR="$generated" \
    nohup bash -lc "source /opt/ros/jazzy/setup.bash; source '$root/robot_ws/install/setup.bash'; exec ros2 launch xh_sim simulation.launch.py world_name:=industrial_cylinder_v1 world_file:='$scene' m1b_scene_supervision:='$supervision' start_paused:=true" \
    >"$run_dir/logs/trial-$(printf '%03d' "$index")-simulation.log" 2>&1 < /dev/null &
  sleep 25
  env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
    nohup bash -lc "source /opt/ros/jazzy/setup.bash; source '$root/robot_ws/install/setup.bash'; exec ros2 launch xh_sim m1b_moveit_server.launch.py" \
    >"$run_dir/logs/trial-$(printf '%03d' "$index")-moveit.log" 2>&1 < /dev/null &
  sleep 18
  if ! timeout "$trial_timeout_s" env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
    python3 scripts/m1b_reset_detach.py --spawn-manifest "$spawn_manifest" --world-name industrial_cylinder_v1 --resume-world --activate-controllers \
    --output "$run_dir/trials/trial-$(printf '%03d' "$index")-reset.json"; then
    cleanup_partition "$partition"
    echo "INFRASTRUCTURE_FAILURE:RESET:index=$index" >&2
    exit 3
  fi
  if ! timeout "$trial_timeout_s" env GZ_PARTITION="$partition" ROS_DOMAIN_ID="$domain" \
    python3 scripts/run_m1b_tolerance_trial.py --trial "$trial_path" --supervision "$supervision" --object-slot "$object_slot" \
    --calibration-fixture-diameter-m "$fixture_diameter_m" "${calibration_hand_y_bias_args[@]}" --output "$run_dir/raw/trial-$(printf '%03d' "$index").json"; then
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

if [[ "$start_index" -eq 0 && "$end_index" -eq 80 ]]; then
  python3 scripts/summarize_m1b_tolerance_campaign.py --worklist "$worklist" --raw-dir "$run_dir/raw" --output "$run_dir/m1b-tolerance-envelope.json"
else
  echo "PARTIAL_CAMPAIGN_COMPLETE:$start_index:$end_index"
fi
