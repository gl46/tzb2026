"""Rule-only orientation state estimation from a visible point-cloud extent."""
from __future__ import annotations


def orientation_state(height_m: float, lateral_extent_m: float, top_face_down: bool = False) -> str:
    if height_m <= 0 or lateral_extent_m <= 0:
        return "unknown"
    if lateral_extent_m > height_m * 1.25:
        return "tilted"
    return "inverted" if top_face_down else "normal"
