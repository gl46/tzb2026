#!/usr/bin/env bash
set -euo pipefail

remote_host="${M2B_REMOTE_HOST:-root@labserver}"
project_root="${ISAAC_PROJECT_ROOT:-/var/tmp/m2a-isaac-project-20260731}"
source_root="${ISAAC_SOURCE_ROOT:-/var/tmp/m1b-isaac-benchmark-assets/source}"
stage="${ISAAC_STAGE:-/var/tmp/m1b-isaac-production-parity-stage-build-20260729/output/m1b_physics_scene.usdc}"
output_root="${M2B_OUTPUT_ROOT:?M2B_OUTPUT_ROOT is required and must be a new remote directory}"
failures="${M2B_FAILURES:-EMPTY_GRASP,WRONG_OBJECT,RELEASE_FAILURE}"

ssh -o BatchMode=yes "${remote_host}" \
  python3 "${project_root}/scripts/m2b/run_physical_failure_smoke.py" \
  --project-root "${project_root}" \
  --source-root "${source_root}" \
  --stage "${stage}" \
  --output-root "${output_root}" \
  --gpu "${ISAAC_GPU:-0}" \
  --target-object "${M2B_INJECTED_OBJECT:-cylinder_04}" \
  --public-target-object "${M2B_PUBLIC_TARGET_OBJECT:-cylinder_04}" \
  --wrong-object-task-target "${M2B_WRONG_TASK_TARGET:-cylinder_07}" \
  --max-attempts "${M2B_MAX_ATTEMPTS:-2}" \
  --settle-s "${M2B_SETTLE_S:-30}" \
  --capture-public-rgbd \
  --failures "${failures}"
