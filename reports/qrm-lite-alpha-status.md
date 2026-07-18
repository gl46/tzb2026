# QRM-Lite Alpha status

- status: **PARTIAL**
- gate: **CONTINUE_WITH_FIXES**
- branch: `codex/qrm-lite-alpha`
- dataset_samples: 120
- coarse_overfit: True
- mlp_overfit: True
- flow_fb/loss↓: True/True
- flow>mlp: False
- qwen_forward: False
- tests: 12 passed
- blockers: ['Qwen3.5-4B weight download still running on node2 via hf-mirror (xet path 401; wget resume used)']
- next: `ssh gl@node2 'tail -f ~/xh-202607-qrm-lite/logs/qwen-download.log'`
