#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOAL_FILE="${GOAL_FILE:-$SCRIPT_DIR/CODEX_GOAL_M2C_HEADROOM.md}"
# M2C 在 M2B 的 worktree 上继续，起点 commit 141e45d。
PROJECT_DIR="${PROJECT_DIR:-/Users/gl/tzb-qrm-lite}"

export ISAAC_HOST="${ISAAC_HOST:-root@labserver}"
export ISAAC_DATA_ROOT="${ISAAC_DATA_ROOT:-/var/tmp/xh-data/isaac-industrial}"

export TRAIN_HOST="${TRAIN_HOST:-node2}"
export TRAIN_USER="${TRAIN_USER:-gl}"
export QRM_REMOTE_ROOT="${QRM_REMOTE_ROOT:-xh-202607-qrm-lite}"

export DATASET_VERSION="${DATASET_VERSION:-isaac-industrial-v3-headroom}"
export M2C_BASE_COMMIT="${M2C_BASE_COMMIT:-141e45d}"
export M2C_BRANCH="${M2C_BRANCH:-codex/m2c-model-headroom}"
export M2C_HARD_FREEZE_DATE="${M2C_HARD_FREEZE_DATE:-2026-09-01}"
export M2C_SUBMISSION_DEADLINE="${M2C_SUBMISSION_DEADLINE:-2026-09-05}"

# 正常研发权限：联网、装依赖、跑 GPU、提交并推送 feature branch。
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

# M2B 证据只读：M2C 不得修改或覆盖任何 m2b-* 正式证据。
export M2B_EVIDENCE_READONLY="${M2B_EVIDENCE_READONLY:-1}"

if [[ ! -f "$GOAL_FILE" ]]; then
  echo "Goal file not found: $GOAL_FILE" >&2
  exit 2
fi

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
  echo "Git project not found: $PROJECT_DIR" >&2
  exit 2
fi

if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
  echo "Working tree is dirty: $PROJECT_DIR" >&2
  echo "M2C must start from a clean tree at $M2C_BASE_COMMIT." >&2
  exit 2
fi

mkdir -p "$PROJECT_DIR/logs"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
FINAL_LOG="$PROJECT_DIR/logs/codex-m2c-final-$RUN_ID.md"
CONSOLE_LOG="$PROJECT_DIR/logs/codex-m2c-console-$RUN_ID.log"

cd "$PROJECT_DIR"

printf 'Starting M2C coordination from %s\n' "$PROJECT_DIR"
printf 'Base commit: %s -> branch %s\n' "$M2C_BASE_COMMIT" "$M2C_BRANCH"
printf 'Isaac host: %s\n' "$ISAAC_HOST"
printf 'Training host: %s@%s, remote root: %s\n' "$TRAIN_USER" "$TRAIN_HOST" "$QRM_REMOTE_ROOT"
printf 'Hard freeze: %s, submission deadline: %s\n' "$M2C_HARD_FREEZE_DATE" "$M2C_SUBMISSION_DEADLINE"
printf 'Network/install/model download/GPU: enabled\n'
printf 'Git commit/push to feature branch: enabled\n'
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
