#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOAL_FILE="${GOAL_FILE:-$SCRIPT_DIR/CODEX_GOAL_QRM_LITE_ALPHA.md}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/xh-202607-world-agent}"

export TRAIN_HOST="${TRAIN_HOST:-chxy}"
export TRAIN_USER="${TRAIN_USER:-gl}"
export QRM_REMOTE_ROOT="${QRM_REMOTE_ROOT:-xh-202607-qrm-lite}"

export SIM_HOST="${SIM_HOST:-node2}"
export SIM_USER="${SIM_USER:-gl}"
export SIM_PROJECT_REMOTE_ROOT="${SIM_PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"

# 本轮是正常研发权限：允许联网、安装依赖、下载 Qwen、跑 GPU、提交和推送 feature branch。
export ALLOW_NETWORK_FETCH="${ALLOW_NETWORK_FETCH:-1}"
export ALLOW_PIP_INSTALL="${ALLOW_PIP_INSTALL:-1}"
export ALLOW_APT_INSTALL="${ALLOW_APT_INSTALL:-1}"
export ALLOW_CONDA_INSTALL="${ALLOW_CONDA_INSTALL:-1}"
export ALLOW_MODEL_DOWNLOAD="${ALLOW_MODEL_DOWNLOAD:-1}"
export MAX_MODEL_DOWNLOAD_GIB="${MAX_MODEL_DOWNLOAD_GIB:-30}"
export ALLOW_CONTAINER_PULL="${ALLOW_CONTAINER_PULL:-1}"
export ALLOW_GPU_RUN="${ALLOW_GPU_RUN:-1}"
export ALLOW_REMOTE_PROJECT_WRITE="${ALLOW_REMOTE_PROJECT_WRITE:-1}"
export ALLOW_SIM_DATA_GENERATION="${ALLOW_SIM_DATA_GENERATION:-1}"
export ALLOW_GIT_BRANCH="${ALLOW_GIT_BRANCH:-1}"
export ALLOW_GIT_COMMIT="${ALLOW_GIT_COMMIT:-1}"
export ALLOW_GIT_PUSH="${ALLOW_GIT_PUSH:-1}"

if [[ ! -f "$GOAL_FILE" ]]; then
  echo "Goal file not found: $GOAL_FILE" >&2
  exit 2
fi

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  echo "Git project not found: $PROJECT_DIR" >&2
  exit 2
fi

mkdir -p "$PROJECT_DIR/logs"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
FINAL_LOG="$PROJECT_DIR/logs/codex-qrm-lite-alpha-final-$RUN_ID.md"
CONSOLE_LOG="$PROJECT_DIR/logs/codex-qrm-lite-alpha-console-$RUN_ID.log"

cd "$PROJECT_DIR"

printf 'Starting QRM-Lite alpha coordination from %s\n' "$PROJECT_DIR"
printf 'Training host: %s@%s, remote root: %s\n' "$TRAIN_USER" "$TRAIN_HOST" "$QRM_REMOTE_ROOT"
printf 'Simulation host: %s@%s\n' "$SIM_USER" "$SIM_HOST"
printf 'Network/install/model download/GPU: enabled\n'
printf 'Git commit/push to feature branch: enabled\n'
printf 'Goal: %s\n' "$GOAL_FILE"
printf 'Final log: %s\n' "$FINAL_LOG"

# workspace-write keeps the local coordinating repository bounded, while explicit
# network access allows official-source research and SSH work on the configured nodes.
# The Goal itself permits normal package installation and model download on the dedicated nodes.
set -o pipefail
codex exec \
  --search \
  --sandbox workspace-write \
  --ask-for-approval never \
  -c 'sandbox_workspace_write.network_access=true' \
  -o "$FINAL_LOG" \
  - < "$GOAL_FILE" \
  2>&1 | tee "$CONSOLE_LOG"
