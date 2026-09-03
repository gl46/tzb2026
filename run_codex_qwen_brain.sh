#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOAL_FILE="${GOAL_FILE:-$SCRIPT_DIR/CODEX_GOAL_QWEN_BRAIN.md}"
PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/xh-202607-qwen-brain}"
SOURCE_REPO="${SOURCE_REPO:-/Users/gl/tzb-qrm-lite}"
BASE_BRANCH="${BASE_BRANCH:-codex/m2c-deliverables-instruction}"
WORK_BRANCH="${WORK_BRANCH:-codex/qwen-brain}"

export INFER_HOST="${INFER_HOST:-node2}"
export INFER_USER="${INFER_USER:-gl}"
export INFER_PORT="${INFER_PORT:-18767}"
export TRAIN_HOST="${TRAIN_HOST:-chxy}"
export TRAIN_USER="${TRAIN_USER:-fx}"

# 演示线权限:联网、装依赖、GPU 推理、本克隆内 commit。
# 硬禁:push 回源仓库、写源仓库本体、labserver m2c 治理根、任何 ordinal 消费。
export ALLOW_NETWORK_FETCH="${ALLOW_NETWORK_FETCH:-1}"
export ALLOW_PIP_INSTALL="${ALLOW_PIP_INSTALL:-1}"
export ALLOW_MODEL_DOWNLOAD="${ALLOW_MODEL_DOWNLOAD:-1}"
export MAX_MODEL_DOWNLOAD_GIB="${MAX_MODEL_DOWNLOAD_GIB:-60}"
export ALLOW_GPU_RUN="${ALLOW_GPU_RUN:-1}"
export ALLOW_GIT_BRANCH="${ALLOW_GIT_BRANCH:-1}"
export ALLOW_GIT_COMMIT="${ALLOW_GIT_COMMIT:-1}"
export ALLOW_GIT_PUSH=0

if [[ ! -f "$GOAL_FILE" ]]; then
  echo "Goal file not found: $GOAL_FILE" >&2
  exit 2
fi

# 专用克隆:对源仓库只读;origin push 永久禁用,防止任何误推回治理仓库。
if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  git clone --branch "$BASE_BRANCH" "$SOURCE_REPO" "$PROJECT_DIR"
  git -C "$PROJECT_DIR" remote set-url --push origin DISABLED_BY_POLICY
  git -C "$PROJECT_DIR" checkout -b "$WORK_BRANCH"
fi

mkdir -p "$PROJECT_DIR/logs"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
FINAL_LOG="$PROJECT_DIR/logs/codex-qwen-brain-final-$RUN_ID.md"
CONSOLE_LOG="$PROJECT_DIR/logs/codex-qwen-brain-console-$RUN_ID.log"

cd "$PROJECT_DIR"

printf 'Starting Qwen-brain line from %s (branch %s)\n' "$PROJECT_DIR" "$WORK_BRANCH"
printf 'Inference host: %s@%s port %s (Qwen3.6-27B multimodal, on-disk)\n' "$INFER_USER" "$INFER_HOST" "$INFER_PORT"
printf 'Optional LoRA host: %s@%s\n' "$TRAIN_USER" "$TRAIN_HOST"
printf 'Hard limits: no push, no source-repo writes, no labserver m2c roots, 0 ordinals\n'
printf 'Goal: %s\n' "$GOAL_FILE"
printf 'Final log: %s\n' "$FINAL_LOG"

set -o pipefail
codex exec \
  --search \
  --sandbox workspace-write \
  --ask-for-approval never \
  -c 'sandbox_workspace_write.network_access=true' \
  -o "$FINAL_LOG" \
  - < "$GOAL_FILE" \
  2>&1 | tee "$CONSOLE_LOG"
