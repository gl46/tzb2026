#!/usr/bin/env bash
# Ordered M1A runner. S2--S4 are recorded as not-run if S1 blocks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export M1A_RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
export M1A_EXECUTION_BASELINE="${M1A_EXECUTION_BASELINE:-$(git rev-parse HEAD)}"
mkdir -p logs reports data/manifests

bash scripts/run_m1a_preflight.sh
bash scripts/run_m1a_m0_smoke.sh
bash scripts/run_contact_calibration.sh
bash scripts/run_moveit_execution_gate.sh
bash scripts/run_friction_grasp_trials.sh
bash scripts/run_contact_gated_grasp.sh
bash scripts/run_b1_oracle_gate.sh
pytest_log="logs/${M1A_RUN_ID}-pytest.log"
validate_log="logs/${M1A_RUN_ID}-validation.log"
export M1A_PYTEST_PASSED=0
export M1A_PYTEST_FAILED=0
if [[ -x .venv/bin/python ]] && .venv/bin/python -m pytest -q >"$pytest_log" 2>&1; then
  export M1A_PYTEST_PASSED="$(awk '/ passed/{print $1}' "$pytest_log" | tail -n 1)"
else
  export M1A_PYTEST_FAILED=1
fi
if [[ -x .venv/bin/python ]]; then
  (.venv/bin/python scripts/validate_project.py && .venv/bin/ruff check . && git diff --check) >"$validate_log" 2>&1 || true
fi
python3 scripts/write_m1a_status.py "$M1A_RUN_ID"
