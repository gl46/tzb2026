"""Command construction for a non-fabricating ffmpeg image-sequence export."""
from __future__ import annotations

from pathlib import Path


def ffmpeg_command(frames_dir: Path, output: Path, fps: int = 15) -> list[str]:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames_dir / "frame_%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)]
