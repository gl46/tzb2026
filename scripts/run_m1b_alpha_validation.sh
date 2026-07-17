#!/usr/bin/env bash
set -euo pipefail
python_bin=".venv/bin/python"
[[ -x "$python_bin" ]] || python_bin="python3"
"$python_bin" -m pytest -q
"$python_bin" scripts/export_schemas.py
"$python_bin" scripts/generate_perception_dataset.py --count 200
"$python_bin" scripts/evaluate_perception.py --manifest data/manifests/m1b-alpha-dataset-v1.json
"$python_bin" -m compileall -q src scripts
"$python_bin" -m ruff check src tests scripts
for file in scripts/run_industrial_scene_v1.sh scripts/record_m1b_alpha_episode.sh scripts/run_m1b_alpha_validation.sh; do bash -n "$file"; done
git diff --check
