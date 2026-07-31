#!/usr/bin/env bash
set -euo pipefail

project_root="${M2B_PROJECT_ROOT:-/home/gl/m2b-qrm-project-20260731}"
python_bin="${M2B_PYTHON:-/home/gl/xh-202607-qrm-lite/.venv-qrm-lite/bin/python}"
dataset_root="${M2B_DATASET_ROOT:-/home/gl/xh-data/isaac-industrial/isaac-industrial-v2-failure-rich-pilot}"
dataset="${M2B_COARSE_DATASET:-${dataset_root}/coarse-training-v2.jsonl}"
model_id="${M2B_MODEL_ID:-/home/gl/xh-202607-qrm-lite/hf-cache/manual/Qwen3.5-4B}"
output_root="${M2B_TRAIN_OUTPUT:-/home/gl/xh-data/qrm-m2b/pipeline-smoke-v1}"

mkdir -p "${output_root}"
cd "${project_root}"
for failure_context in off on; do
  CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src "${python_bin}" \
    scripts/qrm_lite/train_qwen_coarse_beta.py \
    --dataset "${dataset}" \
    --dataset-root "${dataset_root}" \
    --model-id "${model_id}" \
    --revision "" \
    --failure-context "${failure_context}" \
    --epochs 1 \
    --max-train 5 \
    --max-eval 4 \
    --eval-split val \
    --seed 20260731 \
    --adapter-out "${output_root}/${failure_context}-adapter" \
    --report-json "${output_root}/${failure_context}-report.json"
done

PYTHONPATH=src "${python_bin}" - \
  "${dataset}" "${output_root}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

dataset = Path(sys.argv[1])
output = Path(sys.argv[2])
off = json.loads((output / "off-report.json").read_text())
on = json.loads((output / "on-report.json").read_text())
report = {
    "schema_version": "M2BA100CoarsePipelineSmokeV1",
    "status": "PASS_PIPELINE_SMOKE_NOT_FORMAL_ABLATION",
    "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
    "n_train": off["n_train"],
    "n_eval": off["n_eval"],
    "labels": off["labels"],
    "off_eval_accuracy": off["eval_accuracy"],
    "on_eval_accuracy": on["eval_accuracy"],
    "formal_ablation": False,
    "reason": "11-sample pilot only; scale collection is still running",
    "teacher_used": False,
    "privileged_truth_policy_input": False,
}
(output / "smoke-report.json").write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n"
)
print(json.dumps(report, indent=2, sort_keys=True))
PY
