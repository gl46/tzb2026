#!/usr/bin/env bash
set -euo pipefail

project_root="${M2B_PROJECT_ROOT:-/home/gl/m2b-qrm-project-20260731}"
python_bin="${M2B_PYTHON:-/home/gl/xh-202607-qrm-lite/.venv-qrm-lite/bin/python}"
dataset_root="${M2B_DATASET_ROOT:-/home/gl/xh-data/isaac-industrial/isaac-industrial-v2-failure-rich}"
dataset="${M2B_RESIDUAL_DATASET:-${dataset_root}/residual-training-v2.jsonl}"
output_root="${M2B_RESIDUAL_TRAIN_OUTPUT:-/home/gl/xh-data/qrm-m2b/residual-mlp-v2}"
eval_split="${M2B_EVAL_SPLIT:-val}"
seeds=(20260731 20260801)

mkdir -p "${output_root}"
cd "${project_root}"

reports=()
for seed in "${seeds[@]}"; do
  report="${output_root}/${seed}-report.json"
  CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src "${python_bin}" \
    scripts/m2b/train_residual_mlp_v2.py \
    --dataset "${dataset}" \
    --eval-split "${eval_split}" \
    --failure-context on \
    --seed "${seed}" \
    --epochs 1000 \
    --learning-rate 0.001 \
    --batch-size 32 \
    --hidden 128 \
    --device cuda \
    --checkpoint "${output_root}/${seed}-mlp.npz" \
    --report "${report}"
  reports+=(--seed-report "${report}")
done

PYTHONPATH=src "${python_bin}" scripts/m2b/summarize_residual_mlp.py \
  "${reports[@]}" \
  --report "${output_root}/two-seed-summary.json"
