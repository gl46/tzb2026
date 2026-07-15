#!/usr/bin/env bash
set -euo pipefail
if [[ "${ALLOW_OFFICIAL_SHALLOW_CLONE:-1}" != "1" ]]; then
  echo "DRY_RUN: official shallow cloning disabled"
  exit 0
fi
echo "DRY_RUN: revisions are locked in configs/upstream.lock.yaml; no upstream is cloned by default."
