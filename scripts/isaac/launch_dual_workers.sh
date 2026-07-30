#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_PROJECT_ROOT:?set ISAAC_PROJECT_ROOT}"
: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
: "${ISAAC_SOURCE_ROOT:?set ISAAC_SOURCE_ROOT}"
DATASET_VERSION="${DATASET_VERSION:-isaac-industrial-v1-pilot}"

python "${ISAAC_PROJECT_ROOT}/scripts/isaac/run_pilot_campaign.py" \
  --project-root "$ISAAC_PROJECT_ROOT" \
  --source-root "$ISAAC_SOURCE_ROOT" \
  --data-root "$ISAAC_DATA_ROOT" \
  --dataset-version "$DATASET_VERSION" \
  "$@"

