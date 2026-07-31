#!/usr/bin/env bash
set -euo pipefail

remote_host="${M2B_REMOTE_HOST:-root@labserver}"
project_root="${ISAAC_PROJECT_ROOT:-/var/tmp/m2a-isaac-project-20260731}"
source_root="${ISAAC_SOURCE_ROOT:-/var/tmp/m2b-heldout-source-copy-20260731}"
output_root="${M2B_OUTPUT_ROOT:-/var/tmp/xh-data/isaac-industrial/m2b/failure-evidence-scale-v1}"
scene_start="${M2B_SCENE_START:-4000}"
scene_end="${M2B_SCENE_END:-4149}"
exclude_csv="${M2B_EXCLUDE_SEEDS:-4025,4063,4091,4110}"

if (( scene_start > scene_end )); then
  echo "M2B_SCENE_START must not exceed M2B_SCENE_END" >&2
  exit 2
fi

if ssh -o BatchMode=yes "${remote_host}" \
  pgrep -f 'scripts/m2b/run_failure_evidence_worker.py' >/dev/null; then
  echo "an M2B failure-evidence worker is already active on ${remote_host}" >&2
  exit 3
fi

is_excluded() {
  local candidate="$1"
  local item
  IFS=',' read -r -a excluded <<<"${exclude_csv}"
  for item in "${excluded[@]}"; do
    if [[ "${candidate}" == "${item}" ]]; then
      return 0
    fi
  done
  return 1
}

for gpu in 0 1; do
  seed_arguments=()
  for ((seed = scene_start; seed <= scene_end; seed++)); do
    if (( seed % 2 != gpu )) || is_excluded "${seed}"; then
      continue
    fi
    seed_arguments+=(--scene-seed "${seed}")
  done
  if (( ${#seed_arguments[@]} == 0 )); then
    echo "worker ${gpu} has no scene seeds" >&2
    exit 2
  fi
  worker_output="${output_root}/worker${gpu}"
  remote_command=(
    python3 "${project_root}/scripts/m2b/run_failure_evidence_worker.py"
    --project-root "${project_root}"
    --source-root "${source_root}"
    --output-root "${worker_output}"
    "${seed_arguments[@]}"
    --gpu "${gpu}"
    --worker-id "${gpu}"
    --max-stage-attempts 2
    --max-failure-attempts 2
    --settle-s 10
    --container-prefix m2b-scale-v1
  )
  quoted_command=""
  printf -v quoted_command '%q ' "${remote_command[@]}"
  remote_log="${output_root}/worker${gpu}.log"
  ssh -o BatchMode=yes "${remote_host}" \
    "mkdir -p '${output_root}' '${worker_output}'; chmod 0777 '${worker_output}'; nohup ${quoted_command} >'${remote_log}' 2>&1 < /dev/null & echo \$!"
done
