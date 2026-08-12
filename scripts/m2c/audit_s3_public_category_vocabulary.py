#!/usr/bin/env python3
"""Audit ADR-0021's one-time public ``category`` vocabulary prerequisite.

The auditor is deliberately offline and read-only.  A caller supplies a
manifest of already-existing S3 JSON/JSONL evidence files and their SHA-256
digests.  Each file is read once through a non-following descriptor; the exact
bytes that were hashed are the bytes that are parsed.  Only public TaskSpec
attribute words and public perception-track fields are inspected.

This tool replays the official public adapter's exact
``category + ':' + visual_color`` projection into ``PerceptionTrackV1``.  It
never consumes a TaskSpec target track identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Iterable, Mapping


AUDIT_SCHEMA_VERSION = "M2CS3PublicCategoryVocabularyAuditV1"
MANIFEST_SCHEMA_VERSION = "M2CS3PublicCategoryVocabularyInputManifestV1"
ADR_PATH = "docs/decisions/ADR-0021-m2c-public-semantic-candidate-contract.md"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TRACK_ID_PATTERN = re.compile(r"^track-[A-Za-z0-9_-]+$")
TARGET_SELECTOR_PATTERN = re.compile(
    r"(?:^|,)visual_(?:color|class)=([^,]+)(?:,|$)",
    flags=re.IGNORECASE,
)
ALLOWED_TASK_SPEC_FIELDS = {
    "instruction",
    "source",
    "target_selector",
    "simulator_entity_id_used",
    # Present in historical S3, but deliberately never read by this audit.
    "target_track_id",
    "injected_action_track_id",
}
ALLOWED_TRACK_FIELDS = {
    "schema_version",
    "track_id",
    "category",
    "confidence",
    "pose_xyzquat",
    "position_world_m",
    "crop_uri",
    "visual_color",
}
ALLOWED_TRACK_SCHEMAS = {"PublicTrackSnapshotV2", "PerceptionTrackV1", None}
OFFICIAL_COARSE_ADAPTER_PATH = "scripts/m2b/build_coarse_training_v2.py"
FORBIDDEN_KEY_TOKENS = (
    "teacher",
    "truth",
    "semantic",
    "instance",
    "entity",
    "prim",
    "evaluator",
    "injected_failure",
    "task_success",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    """Read exact stable bytes without following symlinks or path reopening."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"audit input is not a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        data = b"".join(chunks)
        if identity_before != identity_after or len(data) != before.st_size:
            raise ValueError(f"audit input changed while being read: {path}")
        return data
    finally:
        os.close(descriptor)


def _json_object(data: bytes, *, label: str) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be one JSON object")
    return value


def _safe_evidence_path(project_root: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError("manifest evidence path must be non-empty")
    path = Path(raw)
    path = path if path.is_absolute() else project_root / path
    if path.is_symlink():
        raise ValueError(f"manifest evidence path may not be a symlink: {raw}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"manifest evidence path is absent: {raw}")
    return resolved


def _validate_manifest(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    expected = {
        "schema_version",
        "evidence_files",
        "teacher_used",
        "privileged_truth_policy_input",
    }
    if set(payload) != expected:
        raise ValueError("input manifest fields differ from the exact audit schema")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("input manifest schema is unsupported")
    if payload.get("teacher_used") is not False:
        raise ValueError("input manifest is not explicitly Teacher-free")
    if payload.get("privileged_truth_policy_input") is not False:
        raise ValueError("input manifest used privileged truth as policy input")
    files = payload.get("evidence_files")
    if not isinstance(files, list) or not files:
        raise ValueError("input manifest has no S3 evidence files")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(files):
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
            raise ValueError(f"manifest evidence binding {index} is malformed")
        if not isinstance(item.get("sha256"), str) or SHA256_PATTERN.fullmatch(
            str(item["sha256"])
        ) is None:
            raise ValueError(f"manifest evidence binding {index} has invalid SHA-256")
        result.append(item)
    return result


def _parse_evidence_rows(data: bytes, *, path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        if not data.endswith(b"\n"):
            raise ValueError(f"S3 JSONL is not newline terminated: {path}")
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(data.splitlines(), 1):
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"S3 JSONL row is not an object: {path}:{line_number}")
            rows.append(value)
        if not rows:
            raise ValueError(f"S3 JSONL has no records: {path}")
        return rows
    return [_json_object(data, label=f"S3 evidence {path}")]


def _task_spec(payload: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    task = payload.get("task_spec")
    if not isinstance(task, Mapping):
        public = payload.get("m2b_public_rgbd")
        task = public.get("task_spec") if isinstance(public, Mapping) else None
    if not isinstance(task, Mapping):
        raise ValueError(f"{label} lacks a public TaskSpec")
    extra = set(task) - ALLOWED_TASK_SPEC_FIELDS
    if extra:
        raise ValueError(f"{label} TaskSpec contains non-public audit fields: {sorted(extra)}")
    public_task = {key: task.get(key) for key in ALLOWED_TASK_SPEC_FIELDS if "track_id" not in key}
    if public_task.get("source") != "PUBLIC_RGBD_TASK_SPEC":
        raise ValueError(f"{label} TaskSpec is not sourced from public RGB-D")
    if public_task.get("simulator_entity_id_used") is not False:
        raise ValueError(f"{label} TaskSpec used simulator entity identity")
    return public_task


def _declared_attribute(task: Mapping[str, Any], *, label: str) -> str:
    selector = task.get("target_selector")
    if not isinstance(selector, str):
        raise ValueError(f"{label} TaskSpec lacks a public target selector")
    match = TARGET_SELECTOR_PATTERN.search(selector)
    if match is None:
        raise ValueError(f"{label} TaskSpec selector lacks a declared color/class attribute")
    token = match.group(1).strip().casefold()
    if not token or not re.fullmatch(r"[a-z0-9_-]+", token):
        raise ValueError(f"{label} TaskSpec declared attribute token is invalid")
    return token


def _observation_tracks(payload: object, *, label: str) -> list[tuple[str, list[object]]]:
    found: list[tuple[str, list[object]]] = []

    def visit(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                key = str(raw_key)
                next_path = f"{path}.{key}"
                if key in {"perception_tracks", "tracks"}:
                    if not isinstance(child, list):
                        raise ValueError(f"{label}{next_path} is not a track list")
                    found.append((next_path, child))
                else:
                    visit(child, next_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    for key in (
        "observation_before",
        "observation_after",
        "recovery_observations",
        "m2c_path_blocked_physical_chain",
    ):
        if key in payload:
            visit(payload[key], f"$.{key}")
    if not found:
        raise ValueError(f"{label} has no public perception-track observation")
    return found


def _forbidden_track_keys(track: Mapping[str, Any], *, label: str) -> None:
    extra = set(track) - ALLOWED_TRACK_FIELDS
    forbidden = [
        key
        for key in extra
        if any(token in str(key).casefold() for token in FORBIDDEN_KEY_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"{label} contains forbidden Teacher/truth/identity fields: {forbidden}")


def _finite_pose(track: Mapping[str, Any], *, label: str) -> None:
    pose = track.get("pose_xyzquat")
    if pose is None:
        position = track.get("position_world_m")
        if not isinstance(position, list) or len(position) != 3:
            raise ValueError(f"{label} is missing public pose")
        pose = position
    if not isinstance(pose, list) or len(pose) not in {3, 7}:
        raise ValueError(f"{label} has invalid public pose")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in pose):
        raise ValueError(f"{label} public pose is not numeric")
    if not all(math.isfinite(float(item)) for item in pose):
        raise ValueError(f"{label} public pose contains NaN or Inf")


def _project_perception_category(track: Mapping[str, Any], *, label: str) -> str:
    """Replay ``build_coarse_training_v2.coarse_sample`` public projection."""

    category = track.get("category")
    if not isinstance(category, str) or not category.strip():
        raise ValueError(f"{label} is missing category")
    if "visual_color" in track:
        visual_color = track.get("visual_color")
        if not isinstance(visual_color, str) or not visual_color.strip():
            raise ValueError(f"{label} is missing visual_color for public adapter projection")
        return f"{category}:{visual_color}"
    # PathBlockedPublicObservationV2 is already the official projected
    # PerceptionTrackV1 representation.
    if track.get("schema_version") in {None, "PerceptionTrackV1"}:
        return category
    raise ValueError(f"{label} lacks visual_color needed by the official public adapter")


def _verify_official_adapter(root: Path) -> tuple[str, str]:
    """Bind the audit to the committed adapter source whose projection it replays."""

    path = root / OFFICIAL_COARSE_ADAPTER_PATH
    data = read_regular_file_once(path)
    completed = subprocess.run(
        ["git", "-C", str(root), "show", f"HEAD:{OFFICIAL_COARSE_ADAPTER_PATH}"],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or completed.stdout != data:
        raise ValueError("official public adapter is absent from or differs from Git HEAD")
    required_source = (
        b'f"{track[\'category\']}:{track[\'visual_color\']}"'
        b"\n                if track.get(\"visual_color\")"
    )
    if required_source not in data:
        raise ValueError("official public adapter category projection changed")
    return OFFICIAL_COARSE_ADAPTER_PATH, sha256_bytes(data)


def _audit_track_list(
    tracks: Iterable[object],
    *,
    attribute: str,
    label: str,
) -> tuple[int, int]:
    count = 0
    matches = 0
    seen_ids: set[str] = set()
    for index, raw in enumerate(tracks):
        track_label = f"{label}[{index}]"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{track_label} is not an object")
        _forbidden_track_keys(raw, label=track_label)
        if raw.get("schema_version") not in ALLOWED_TRACK_SCHEMAS:
            raise ValueError(f"{track_label} has unsupported public track schema")
        track_id = raw.get("track_id")
        if not isinstance(track_id, str) or TRACK_ID_PATTERN.fullmatch(track_id) is None:
            raise ValueError(f"{track_label} has invalid public opaque track_id")
        if track_id in seen_ids:
            raise ValueError(f"{label} repeats public track_id {track_id}")
        seen_ids.add(track_id)
        category = _project_perception_category(raw, label=track_label)
        confidence = raw.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError(f"{track_label} has invalid confidence")
        _finite_pose(raw, label=track_label)
        count += 1
        if attribute in category.casefold():
            matches += 1
    if count == 0:
        raise ValueError(f"{label} is empty")
    return count, matches


def audit_manifest(project_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Replay every byte-bound S3 evidence file and return one audit report."""

    root = project_root.resolve()
    adapter_path, adapter_sha256 = _verify_official_adapter(root)
    manifest_bytes = read_regular_file_once(manifest_path)
    bindings = _validate_manifest(_json_object(manifest_bytes, label="input manifest"))
    seen_paths: set[Path] = set()
    seen_digests: set[str] = set()
    files_report: list[dict[str, Any]] = []
    records_audited = 0
    observations_audited = 0
    tracks_audited = 0
    category_attribute_matches = 0
    attributes: set[str] = set()
    for binding in bindings:
        evidence_path = _safe_evidence_path(root, binding["path"])
        if evidence_path in seen_paths:
            raise ValueError("input manifest repeats an evidence path")
        seen_paths.add(evidence_path)
        evidence_bytes = read_regular_file_once(evidence_path)
        digest = sha256_bytes(evidence_bytes)
        if digest != binding["sha256"]:
            raise ValueError(f"S3 evidence SHA-256 mismatch: {binding['path']}")
        if digest in seen_digests:
            raise ValueError("input manifest repeats identical S3 evidence bytes")
        seen_digests.add(digest)
        rows = _parse_evidence_rows(evidence_bytes, path=evidence_path)
        file_observations = 0
        file_tracks = 0
        file_matches = 0
        for row_index, row in enumerate(rows):
            label = f"{evidence_path}:record[{row_index}]"
            if row.get("teacher_used") is not False or row.get("teacher_response") is not None:
                raise ValueError(f"{label} is not explicitly Teacher-free")
            if row.get("policy_input_simulator_truth") is not False:
                raise ValueError(f"{label} used privileged simulator truth")
            task = _task_spec(row, label=label)
            attribute = _declared_attribute(task, label=label)
            attributes.add(attribute)
            observations = _observation_tracks(row, label=label)
            record_matches = 0
            for track_path, tracks in observations:
                count, matches = _audit_track_list(
                    tracks,
                    attribute=attribute,
                    label=f"{label}{track_path}",
                )
                file_observations += 1
                file_tracks += count
                file_matches += matches
                record_matches += matches
            if record_matches == 0:
                raise ValueError(
                    f"{label} projected PerceptionTrackV1.category vocabulary "
                    f"does not carry declared attribute {attribute!r}"
                )
            records_audited += 1
        observations_audited += file_observations
        tracks_audited += file_tracks
        category_attribute_matches += file_matches
        files_report.append(
            {
                "path": str(binding["path"]),
                "sha256": digest,
                "size_bytes": len(evidence_bytes),
                "records_audited": len(rows),
                "observations_audited": file_observations,
                "tracks_audited": file_tracks,
                "category_attribute_matches": file_matches,
            }
        )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "PASS_CATEGORY_CARRIES_DECLARED_ATTRIBUTE_VOCABULARY",
        "adr_path": ADR_PATH,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "evidence_files_verified": len(files_report),
        "records_audited": records_audited,
        "observations_audited": observations_audited,
        "tracks_audited": tracks_audited,
        "category_attribute_matches": category_attribute_matches,
        "declared_attributes": sorted(attributes),
        "files": files_report,
        "task_spec_target_track_id_read": False,
        "visual_color_promoted_as_standalone_category": False,
        "public_adapter_projection": (
            "PublicTrackSnapshotV2.category + ':' + visual_color -> "
            "PerceptionTrackV1.category"
        ),
        "public_adapter_path": adapter_path,
        "public_adapter_sha256": adapter_sha256,
        "raw_category_and_visual_color_remain_distinct": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "collection_or_training_executed": False,
    }


def write_report_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o644)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("failed to write category-vocabulary audit report")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit_manifest(args.project_root, args.manifest)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        report = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "status": "BLOCKED_CATEGORY_VOCABULARY_PREREQUISITE",
            "blocker": f"{type(error).__name__}: {error}",
            "task_spec_target_track_id_read": False,
            "visual_color_promoted_as_standalone_category": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "collection_or_training_executed": False,
        }
        write_report_create_only(args.output, report)
        return 2
    write_report_create_only(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
