#!/usr/bin/env bash
set -euo pipefail
output_dir="${1:-data/episodes/m1b-alpha}"
exec python3 scripts/record_m1b_alpha_ros.py --output-dir "$output_dir"
