#!/usr/bin/env bash
set -euo pipefail

: "${ISAAC_DATA_ROOT:?set ISAAC_DATA_ROOT}"
: "${TRAIN_HOST:?set TRAIN_HOST}"
: "${TRAIN_DATA_ROOT:?set TRAIN_DATA_ROOT}"
DATASET_VERSION="${DATASET_VERSION:-isaac-industrial-v1-pilot}"

SOURCE_ROOT="${ISAAC_DATA_ROOT}/${DATASET_VERSION}"
MANIFEST="${SOURCE_ROOT}/manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "dataset manifest missing: $MANIFEST" >&2
  exit 2
fi
if find "${SOURCE_ROOT}/shards" -maxdepth 1 -type d ! -name '*.READY' ! -path "${SOURCE_ROOT}/shards" | grep -q .; then
  echo "non-READY shard present; refusing sync" >&2
  exit 2
fi

ssh "$TRAIN_HOST" "mkdir -p '${TRAIN_DATA_ROOT}/${DATASET_VERSION}/shards'"
rsync -a --partial --append-verify \
  --include='*/' --include='*.READY/***' --exclude='*' \
  "${SOURCE_ROOT}/shards/" \
  "${TRAIN_HOST}:${TRAIN_DATA_ROOT}/${DATASET_VERSION}/shards/"
rsync -a --checksum "$MANIFEST" \
  "${TRAIN_HOST}:${TRAIN_DATA_ROOT}/${DATASET_VERSION}/manifest.json"

