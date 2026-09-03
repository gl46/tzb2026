# QRM-Lite Alpha Codex bundle

Files:

- `CODEX_GOAL_QRM_LITE_ALPHA.md`
- `run_codex_qrm_lite_alpha.sh`

Recommended launch:

```bash
mkdir -p ~/codex-goals/xh-202607/qrm-lite-alpha
cd ~/codex-goals/xh-202607/qrm-lite-alpha
# Copy the two files here.
chmod +x run_codex_qrm_lite_alpha.sh

export PROJECT_DIR="$HOME/projects/xh-202607-world-agent"
export TRAIN_HOST="chxy"
export TRAIN_USER="gl"
export QRM_REMOTE_ROOT="xh-202607-qrm-lite"
export SIM_HOST="node2"
export SIM_USER="gl"
export SIM_PROJECT_REMOTE_ROOT="xh-202607-world-agent"

tmux new -s xh-qrm-a
./run_codex_qrm_lite_alpha.sh
```

Detach from tmux with `Ctrl+B`, then `D`.

The launcher intentionally enables network access, ordinary pip/apt/conda installation,
Qwen model download, GPU execution, and feature-branch commit/push. It does not authorize
force-push, automatic merge to main, driver/kernel replacement, or destructive cleanup.
