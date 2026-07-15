import json
from pathlib import Path


def main() -> int:
    status = Path("reports/m0-rebaseline-status.json")
    if not status.exists():
        print(json.dumps({"status": "NOT_GENERATED"}))
        return 0
    print(json.dumps(json.loads(status.read_text(encoding="utf-8")), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
