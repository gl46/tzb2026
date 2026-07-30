#!/usr/bin/env bash
# Rebuild the M1B p90 gate only from the current ADR-0014 geometry corpus.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 CAPTURED_MANIFEST" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$1"
python_bin="${M1B_PUBLIC_AUDIT_PYTHON:-$root/.venv/bin/python}"
train_audit="$root/reports/m1b-adr0016b-current-geometry-train-audit.json"
test_audit="$root/reports/m1b-adr0016b-current-geometry-perception-metrics.json"
xy_correction="$root/configs/m1b_public_geometry_xy_correction.json"
gate="$root/reports/m1b-adr0016b-current-geometry-reachability-gate.json"

[[ -x "$python_bin" ]] || { echo "PUBLIC_AUDIT_PYTHON_MISSING:$python_bin" >&2; exit 2; }
[[ -f "$manifest" ]] || { echo "CAPTURED_MANIFEST_MISSING:$manifest" >&2; exit 2; }
[[ -f "$root/reports/m1b-adr0016b-tolerance-envelope.json" ]] || { echo "TOLERANCE_EVIDENCE_MISSING" >&2; exit 2; }
[[ -f "$root/configs/m1b_table_supported_cylinder_center.json" ]] || { echo "TABLE_SUPPORTED_Z_CONFIG_MISSING" >&2; exit 2; }

"$python_bin" - "$manifest" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
counts = payload.get("counts")
if counts != {"train": 140, "val": 30, "test": 30}:
    raise SystemExit(f"CURRENT_GEOMETRY_SPLIT_INCOMPLETE:{counts}")
PY

export PYTHONPATH="$root/src:$root/scripts${PYTHONPATH:+:$PYTHONPATH}"
cd "$root"
"$python_bin" scripts/audit_m1b_center_reachability.py "$manifest" --split train --output "$train_audit"
"$python_bin" scripts/fit_m1b_public_geometry_xy_correction.py "$train_audit" --output "$xy_correction"
"$python_bin" scripts/audit_m1b_center_reachability.py "$manifest" --split test --xy-correction "$xy_correction" --table-supported-z configs/m1b_table_supported_cylinder_center.json --output "$test_audit"
"$python_bin" scripts/evaluate_m1b_reachability_gate.py \
  --tolerance-trials reports/m1b-adr0016b-tolerance-envelope.json \
  --perception-errors "$test_audit" \
  --output "$gate"
"$python_bin" - "$gate" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps({"status": payload["status"], "reasons": payload["reasons"], "gate": sys.argv[1]}))
PY
