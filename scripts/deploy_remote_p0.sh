#!/usr/bin/env bash
# Gated project deployment for a host that already passed the read-only Doctor.
set -euo pipefail

host="${REMOTE_HOST:-node2}"
user="${REMOTE_USER:-}"
remote_root="${REMOTE_PROJECT_ROOT:-xh-202607-world-agent}"
if [[ -z "$user" ]]; then
  case "$host" in node2) user="gl" ;; chxy) user="fx" ;; *) user="${USER}" ;; esac
fi
if [[ ! "$remote_root" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "REMOTE_PROJECT_ROOT must be a simple relative path" >&2
  exit 2
fi
if [[ "${ALLOW_REMOTE_WRITE:-0}" != "1" ]]; then
  echo "DRY_RUN: set ALLOW_REMOTE_WRITE=1 to sync and build robot_ws on ${user}@${host}:${remote_root}"
  exit 0
fi

ssh -o BatchMode=yes -o ConnectTimeout=10 "${user}@${host}" "mkdir -p '${remote_root}'"
rsync -a --exclude .git --exclude .venv --exclude external --exclude reports --exclude data/episodes \
  ./ "${user}@${host}:${remote_root}/"
ssh -o BatchMode=yes -o ConnectTimeout=10 "${user}@${host}" \
  "source /opt/ros/jazzy/setup.bash && cd '${remote_root}/robot_ws' && colcon build --symlink-install"
echo "DEPLOYED: ${user}@${host}:${remote_root}; now run the project-aware remote smoke test"
