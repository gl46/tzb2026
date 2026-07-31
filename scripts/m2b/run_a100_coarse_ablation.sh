#!/usr/bin/env bash
set -euo pipefail

project_root="${M2B_PROJECT_ROOT:-/home/gl/m2b-qrm-project-20260731}"
python_bin="${M2B_PYTHON:-/home/gl/xh-202607-qrm-lite/.venv-qrm-lite/bin/python}"
dataset_root="${M2B_DATASET_ROOT:-/home/gl/xh-data/isaac-industrial/isaac-industrial-v2-failure-rich}"
dataset="${M2B_COARSE_DATASET:-${dataset_root}/coarse-training-v2.jsonl}"
model_id="${M2B_MODEL_ID:-/home/gl/xh-202607-qrm-lite/hf-cache/manual/Qwen3.5-4B}"
output_root="${M2B_TRAIN_OUTPUT:-/home/gl/xh-data/qrm-m2b/coarse-ablation-v1}"
eval_split="${M2B_EVAL_SPLIT:-val}"
seeds=(20260731 20260801)

mkdir -p "${output_root}"
cd "${project_root}"
PYTHONPATH=src "${python_bin}" scripts/m2b/validate_coarse_training_v2.py \
  --dataset "${dataset}" \
  --report "${output_root}/data-gate.json"
dataset_sha256="$(sha256sum "${dataset}" | cut -d' ' -f1)"

for seed in "${seeds[@]}"; do
  for failure_context in off on; do
    CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src "${python_bin}" \
      scripts/qrm_lite/train_qwen_coarse_beta.py \
      --dataset "${dataset}" \
      --dataset-root "${dataset_root}" \
      --model-id "${model_id}" \
      --revision "" \
      --failure-context "${failure_context}" \
      --epochs 1 \
      --max-train 500 \
      --max-eval 150 \
      --eval-split "${eval_split}" \
      --seed "${seed}" \
      --adapter-out "${output_root}/${seed}-${failure_context}-adapter" \
      --report-json "${output_root}/${seed}-${failure_context}-report.json"
  done
done

PYTHONPATH=src "${python_bin}" scripts/m2b/summarize_coarse_ablation.py \
  --off-report "${output_root}/20260731-off-report.json" \
  --off-report "${output_root}/20260801-off-report.json" \
  --on-report "${output_root}/20260731-on-report.json" \
  --on-report "${output_root}/20260801-on-report.json" \
  --dataset-sha256 "${dataset_sha256}" \
  --report "${output_root}/ablation-report.json"
