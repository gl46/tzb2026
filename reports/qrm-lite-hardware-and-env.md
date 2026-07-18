# QRM-Lite hardware and env

```json
{
  "generated_at": "2026-07-18T00:01:28.679598+00:00",
  "local_coordinator": {
    "path": "/Users/gl/tzb-qrm-lite",
    "branch": "codex/qrm-lite-alpha",
    "platform": "macOS-26.4.1-arm64-arm-64bit"
  },
  "train_host": {
    "host": "node2",
    "user": "gl",
    "gpu": "NVIDIA A100-SXM4-80GB",
    "driver": "595.71.05",
    "cuda": "13.2 (nvidia-smi) / torch cu130",
    "torch": "2.13.0+cu130",
    "python": "3.12.3",
    "venv": "~/xh-202607-qrm-lite/.venv-qrm-lite",
    "hf_endpoint": "https://hf-mirror.com",
    "pip_index": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "proxy": "disabled_on_node2_per_user"
  },
  "sim_host_note": "user override: remote only gl@node2; do not use fx@chxy for this track",
  "base_model": "Qwen/Qwen3.5-4B",
  "base_revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
}
```
