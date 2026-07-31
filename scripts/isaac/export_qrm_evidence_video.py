#!/usr/bin/env python3
"""Render an honest QRM-FC closed-loop evidence video from retained RGB frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


CAMERAS = ("front_rgbd", "overhead_rgbd", "side_rgbd", "policy_rgbd")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _font(size: int) -> ImageFont.ImageFont:
    candidates = (
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def decision_lines(decision: dict[str, Any], step: int) -> list[str]:
    failure = decision["failure_context"]
    return [
        f"Step {step} | public tracks={decision['public_track_count']} | "
        f"coarse skill={decision['coarse_skill']}",
        f"expected={failure['expected_predicates']} | observed={failure['observed_predicates']}",
        f"FailureContext={failure['failure_type']} retry={failure['retry_count']} | "
        f"model={decision['model_id']}",
        f"model mapping={decision['mapping_validation']} | executed fallback={decision['fallback']}",
    ]


def render_frame(
    run_root: Path,
    decision: dict[str, Any],
    step: int,
    destination: Path,
) -> None:
    canvas = Image.new("RGB", (1280, 1120), "#101318")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(28)
    body_font = _font(21)
    small_font = _font(18)
    draw.text(
        (24, 18),
        "QRM-FC CLOSED LOOP — REPRESENTATIVE FAILURE / B0 FALLBACK",
        fill="#ffd166",
        font=title_font,
    )
    header = [
        "Instruction: Observe the leftmost industrial cylinder while moving.",
        "TaskSpec: observe_dynamics; target track was not retained in this smoke artifact.",
        "Final result: task_success=false. This video is not labelled as a successful task.",
    ]
    y = 58
    for line in header:
        draw.text((24, y), line, fill="#f2f2f2", font=body_font)
        y += 30

    tile_width, tile_height = 600, 360
    for camera_index, camera in enumerate(CAMERAS):
        source = run_root / camera / "rgb" / f"{step:06d}.png"
        if not source.is_file():
            raise FileNotFoundError(source)
        with Image.open(source) as image:
            tile = image.convert("RGB")
            tile.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
            x = 24 + (camera_index % 2) * 628
            tile_y = 162 + (camera_index // 2) * 400
            canvas.paste(tile, (x, tile_y))
            draw.rectangle(
                (x, tile_y, x + tile.width, tile_y + tile.height),
                outline="#777777",
                width=2,
            )
            draw.text((x + 8, tile_y + 8), camera, fill="#ffffff", font=small_font)

    footer_y = 970
    for line in decision_lines(decision, step):
        wrapped = textwrap.wrap(line, width=102)
        for part in wrapped:
            draw.text((24, footer_y), part, fill="#d8dee9", font=body_font)
            footer_y += 27
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)


def export_video(run_root: Path, output: Path, ffmpeg: str) -> dict[str, Any]:
    metrics = json.loads((run_root / "metrics.json").read_text(encoding="utf-8"))
    smoke = metrics["qrm_closed_loop_smoke"]
    decisions = smoke["decisions"]
    with tempfile.TemporaryDirectory(prefix="m2a-qrm-video-") as temporary:
        frames = Path(temporary)
        for step, decision in enumerate(decisions):
            render_frame(run_root, decision, step, frames / f"{step:06d}.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                "1",
                "-i",
                str(frames / "%06d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip())
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("ffmpeg did not create a non-empty video")
    return {
        "schema_version": "M2AVideoEvidenceV1",
        "status": "PARTIAL_ONE_OF_THREE",
        "teacher_enabled": False,
        "videos": {
            "normal_success": {
                "status": "NOT_AVAILABLE_NO_RETAINED_CAPTURE",
                "reason": "M2A Pilot contains no task_success=true episode.",
            },
            "wrong_object_recovery": {
                "status": "NOT_AVAILABLE_NO_RETAINED_CAPTURE",
                "reason": "M1B has accepted JSON evidence but no retained synchronized video.",
            },
            "qrm_fc_closed_loop": {
                "status": "PASS_REPRESENTATIVE_FAILURE",
                "path": str(output),
                "bytes": output.stat().st_size,
                "sha256": sha256(output),
                "frames": len(decisions),
                "duration_s": len(decisions),
                "final_task_success": False,
                "fallback_rate": smoke["fallback_rate"],
                "mapping_validation": smoke["model_action_mapping"],
            },
        },
        "editing_policy": "all retained decision steps included; no failure step removed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("reports/m2a-s8-video-evidence.json"),
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("reports/m2a-s8-video-evidence.md"),
    )
    args = parser.parse_args()
    report = export_video(args.run_root.resolve(), args.output.resolve(), args.ffmpeg)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    qrm = report["videos"]["qrm_fc_closed_loop"]
    args.report_md.write_text(
        "\n".join(
            [
                "# M2A S8 video evidence",
                "",
                f"- status: **{report['status']}**",
                "- Teacher: disabled",
                "- normal success: unavailable; the M2A Pilot has no successful task episode",
                "- WRONG_OBJECT recovery: accepted JSON evidence exists, but no synchronized "
                "video was retained",
                "- QRM-FC: representative failure video retained with every decision step",
                f"- QRM fallback rate: {qrm['fallback_rate']}",
                f"- QRM action mapping: `{qrm['mapping_validation']}`",
                f"- video SHA-256: `{qrm['sha256']}`",
                "",
            ]
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
