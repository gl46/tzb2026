#!/usr/bin/env python3
"""Export honest M2B success, WRONG_OBJECT, and attribution deliverables for S1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import textwrap
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopEpisodeV1,
    pure_model_success_episode,
)


PROJECT = Path(__file__).resolve().parents[2]
M2B_REMOTE_ROOT = PurePosixPath(
    "/var/tmp/xh-data/isaac-industrial/m2b/matched-closed-loop-v1"
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def select_successful_wrong_object_fc(
    episodes: list[dict[str, Any]],
    episode_id: str | None = None,
) -> M2BClosedLoopEpisodeV1:
    candidates = [
        M2BClosedLoopEpisodeV1.model_validate(record)
        for record in episodes
        if record.get("failure_type") == "WRONG_OBJECT"
        and record.get("method") == "QRM_COARSE_FC"
        and record.get("final_success") is True
        and record.get("recovery_success") is True
        and (episode_id is None or record.get("episode_id") == episode_id)
    ]
    if not candidates:
        raise ValueError("no successful M2B QRM_COARSE_FC WRONG_OBJECT episode")
    return sorted(candidates, key=lambda item: item.episode_id)[0]


def validated_remote_path(path: str) -> PurePosixPath:
    if re.fullmatch(r"/[A-Za-z0-9._/-]+", path) is None:
        raise ValueError(f"unsafe remote path: {path}")
    candidate = PurePosixPath(path)
    if not candidate.is_relative_to(M2B_REMOTE_ROOT):
        raise ValueError(f"remote evidence escapes frozen M2B root: {path}")
    return candidate


def capture_remote_path(evidence_path: PurePosixPath, uri: str) -> PurePosixPath:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported capture URI: {uri}")
    relative = PurePosixPath(uri.removeprefix(prefix))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"capture URI escapes evidence directory: {uri}")
    candidate = evidence_path.parent / relative
    if not candidate.is_relative_to(evidence_path.parent):
        raise ValueError(f"capture URI escapes evidence directory: {uri}")
    return candidate


def remote_bytes(host: str, path: PurePosixPath) -> bytes:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "cat", str(path)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"remote read failed {host}:{path}: "
            f"{completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def depth_visualization(path: Path) -> Image.Image:
    depth = np.load(path, allow_pickle=False)
    if depth.ndim != 2:
        raise ValueError(f"depth must be HxW: {path}")
    finite = np.isfinite(depth) & (depth > 0)
    if not finite.any():
        raise ValueError(f"depth has no finite positive samples: {path}")
    low, high = np.percentile(depth[finite], (2.0, 98.0))
    scale = max(float(high - low), 1e-9)
    normalized = np.zeros(depth.shape, dtype=np.float32)
    normalized[finite] = np.clip((high - depth[finite]) / scale, 0.0, 1.0)
    red = (normalized * 255).astype(np.uint8)
    green = (np.sqrt(normalized) * 220).astype(np.uint8)
    blue = ((1.0 - normalized) * 180).astype(np.uint8)
    rgb = np.stack([red, green, blue], axis=-1)
    rgb[~finite] = 0
    return Image.fromarray(rgb, mode="RGB")


def fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    result = image.convert("RGB")
    result.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "#05070a")
    canvas.paste(
        result,
        ((size[0] - result.width) // 2, (size[1] - result.height) // 2),
    )
    return canvas


def render_rgbd_frame(
    *,
    rgb_path: Path,
    depth_path: Path,
    title: str,
    subtitle: str,
    lines: list[str],
    output: Path,
) -> None:
    canvas = Image.new("RGB", (1440, 900), "#101318")
    draw = ImageDraw.Draw(canvas)
    title_font = font(30)
    body_font = font(21)
    small_font = font(18)
    draw.text((24, 18), title, fill="#ffd166", font=title_font)
    draw.text((24, 58), subtitle, fill="#f4f4f4", font=body_font)
    with Image.open(rgb_path) as source:
        rgb = fit(source, (680, 510))
    depth = fit(depth_visualization(depth_path), (680, 510))
    canvas.paste(rgb, (24, 106))
    canvas.paste(depth, (736, 106))
    draw.rectangle((24, 106, 704, 616), outline="#8b949e", width=2)
    draw.rectangle((736, 106, 1416, 616), outline="#8b949e", width=2)
    draw.text((38, 118), "public RGB", fill="#ffffff", font=small_font)
    draw.text((750, 118), "public metric depth", fill="#ffffff", font=small_font)
    y = 642
    for line in lines:
        for part in textwrap.wrap(line, width=112):
            draw.text((24, y), part, fill="#d8dee9", font=body_font)
            y += 30
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def encode_video(frames: Path, output: Path, ffmpeg: str) -> dict[str, Any]:
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
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg created no video: {output}")
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
    }


def capture_stage(label: str) -> str:
    return {
        "before_failure": "before failed grasp",
        "after_physical_lift": "wrong object physically lifted",
        "after_recovery_retreat": "model-selected SAFE_PLACE_NON_TARGET complete",
        "wrong_object_target_after_regrasp": "B0 continuation regrasped intended target",
    }.get(label, label)


def changed_files(project: Path, generated: set[str]) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=project,
        capture_output=True,
        check=True,
        text=True,
    )
    return sorted(
        {
            *(line[3:] for line in completed.stdout.splitlines() if len(line) > 3),
            *generated,
        }
    )


def export_evidence(
    *,
    episodes_path: Path,
    journal_path: Path,
    host: str,
    output_root: Path,
    ffmpeg: str,
    episode_id: str | None,
) -> dict[str, Any]:
    if "m2b" in {part.lower() for part in output_root.parts}:
        raise ValueError("S1 output must not write inside an M2B evidence path")
    episode = select_successful_wrong_object_fc(
        load_jsonl(episodes_path), episode_id=episode_id
    )
    journals = {
        item["episode_id"]: item for item in load_jsonl(journal_path)
    }
    journal = journals.get(episode.episode_id)
    if not journal or journal.get("status") != "EVALUATION_EXECUTION_RECORDED":
        raise ValueError("selected episode lacks a recorded execution journal")
    if journal.get("teacher_used") is not False:
        raise ValueError("Teacher evidence is forbidden")
    if journal.get("privileged_truth_policy_input") is not False:
        raise ValueError("privileged truth entered policy input")
    evidence_path = validated_remote_path(str(journal["execution_evidence_path"]))
    evidence_bytes = remote_bytes(host, evidence_path)
    if sha256_bytes(evidence_bytes) != journal["execution_evidence_sha256"]:
        raise ValueError("remote actuation evidence differs from M2B journal hash")
    evidence = json.loads(evidence_bytes)
    public_rgbd = evidence.get("m2b_public_rgbd") or {}
    if public_rgbd.get("simulator_truth_policy_input") is not False:
        raise ValueError("public RGB-D evidence declares simulator truth policy input")
    recovery = (evidence.get("m2b_recovery") or {}).get("wrong_object") or {}
    if not (
        recovery.get("safe_place_non_target_passed") is True
        and recovery.get("reassociate_target_executed") is True
        and recovery.get("regrasp_target_executed") is True
    ):
        raise ValueError("WRONG_OBJECT recovery chain is incomplete")
    captures = sorted(public_rgbd.get("captures", []), key=lambda item: item["timestamp_ns"])
    if len(captures) < 4:
        raise ValueError("WRONG_OBJECT evidence needs at least four synchronized captures")

    output_root.mkdir(parents=True, exist_ok=True)
    source_dir = output_root / "source"
    capture_dir = output_root / "captures"
    source_dir.mkdir(parents=True, exist_ok=True)
    capture_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "actuation-probe.json").write_bytes(evidence_bytes)
    (source_dir / "episode.json").write_text(
        json.dumps(episode.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    (source_dir / "journal.json").write_text(
        json.dumps(journal, indent=2, sort_keys=True) + "\n"
    )

    local_captures = []
    for capture in captures:
        label = capture["label"]
        rgb_remote = capture_remote_path(evidence_path, capture["rgb_uri"])
        depth_remote = capture_remote_path(evidence_path, capture["depth_uri"])
        rgb_bytes = remote_bytes(host, rgb_remote)
        depth_bytes = remote_bytes(host, depth_remote)
        if sha256_bytes(rgb_bytes) != capture["rgb_sha256"]:
            raise ValueError(f"{label}: RGB hash mismatch")
        if sha256_bytes(depth_bytes) != capture["depth_sha256"]:
            raise ValueError(f"{label}: depth hash mismatch")
        rgb_path = capture_dir / f"{label}.png"
        depth_path = capture_dir / f"{label}.npy"
        rgb_path.write_bytes(rgb_bytes)
        depth_path.write_bytes(depth_bytes)
        depth = np.load(depth_path, allow_pickle=False)
        finite = int((np.isfinite(depth) & (depth > 0)).sum())
        if finite != int(capture["finite_depth_samples"]):
            raise ValueError(f"{label}: finite depth count mismatch")
        local_captures.append(
            {
                "label": label,
                "timestamp_ns": int(capture["timestamp_ns"]),
                "rgb_path": str(rgb_path),
                "rgb_sha256": capture["rgb_sha256"],
                "depth_path": str(depth_path),
                "depth_sha256": capture["depth_sha256"],
                "finite_depth_samples": finite,
            }
        )

    final_capture = next(
        item
        for item in local_captures
        if item["label"] == "wrong_object_target_after_regrasp"
    )
    sample_dir = output_root / "task-success-rgbd"
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_rgb = sample_dir / "rgb.png"
    sample_depth = sample_dir / "depth.npy"
    shutil.copyfile(final_capture["rgb_path"], sample_rgb)
    shutil.copyfile(final_capture["depth_path"], sample_depth)
    sample_manifest = {
        "schema_version": "M2CTaskSuccessRGBDExampleV1",
        "task_success": True,
        "task_success_source": "M2BClosedLoopEpisodeV1.final_success",
        "raw_actuation_probe_task_success_field_present": "task_success" in evidence,
        "episode_id": episode.episode_id,
        "matched_key": episode.matched_key,
        "scene_seed": episode.scene_seed,
        "failure_type": episode.failure_type,
        "method": episode.method,
        "recovery_success": episode.recovery_success,
        "capture_label": final_capture["label"],
        "capture_timestamp_ns": final_capture["timestamp_ns"],
        "rgb": {"path": str(sample_rgb), "sha256": sha256_file(sample_rgb)},
        "depth": {
            "path": str(sample_depth),
            "sha256": sha256_file(sample_depth),
            "finite_depth_samples": final_capture["finite_depth_samples"],
            "semantics": public_rgbd["depth_semantics"],
        },
        "camera_frame": public_rgbd["camera_frame"],
        "camera_intrinsics": public_rgbd["camera_intrinsics"],
        "policy_input_simulator_truth": False,
        "teacher_used": False,
        "source_execution_evidence": {
            "host": host,
            "path": str(evidence_path),
            "sha256": journal["execution_evidence_sha256"],
        },
    }
    sample_manifest_path = sample_dir / "manifest.json"
    sample_manifest_path.write_text(
        json.dumps(sample_manifest, indent=2, sort_keys=True) + "\n"
    )

    with tempfile.TemporaryDirectory(prefix="m2c-wrong-object-") as temporary:
        frames = Path(temporary)
        first_timestamp = local_captures[0]["timestamp_ns"]
        for index, capture in enumerate(local_captures):
            elapsed = (capture["timestamp_ns"] - first_timestamp) / 1e9
            render_rgbd_frame(
                rgb_path=Path(capture["rgb_path"]),
                depth_path=Path(capture["depth_path"]),
                title="M2C S1 — M2B WRONG_OBJECT RECOVERY",
                subtitle="Sparse synchronized retained RGB-D evidence; not a continuous camera recording",
                lines=[
                    f"capture={capture['label']} | source timestamp_ns={capture['timestamp_ns']} | elapsed={elapsed:.3f}s",
                    f"stage={capture_stage(capture['label'])}",
                    "physical recovery sequence=SAFE_PLACE_NON_TARGET → REASSOCIATE_TARGET → REGRASP",
                    "all RGB/depth hashes and finite-depth counts verified against the frozen actuation evidence",
                ],
                output=frames / f"{index:06d}.png",
            )
        wrong_video = encode_video(
            frames,
            output_root / "m2c-s1-wrong-object-recovery.mp4",
            ffmpeg,
        )
    wrong_video.update(
        {
            "status": "PASS_SPARSE_SYNCHRONIZED_RGBD",
            "frames": len(local_captures),
            "source_timestamps_ns": [item["timestamp_ns"] for item in local_captures],
            "continuous_capture": False,
        }
    )

    decisions = episode.decisions
    capture_by_label = {item["label"]: item for item in local_captures}
    decision_capture_labels = [
        "after_recovery_retreat",
        "after_recovery_retreat",
        "wrong_object_target_after_regrasp",
    ]
    if len(decisions) != len(decision_capture_labels):
        raise ValueError("frozen M2B WRONG_OBJECT attribution expects exactly three decisions")
    with tempfile.TemporaryDirectory(prefix="m2c-attribution-") as temporary:
        frames = Path(temporary)
        for index, (decision, label) in enumerate(zip(decisions, decision_capture_labels)):
            capture = capture_by_label[label]
            owner = (
                "MODEL"
                if decision.execution_source == "MODEL_SELECTED_B0_SKILL"
                else "FIXED B0 CONTINUATION"
            )
            render_rgbd_frame(
                rgb_path=Path(capture["rgb_path"]),
                depth_path=Path(capture["depth_path"]),
                title="M2B ATTRIBUTION — SYSTEM SUCCESS, NOT PURE MODEL SUCCESS",
                subtitle=f"decision {index + 1}/{len(decisions)} | owner={owner}",
                lines=[
                    f"selected/executed skill={decision.selected_skill}/{decision.executed_skill}",
                    f"execution_source={decision.execution_source} | model_decision={decision.model_decision}",
                    f"mapping/IK/collision/safety={decision.mapping_status}/{decision.ik_gate}/{decision.collision_gate}/{decision.safety_gate}",
                    "final_task_success=true; pure_model_success_episode=false because B0 owns decisions 2–3",
                ],
                output=frames / f"{index:06d}.png",
            )
        attribution_video = encode_video(
            frames,
            output_root / "m2c-s1-m2b-attribution.mp4",
            ffmpeg,
        )
    attribution_video.update(
        {
            "status": "PASS_HONEST_ATTRIBUTION",
            "frames": len(decisions),
            "model_owned_decisions": sum(
                item.execution_source == "MODEL_SELECTED_B0_SKILL" for item in decisions
            ),
            "b0_continuation_decisions": sum(
                item.execution_source == "B0_BASELINE" for item in decisions
            ),
            "final_task_success": episode.final_success,
            "pure_model_success_episode": pure_model_success_episode(episode),
        }
    )

    return {
        "schema_version": "M2CS1DeliverablesV1",
        "evidence_status": "PASS",
        "episode_id": episode.episode_id,
        "task_success_rgbd": {
            **sample_manifest,
            "manifest_path": str(sample_manifest_path),
            "manifest_sha256": sha256_file(sample_manifest_path),
        },
        "wrong_object_recovery_video": wrong_video,
        "m2b_attribution_video": attribution_video,
        "synchronization": {
            "status": "PASS",
            "source": "M2BPublicRGBDEvidenceV2.capture.timestamp_ns",
            "captures": local_captures,
            "monotonic_timestamps": all(
                first["timestamp_ns"] < second["timestamp_ns"]
                for first, second in zip(local_captures, local_captures[1:])
            ),
        },
        "editing_policy": (
            "all retained public RGB-D captures are included in timestamp order; "
            "videos explicitly disclose sparse capture and B0 continuation"
        ),
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    task = report["task_report"]
    sample = report["task_success_rgbd"]
    wrong = report["wrong_object_recovery_video"]
    attribution = report["m2b_attribution_video"]
    lines = [
        "# M2C S1 submission deliverables",
        "",
        f"- status: **{report['status']}**",
        f"- source episode: `{report['episode_id']}`",
        f"- task-success RGB-D: `{sample['manifest_path']}`; task_success={sample['task_success']}",
        f"- RGB/depth SHA-256: `{sample['rgb']['sha256']}` / `{sample['depth']['sha256']}`",
        f"- WRONG_OBJECT video: `{wrong['path']}`; `{wrong['sha256']}`",
        f"- attribution video: `{attribution['path']}`; `{attribution['sha256']}`",
        f"- attribution: model={attribution['model_owned_decisions']}, fixed B0 continuation={attribution['b0_continuation_decisions']}",
        f"- final task success / pure model success: {attribution['final_task_success']} / {attribution['pure_model_success_episode']}",
        "- capture disclosure: sparse synchronized retained RGB-D evidence, not continuous camera recording",
        "- Teacher used: no; kill-rule events: none",
        "- privileged truth used as policy input: no",
        "",
        "## Task report",
        "",
        "- changed files:",
        *([f"  - `{item}`" for item in task["changed_files"]] or ["  - none"]),
        f"- tests: {task['tests']['passed']} passed, {task['tests']['failed']} failed",
        "- failures:",
        *([f"  - {item}" for item in task["failures"]] or ["  - none"]),
        "- blockers:",
        *([f"  - {item}" for item in task["blockers"]] or ["  - none"]),
        f"- next command: `{report['next_command']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--episodes",
        type=Path,
        default=PROJECT / "artifacts/m2b/closed-loop-20260731-episodes.jsonl",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=PROJECT / "artifacts/m2b/closed-loop-20260731-journal.jsonl",
    )
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/Users/gl/tzb-m2c-evidence/m2c-s1"),
    )
    parser.add_argument("--episode-id")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument(
        "--verification",
        type=Path,
        default=PROJECT / "reports/m2c-s1-verification.json",
    )
    parser.add_argument(
        "--checklist",
        type=Path,
        default=PROJECT / "docs/competition/submission-checklist.md",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT / "reports/m2c-s1-deliverables.json",
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=PROJECT / "reports/m2c-s1-deliverables.md",
    )
    args = parser.parse_args()
    if os.environ.get("M2B_EVIDENCE_READONLY") != "1":
        parser.error("M2B_EVIDENCE_READONLY=1 is required")
    report = export_evidence(
        episodes_path=args.episodes,
        journal_path=args.journal,
        host=args.host,
        output_root=args.output_root.resolve(),
        ffmpeg=args.ffmpeg,
        episode_id=args.episode_id,
    )
    verification = (
        json.loads(args.verification.read_text())
        if args.verification.is_file()
        else None
    )
    tests = verification.get("tests", {}) if verification else {}
    verification_passed = bool(
        verification
        and verification.get("status") == "PASS"
        and int(tests.get("passed", 0)) > 0
        and int(tests.get("failed", 1)) == 0
    )
    unchecked = [
        line.strip()
        for line in args.checklist.read_text().splitlines()
        if line.lstrip().startswith("- [ ]")
    ]
    blockers = []
    if not verification_passed:
        blockers.append("S1 full-suite verification is missing or failing")
    if unchecked:
        blockers.append(f"submission checklist still has unchecked required items: {unchecked}")
    report["status"] = "PASS" if not blockers else "PARTIAL"
    report["checklist"] = {
        "path": str(args.checklist.relative_to(PROJECT)),
        "unchecked_required_items": unchecked,
        "status": "PASS" if not unchecked else "FAIL",
    }
    generated = {
        str(args.report.resolve().relative_to(PROJECT.resolve())),
        str(args.report_md.resolve().relative_to(PROJECT.resolve())),
    }
    report["task_report"] = {
        "changed_files": changed_files(PROJECT, generated),
        "tests": {
            "passed": int(tests.get("passed", 0)),
            "failed": int(tests.get("failed", 0)) if verification else None,
        },
        "failures": verification.get("failures", []) if verification else [],
        "blockers": blockers,
    }
    report["next_command"] = "make m2c-s2" if not blockers else "make m2c-s1"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    write_markdown(args.report_md, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
