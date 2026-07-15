#!/usr/bin/env bash
set -euo pipefail
model_id="${1:-}"
target="${2:-external/teacher-models}"
if [[ -z "$model_id" ]]; then echo "usage: $0 MODEL_ID [IGNORED_EXTERNAL_TARGET]" >&2; exit 2; fi
if [[ "$target" != external/* ]]; then echo "refusing target outside ignored external/: $target" >&2; exit 2; fi
if [[ "${ALLOW_LARGE_DOWNLOAD:-0}" != "1" ]]; then
  echo "DRY_RUN: ALLOW_LARGE_DOWNLOAD=0; would request metadata/download for $model_id into $target"
  exit 0
fi
echo "Refusing automatic download: model-license acceptance and an explicit human retrieval procedure are required." >&2
exit 3
