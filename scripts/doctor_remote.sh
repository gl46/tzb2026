#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 ]]; then echo "usage: $0 HOST USER" >&2; exit 2; fi
export PYTHONPATH="${PYTHONPATH:-src}"
python_bin="python3"
if [[ -x .venv/bin/python ]]; then python_bin=".venv/bin/python"; fi
"$python_bin" -m xh_agent.diagnostics.doctor --remote "$1" --user "$2" --output "reports/hardware-remote-$1.json"
