#!/usr/bin/env bash
set -euo pipefail
if [[ "${ALLOW_TEACHER_GPU_RUN:-0}" != "1" ]]; then
  echo "BLOCKED: ALLOW_TEACHER_GPU_RUN=0; no Teacher model or GPU process will start."
  exit 0
fi
echo "BLOCKED: M0-R provides service templates only; a human ADR plus separately reviewed service deployment is required."
exit 3
