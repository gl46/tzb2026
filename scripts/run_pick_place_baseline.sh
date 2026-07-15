#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:-src}"
python_bin="python3"
if [[ -x .venv/bin/python ]]; then python_bin=".venv/bin/python"; fi
"$python_bin" -m xh_agent.baselines.cli
