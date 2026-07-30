#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
DATASET_VERSION="${DATASET_VERSION:-isaac-industrial-v1-pilot}"
python scripts/isaac/validate_data_contract.py \
  --dataset-root "${ISAAC_DATA_ROOT}/${DATASET_VERSION}" \
  "$@"

