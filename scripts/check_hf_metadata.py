"""Small metadata-only audit; never downloads a checkpoint or sends credentials."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


MODELS = ["nvidia/Cosmos3-Nano", "BLM-Lab/Boundless-World-Model", "nvidia/Cosmos3-Super"]


def lookup(model: str) -> dict[str, object]:
    request = urllib.request.Request(f"https://huggingface.co/api/models/{model}", headers={"User-Agent": "xh-m0-audit/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        card = payload.get("cardData") or {}
        return {"status": "FOUND", "id": payload.get("id"), "revision": payload.get("sha"),
                "gated": payload.get("gated"), "private": payload.get("private"), "license": card.get("license")}
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return {"status": "ERROR", "error": type(error).__name__, "message": str(error)[:160]}


def main() -> int:
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "metadata_only": True,
              "allow_large_download": False, "models": {model: lookup(model) for model in MODELS}}
    Path("reports/model-access.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "models_checked": len(MODELS)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
