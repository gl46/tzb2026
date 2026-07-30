#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_PROJECT_ROOT:?set ISAAC_PROJECT_ROOT}"
: "${ISAAC_SOURCE_ROOT:?set ISAAC_SOURCE_ROOT}"
: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
OUT="${ISAAC_DATA_ROOT}/benchmarks/m2a-$(date +%Y%m%d-%H%M%S)"
python "${ISAAC_PROJECT_ROOT}/scripts/run_isaac_m1b_dual_benchmark.py" \
  --project-root "$ISAAC_PROJECT_ROOT" \
  --source-root "$ISAAC_SOURCE_ROOT" \
  --output "$OUT" \
  --frames 100

