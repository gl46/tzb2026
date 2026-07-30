#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_PROJECT_ROOT:?set ISAAC_PROJECT_ROOT}"
: "${ISAAC_SOURCE_ROOT:?set ISAAC_SOURCE_ROOT}"
: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
FRAMES="${ISAAC_BENCHMARK_FRAMES:-100}"
SEED0="${ISAAC_BENCHMARK_SEED0:-3100}"
SEED1="${ISAAC_BENCHMARK_SEED1:-3101}"
SETTLE_S="${ISAAC_BENCHMARK_SETTLE_S:-30}"
OUT="${ISAAC_DATA_ROOT}/benchmarks/m2a-$(date +%Y%m%d-%H%M%S)"

sleep "$SETTLE_S"
python3 "${ISAAC_PROJECT_ROOT}/scripts/isaac/launch_worker.py" \
  --project-root "$ISAAC_PROJECT_ROOT" \
  --source-root "$ISAAC_SOURCE_ROOT" \
  --output "$OUT/single-gpu0" \
  --sdf "scene-${SEED0}.sdf" \
  --supervision "scene-${SEED0}.supervision.json" \
  --worker-id 0 \
  --gpu 0 \
  --frames "$FRAMES"

sleep "$SETTLE_S"
python3 "${ISAAC_PROJECT_ROOT}/scripts/isaac/launch_worker.py" \
  --project-root "$ISAAC_PROJECT_ROOT" \
  --source-root "$ISAAC_SOURCE_ROOT" \
  --output "$OUT/single-gpu1" \
  --sdf "scene-${SEED1}.sdf" \
  --supervision "scene-${SEED1}.supervision.json" \
  --worker-id 1 \
  --gpu 1 \
  --frames "$FRAMES"

sleep "$SETTLE_S"
python3 "${ISAAC_PROJECT_ROOT}/scripts/run_isaac_m1b_dual_benchmark.py" \
  --project-root "$ISAAC_PROJECT_ROOT" \
  --source-root "$ISAAC_SOURCE_ROOT" \
  --output "$OUT/dual" \
  --frames "$FRAMES" \
  --worker-sdf "scene-${SEED0}.sdf" \
  --worker-sdf "scene-${SEED1}.sdf" \
  --worker-supervision "scene-${SEED0}.supervision.json" \
  --worker-supervision "scene-${SEED1}.supervision.json" \
  --container-prefix "m2a-worker-benchmark-${SEED0}-${SEED1}"

python3 "${ISAAC_PROJECT_ROOT}/scripts/isaac/summarize_worker_benchmark.py" \
  --single-gpu0 "$OUT/single-gpu0/metrics.json" \
  --single-gpu1 "$OUT/single-gpu1/metrics.json" \
  --dual-summary "$OUT/dual/dual-benchmark-summary.json" \
  --report-json "$OUT/m2a-s2-worker-benchmark.json" \
  --report-md "$OUT/m2a-s2-worker-benchmark.md"

echo "$OUT"
