#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_PROJECT_ROOT:?set ISAAC_PROJECT_ROOT}"
: "${ISAAC_SOURCE_ROOT:?set ISAAC_SOURCE_ROOT}"
: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
FRAMES="${ISAAC_BENCHMARK_FRAMES:-100}"
SEED0="${ISAAC_BENCHMARK_SEED0:-3100}"
SEED1="${ISAAC_BENCHMARK_SEED1:-3101}"
SETTLE_S="${ISAAC_BENCHMARK_SETTLE_S:-120}"
MAX_ATTEMPTS="${ISAAC_BENCHMARK_MAX_ATTEMPTS:-6}"
OUT="${ISAAC_DATA_ROOT}/benchmarks/m2a-$(date +%Y%m%d-%H%M%S)"

quarantine_failed() {
  local label="$1"
  local attempt="$2"
  local index="$attempt"
  local destination
  mkdir -p "$OUT/quarantine"
  destination="$OUT/quarantine/${label}-attempt-$(printf '%02d' "$index")"
  while [[ -e "$destination" ]]; do
    index=$((index + 1))
    destination="$OUT/quarantine/${label}-attempt-$(printf '%02d' "$index")"
  done
  mv "$OUT/$label" "$destination"
}

run_single() {
  local label="$1"
  local seed="$2"
  local worker_id="$3"
  local gpu="$4"
  local attempt
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    sleep "$SETTLE_S"
    if python3 "${ISAAC_PROJECT_ROOT}/scripts/isaac/launch_worker.py" \
      --project-root "$ISAAC_PROJECT_ROOT" \
      --source-root "$ISAAC_SOURCE_ROOT" \
      --output "$OUT/$label" \
      --sdf "scene-${seed}.sdf" \
      --supervision "scene-${seed}.supervision.json" \
      --worker-id "$worker_id" \
      --gpu "$gpu" \
      --frames "$FRAMES"; then
      return 0
    fi
    quarantine_failed "$label" "$attempt"
  done
  echo "$label exhausted $MAX_ATTEMPTS infrastructure attempts" >&2
  return 1
}

run_dual() {
  local attempt
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    sleep "$SETTLE_S"
    if python3 "${ISAAC_PROJECT_ROOT}/scripts/run_isaac_m1b_dual_benchmark.py" \
      --project-root "$ISAAC_PROJECT_ROOT" \
      --source-root "$ISAAC_SOURCE_ROOT" \
      --output "$OUT/dual" \
      --frames "$FRAMES" \
      --worker-sdf "scene-${SEED0}.sdf" \
      --worker-sdf "scene-${SEED1}.sdf" \
      --worker-supervision "scene-${SEED0}.supervision.json" \
      --worker-supervision "scene-${SEED1}.supervision.json" \
      --container-prefix "m2a-worker-benchmark-${SEED0}-${SEED1}-a${attempt}"; then
      return 0
    fi
    quarantine_failed dual "$attempt"
  done
  echo "dual exhausted $MAX_ATTEMPTS infrastructure attempts" >&2
  return 1
}

run_single single-gpu0 "$SEED0" 0 0
run_single single-gpu1 "$SEED1" 1 1
run_dual

python3 "${ISAAC_PROJECT_ROOT}/scripts/isaac/summarize_worker_benchmark.py" \
  --single-gpu0 "$OUT/single-gpu0/metrics.json" \
  --single-gpu1 "$OUT/single-gpu1/metrics.json" \
  --dual-summary "$OUT/dual/dual-benchmark-summary.json" \
  --report-json "$OUT/m2a-s2-worker-benchmark.json" \
  --report-md "$OUT/m2a-s2-worker-benchmark.md"

echo "$OUT"
