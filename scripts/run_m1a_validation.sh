#!/usr/bin/env bash
# Ordered M1A runner. S2--S4 are recorded as not-run if S1 blocks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export M1A_RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
export M1A_EXECUTION_BASELINE="${M1A_EXECUTION_BASELINE:-$(git rev-parse HEAD)}"
mkdir -p logs reports data/manifests

bash scripts/run_m1a_preflight.sh
bash scripts/run_contact_calibration.sh
bash scripts/run_moveit_execution_gate.sh
bash scripts/run_friction_grasp_trials.sh
bash scripts/run_contact_gated_grasp.sh
bash scripts/run_b1_oracle_gate.sh
python3 scripts/write_m1a_status.py "$M1A_RUN_ID"
