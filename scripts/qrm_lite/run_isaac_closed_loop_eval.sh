#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_PROJECT_ROOT:?set ISAAC_PROJECT_ROOT}"
: "${ISAAC_SOURCE_ROOT:?set ISAAC_SOURCE_ROOT}"
: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
: "${QRM_CHECKPOINT:?set QRM_CHECKPOINT}"

SEED_START="${QRM_CLOSED_LOOP_SEED_START:-3200}"
SCENE_COUNT="${QRM_CLOSED_LOOP_SCENE_COUNT:-10}"
if (( SCENE_COUNT < 2 || SCENE_COUNT % 2 != 0 )); then
  echo "QRM_CLOSED_LOOP_SCENE_COUNT must be an even integer >=2" >&2
  exit 2
fi
SEED_END=$((SEED_START + SCENE_COUNT - 1))
OUTPUT="${ISAAC_DATA_ROOT}/closed-loop/qrm-beta-seeds-${SEED_START}-${SEED_END}"
mkdir -p "$OUTPUT"
SUMMARY_ARGS=()

for ((offset = 0; offset < SCENE_COUNT; offset += 2)); do
  seed0=$((SEED_START + offset))
  seed1=$((seed0 + 1))
  run_root="${OUTPUT}/seeds-${seed0}-${seed1}"
  python3 "${ISAAC_PROJECT_ROOT}/scripts/run_isaac_m1b_dual_benchmark.py" \
    --project-root "$ISAAC_PROJECT_ROOT" \
    --source-root "$ISAAC_SOURCE_ROOT" \
    --output "$run_root" \
    --frames 6 \
    --worker-sdf "scene-${seed0}.sdf" \
    --worker-sdf "scene-${seed1}.sdf" \
    --worker-supervision "scene-${seed0}.supervision.json" \
    --worker-supervision "scene-${seed1}.supervision.json" \
    --qrm-checkpoint "$QRM_CHECKPOINT" \
    --qrm-model-id Q2_COARSE_MLP_FAILURE_CONTEXT \
    --container-prefix "m2a-qrm-loop-${seed0}-${seed1}"
  SUMMARY_ARGS+=(--run-root "$run_root")
done

python3 "${ISAAC_PROJECT_ROOT}/scripts/qrm_lite/summarize_isaac_closed_loop.py" \
  "${SUMMARY_ARGS[@]}" \
  --report-json "${ISAAC_PROJECT_ROOT}/reports/m2a-s5-qrm-beta-closed-loop.json" \
  --report-md "${ISAAC_PROJECT_ROOT}/reports/m2a-s5-qrm-beta-closed-loop.md"
