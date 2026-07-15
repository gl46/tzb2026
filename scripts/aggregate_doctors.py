"""Combine bounded per-host Doctor results into the required remote evidence report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    reports = Path("reports")
    hosts = {}
    for host in ("node2", "chxy"):
        path = reports / f"hardware-remote-{host}.json"
        hosts[host] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "MISSING_REPORT"}
    output = {"scope": "remote-aggregate", "generated_at": datetime.now(timezone.utc).isoformat(), "hosts": hosts}
    (reports / "hardware-remote.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": "reports/hardware-remote.json", "hosts": sorted(hosts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
