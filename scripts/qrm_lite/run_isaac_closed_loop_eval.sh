#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_PROJECT_ROOT:?set ISAAC_PROJECT_ROOT}"
: "${ISAAC_SOURCE_ROOT:?set ISAAC_SOURCE_ROOT}"
: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
: "${QRM_CHECKPOINT:?set QRM_CHECKPOINT}"

SEED0="${QRM_CLOSED_LOOP_SEED0:-3238}"
SEED1="${QRM_CLOSED_LOOP_SEED1:-3239}"
OUTPUT="${ISAAC_DATA_ROOT}/closed-loop/qrm-beta-seeds-${SEED0}-${SEED1}"

python3 "${ISAAC_PROJECT_ROOT}/scripts/run_isaac_m1b_dual_benchmark.py" \
  --project-root "$ISAAC_PROJECT_ROOT" \
  --source-root "$ISAAC_SOURCE_ROOT" \
  --output "$OUTPUT" \
  --frames 6 \
  --worker-sdf "scene-${SEED0}.sdf" \
  --worker-sdf "scene-${SEED1}.sdf" \
  --worker-supervision "scene-${SEED0}.supervision.json" \
  --worker-supervision "scene-${SEED1}.supervision.json" \
  --qrm-checkpoint "$QRM_CHECKPOINT" \
  --qrm-model-id Q2_COARSE_MLP_FAILURE_CONTEXT \
  --container-prefix "m2a-qrm-loop-${SEED0}-${SEED1}"

python3 "${ISAAC_PROJECT_ROOT}/scripts/qrm_lite/summarize_isaac_closed_loop.py" \
  --run-root "$OUTPUT" \
  --report-json "${ISAAC_PROJECT_ROOT}/reports/m2a-s5-qrm-beta-closed-loop.json" \
  --report-md "${ISAAC_PROJECT_ROOT}/reports/m2a-s5-qrm-beta-closed-loop.md"

