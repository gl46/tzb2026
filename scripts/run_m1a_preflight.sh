#!/usr/bin/env bash
# M1A preflight deliberately leaves M0 evidence untouched.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
RUN_ID="${M1A_RUN_ID:-m1a-$(date +%Y%m%d-%H%M%S)}"
SIM_HOST="${SIM_HOST:-node2}"
SIM_USER="${SIM_USER:-gl}"
PROJECT_REMOTE_ROOT="${PROJECT_REMOTE_ROOT:-xh-202607-world-agent}"
BASELINE_COMMIT="${M1A_DOCUMENT_BASELINE:-22ce578}"
EXECUTION_BASELINE="${M1A_EXECUTION_BASELINE:-$(git rev-parse HEAD)}"
mkdir -p logs reports

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
head_hash="$(git rev-parse HEAD)"
origin_hash="$(git rev-parse origin/main)"
branch="$(git branch --show-current)"
worktree="$(git status --short)"
tag_status="M0_TAG_MISSING_NONBLOCKING"
if git tag --points-at "$BASELINE_COMMIT" | grep -qx 'm0-r-baseline'; then tag_status="VERIFIED"; fi
if git show-ref --tags --verify --quiet "refs/tags/m0-r-baseline" && ! git merge-base --is-ancestor "$BASELINE_COMMIT" "m0-r-baseline"; then tag_status="M0_TAG_MISMATCH"; fi
remote_probe="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SIM_USER@$SIM_HOST" "test -d \"\$HOME/$PROJECT_REMOTE_ROOT\" && sha256sum \"\$HOME/$PROJECT_REMOTE_ROOT/robot_ws/src/xh_sim/urdf/panda_controlled.urdf\"" 2>&1 || true)"
local_urdf_sha="$(sha256sum robot_ws/src/xh_sim/urdf/panda_controlled.urdf | awk '{print $1}')"
can_start=true
blockers=()
if [[ -n "$worktree" ]]; then can_start=false; blockers+=("BLOCKED_DIRTY_OR_MOVED_BASELINE"); fi
if [[ "$head_hash" != "$EXECUTION_BASELINE" ]]; then can_start=false; blockers+=("EXECUTION_BASELINE_MISMATCH"); fi
if [[ "$remote_probe" == *"No such file"* || "$remote_probe" == *"not found"* ]]; then can_start=false; blockers+=("REMOTE_PROJECT_UNAVAILABLE"); fi
printf '%s\n' "$remote_probe" >"logs/${RUN_ID}-preflight-remote.log"

python3 - "$RUN_ID" "$started_at" "$head_hash" "$origin_hash" "$branch" "$BASELINE_COMMIT" "$EXECUTION_BASELINE" "$tag_status" "$local_urdf_sha" "$remote_probe" "$can_start" "${blockers[*]:-}" <<'PY'
import json, sys
from pathlib import Path
keys = ("run_id", "started_at", "head", "origin_main", "branch", "document_baseline", "execution_baseline", "m0_tag_status", "local_urdf_sha256", "remote_probe", "can_start", "blockers")
d = dict(zip(keys, sys.argv[1:]))
d["can_start"] = d["can_start"] == "true"
d["blockers"] = d["blockers"].split() if d["blockers"] else []
d["baseline_origin_match"] = d["head"] == d["origin_main"]
d["execution_baseline_matches_head"] = d["head"] == d["execution_baseline"]
Path("reports/m1a-preflight.json").write_text(json.dumps(d, indent=2) + "\n")
Path("reports/m1a-preflight.md").write_text(
    "# M1A preflight\n\n"
    f"- Run: `{d['run_id']}`\n- Document baseline: `{d['document_baseline']}`\n"
    f"- Authorized execution baseline: `{d['execution_baseline']}`\n"
    f"- HEAD / origin-main: `{d['head']}` / `{d['origin_main']}`\n"
    f"- M0 tag: `{d['m0_tag_status']}`\n- Can start remote stages: `{d['can_start']}`\n"
    f"- Blockers: `{', '.join(d['blockers']) or 'none'}`\n"
)
PY

[[ "$can_start" == true ]]
