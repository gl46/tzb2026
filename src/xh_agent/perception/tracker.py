"""Small deterministic tracker which never consumes simulator entity IDs."""
from __future__ import annotations

import hashlib


def track_id_from_geometry(position_3d: list[float], category: str) -> str:
    """Derive a stable public identifier from quantized observed geometry only."""
    key = f"{category}:{','.join(f'{coordinate:.2f}' for coordinate in position_3d)}"
    return "track-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
