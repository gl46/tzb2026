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

LOCAL_MANIFEST_SHA256="$(sha256sum "$MANIFEST" | cut -d' ' -f1)"
REMOTE_MANIFEST_SHA256="$(
  ssh "$TRAIN_HOST" \
    "if test -f '${TRAIN_DATA_ROOT}/${DATASET_VERSION}/manifest.json'; then sha256sum '${TRAIN_DATA_ROOT}/${DATASET_VERSION}/manifest.json' | cut -d' ' -f1; else echo missing; fi"
)"
if [[ "$REMOTE_MANIFEST_SHA256" != "missing" && "$REMOTE_MANIFEST_SHA256" != "$LOCAL_MANIFEST_SHA256" ]]; then
  echo "remote dataset version has a different manifest; refusing overwrite" >&2
  exit 2
fi

ssh "$TRAIN_HOST" "mkdir -p '${TRAIN_DATA_ROOT}/${DATASET_VERSION}/shards'"
rsync -aH --partial --append-verify \
  --include='*/' --include='*.READY/***' --exclude='*' \
  "${SOURCE_ROOT}/shards/" \
  "${TRAIN_HOST}:${TRAIN_DATA_ROOT}/${DATASET_VERSION}/shards/"
rsync -a --checksum "$MANIFEST" \
  "${TRAIN_HOST}:${TRAIN_DATA_ROOT}/${DATASET_VERSION}/manifest.json"
REMOTE_MANIFEST_SHA256="$(
  ssh "$TRAIN_HOST" \
    "sha256sum '${TRAIN_DATA_ROOT}/${DATASET_VERSION}/manifest.json' | cut -d' ' -f1"
)"
if [[ "$REMOTE_MANIFEST_SHA256" != "$LOCAL_MANIFEST_SHA256" ]]; then
  echo "remote manifest checksum mismatch after sync" >&2
  exit 2
fi
