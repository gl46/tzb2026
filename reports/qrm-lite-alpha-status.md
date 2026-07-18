# QRM-Lite Alpha status

- status: **PASS_QRM_ALPHA_WITH_LIMITATIONS**
- gate: **GO_COARSE_AND_MLP_ONLY**
- branch/commit: `codex/qrm-lite-alpha` / `98b5747247bf`
- Qwen multimodal/hidden/LoRA: True/True/True
- peak VRAM: 17824.9 MB; forward: 9.99s
- dataset_samples: 120
- coarse/mlp overfit: True/True
- flow fb/loss↓ / >mlp: True/True/False
- tests: 12 passed
- pushed: True

## Limitations
- Flow does not outperform MLP on alpha offline split; keep MLP as primary residual head
- Dataset is mostly geometric synthetic fixtures + 20 empty-grasp logs, not full Gazebo RGB-D scale
- Closed-loop Gazebo smoke not required for alpha and not run
- Flow numpy path is a prototype; torch path preferred on A100 for further work

## Next
`ssh gl@node2 'cd ~/xh-202607-qrm-lite && source .venv-qrm-lite/bin/activate && PYTHONPATH=src python scripts/qrm_lite/train_mlp_refiner.py --limit 100 --epochs 400'`
