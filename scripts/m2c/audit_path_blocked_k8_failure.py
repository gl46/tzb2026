#!/usr/bin/env python3
"""Replay public RGB-D evidence to diagnose an ADR-0020 K=8 rejection.

This is an offline, public-only audit tool.  It consumes only the stage's
public RGB/depth capture manifest and the corresponding image files.  In
particular, it deliberately refuses semantic/instance inputs, Teacher fields,
and privileged-truth fields instead of trying to make an incomplete audit
pass.  The report binds every consumed file by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from xh_agent.data_engine.isaac.public_failure_predicates import (
    PublicTrackSnapshotV2,
    select_task_target_track,
    snapshots_from_perception_results,
)
from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1
from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v2 import (
    PUBLIC_TRACK_SLOT_COUNT,
    canonical_track_slots,
)


AUDIT_SCHEMA_VERSION = "M2CPathBlockedK8AuditV1"
AGGREGATE_SCHEMA_VERSION = "M2CPathBlockedK8AuditAggregateV1"
FROZEN_TRAINING_MANIFEST_SCHEMA = "M2CS4TrainingAndSmokeKeyManifestV1"
PUBLIC_TARGET_OUTSIDE_CANONICAL_K8 = "PUBLIC_TARGET_OUTSIDE_CANONICAL_K8"
FROZEN_MAXIMUM_ASSOCIATION_DISTANCE_M = 0.12
FROZEN_TARGET_SELECTOR_SUFFIX = ",top_z_band=0.02m,world_x=max"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_false(value: object, *, label: str) -> None:
    if value is not False:
        raise ValueError(f"{label} must be false for a public-only audit")


def _reject_forbidden_inputs(value: object, *, label: str) -> None:
    """Reject hidden inputs, including fields the replay does not understand."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key).lower()
            if "teacher" in key or "truth" in key:
                _require_false(item, label=f"{label}.{raw_key}")
            if "instance" in key or ("semantic" in key and key != "depth_semantics"):
                raise ValueError(f"{label} may not contain semantic or instance input {raw_key}")
            _reject_forbidden_inputs(item, label=f"{label}.{raw_key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_inputs(item, label=f"{label}[{index}]")


def _public_rgbd_record(metrics: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = [metrics[name] for name in ("m2b_public_rgbd", "public_rgbd") if name in metrics]
    if not candidates and metrics.get("schema_version") == "M2BPublicRGBDEvidenceV2":
        candidates = [metrics]
    if len(candidates) != 1 or not isinstance(candidates[0], Mapping):
        raise ValueError("stage metrics must contain exactly one public RGB-D record")
    return candidates[0]


def _load_partial_public_rgbd_record(
    partial_record: Path,
    *,
    stage_metrics: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Load a public-only record reconstructed after a fail-closed probe exit.

    The collection probe intentionally exits before writing its final evidence
    envelope when the step-6 target is outside K=8.  This diagnostic-only path
    accepts a manifest containing the already-saved public capture receipts and
    binds calibration to the stage's public policy-camera record.  It never
    changes the training packager's requirement for a complete probe envelope.
    """

    record = _load_json(partial_record, label="partial public RGB-D record")
    _reject_forbidden_inputs(record, label="partial public RGB-D record")
    if record.get("schema_version") != "M2CPartialPublicRGBDAuditInputV1":
        raise ValueError("partial public RGB-D record schema is not supported")
    if record.get("evidence_use") != "DIAGNOSTIC_ONLY_NOT_TRAINING_OR_EVALUATION":
        raise ValueError("partial public RGB-D record has invalid evidence use")
    for field in ("probe_console_sha256", "collection_job_sha256"):
        value = record.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"partial public RGB-D record lacks a valid {field}")
    identity = {
        "matched_key": str,
        "scene_seed": int,
        "failure_seed": int,
        "sdf_sha256": str,
        "supervision_sha256": str,
    }
    for field, expected_type in identity.items():
        if not isinstance(record.get(field), expected_type):
            raise ValueError(f"partial public RGB-D record lacks valid {field}")
    for field in ("sdf_sha256", "supervision_sha256"):
        if _SHA256.fullmatch(str(record[field])) is None:
            raise ValueError(f"partial public RGB-D record has invalid {field}")
    calibration = stage_metrics.get("policy_camera_calibration")
    if not isinstance(calibration, Mapping):
        raise ValueError("stage metrics lacks public policy-camera calibration")
    expected = {
        "camera_frame": "m2b_policy_rgbd_optical",
        "camera_intrinsics": calibration.get("camera_intrinsics"),
        "camera_to_world_optical": calibration.get("camera_to_world_optical"),
        "depth_semantics": calibration.get("depth_semantics"),
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise ValueError(f"partial public RGB-D {field} differs from stage calibration")
    return record


def _finite_numbers(value: object, *, length: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{label} must contain exactly {length} numeric values")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{label} may not contain NaN or Inf")
    return result


def _parse_target_color(task_spec: object) -> str:
    if not isinstance(task_spec, Mapping):
        raise ValueError("public task_spec is required")
    if task_spec.get("source") != "PUBLIC_RGBD_TASK_SPEC":
        raise ValueError("task_spec must be sourced from public RGB-D")
    if task_spec.get("simulator_entity_id_used") is not False:
        raise ValueError("task_spec may not use a simulator entity ID")
    selector = task_spec.get("target_selector")
    if not isinstance(selector, str) or not selector.endswith(FROZEN_TARGET_SELECTOR_SUFFIX):
        raise ValueError("task_spec does not use the frozen public target selector")
    prefix = selector.removesuffix(FROZEN_TARGET_SELECTOR_SUFFIX)
    if not prefix.startswith("visual_color="):
        raise ValueError("frozen public selector lacks a visual color")
    color = prefix.removeprefix("visual_color=")
    if not color or "," in color:
        raise ValueError("frozen public selector visual color is invalid")
    return color


def _safe_dataset_relative(uri: object, *, label: str) -> Path:
    if not isinstance(uri, str) or not uri.startswith("dataset://"):
        raise ValueError(f"{label} must be a dataset:// URI")
    raw = uri.removeprefix("dataset://")
    relative = Path(raw)
    if (
        not raw
        or raw.startswith("/")
        or "\\" in raw
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(f"{label} escapes capture root")
    return relative


def _resolve_capture_asset(capture_root: Path, uri: object, *, label: str) -> Path:
    relative = _safe_dataset_relative(uri, label=label)
    candidates = [capture_root / relative]
    if relative.parts and relative.parts[0] == "m2b_public_rgbd":
        candidates.append(capture_root / Path(*relative.parts[1:]))
    existing = [path for path in candidates if path.is_file() and not path.is_symlink()]
    if len(existing) != 1:
        raise ValueError(f"{label} must resolve to exactly one regular capture file")
    resolved = existing[0].resolve()
    root = capture_root.resolve()
    if root not in resolved.parents:
        raise ValueError(f"{label} escapes capture root")
    if any(token in {"semantic", "semantics", "instance", "instances"} for token in resolved.parts):
        raise ValueError(f"{label} may not use semantic or instance assets")
    return resolved


def _verify_expected_sha(path: Path, expected: object, *, label: str) -> str:
    if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
        raise ValueError(f"{label} SHA-256 is invalid")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch")
    return actual


def _public_track(track: PublicTrackSnapshotV2) -> PerceptionTrackV1:
    color = track.visual_color or "unknown"
    return PerceptionTrackV1(
        track_id=track.track_id,
        category=f"{track.category}:{color}",
        confidence=track.confidence,
        pose_xyzquat=[*track.position_world_m, 1.0, 0.0, 0.0, 0.0],
    )


def _track_report(track: PublicTrackSnapshotV2) -> dict[str, object]:
    return {
        "track_id": track.track_id,
        "category": track.category,
        "visual_color": track.visual_color,
        "position_world_m": track.position_world_m,
        "confidence": track.confidence,
    }


def _target_membership(
    target: PublicTrackSnapshotV2,
    tracks: Sequence[PublicTrackSnapshotV2],
    slot_ids: Sequence[str | None],
) -> dict[str, object]:
    # No confidence filter occurs before ranking or canonicalization.
    ordered_ids = sorted(track.track_id for track in tracks)
    rank = ordered_ids.index(target.track_id) + 1
    slot_index = next(
        (index for index, track_id in enumerate(slot_ids) if track_id == target.track_id),
        None,
    )
    return {
        "target_track_id": target.track_id,
        "target_confidence": target.confidence,
        "public_track_count": len(tracks),
        "target_rank_by_literal_track_id": rank,
        "canonical_slot_index": slot_index,
        "reason": (None if slot_index is not None else PUBLIC_TARGET_OUTSIDE_CANONICAL_K8),
    }


def _reassociate_without_confidence_filter(
    before: Sequence[PublicTrackSnapshotV2],
    after: Sequence[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
) -> PublicTrackSnapshotV2:
    """Reassociate with public color/geometry only; retain low-confidence tracks."""

    original = [track for track in before if track.track_id == task_target_track_id]
    if len(original) != 1:
        raise ValueError("initial public task target is not unique")
    exact = [track for track in after if track.track_id == task_target_track_id]
    if len(exact) == 1:
        return exact[0]
    candidates = [track for track in after if track.visual_color == original[0].visual_color]
    if not candidates:
        raise ValueError("public task target could not be reassociated")
    result = min(
        candidates,
        key=lambda track: math.dist(track.position_world_m, original[0].position_world_m),
    )
    if math.dist(result.position_world_m, original[0].position_world_m) > 0.08:
        raise ValueError("public task target reassociation exceeded distance gate")
    return result


def audit_attempt(
    stage_metrics: Path,
    capture_root: Path,
    *,
    partial_public_rgbd_record: Path | None = None,
) -> dict[str, object]:
    """Replay one attempt in capture-manifest order and return public evidence."""

    metrics = _load_json(stage_metrics, label="stage metrics")
    public_rgbd = (
        _load_partial_public_rgbd_record(
            partial_public_rgbd_record,
            stage_metrics=metrics,
        )
        if partial_public_rgbd_record is not None
        else _public_rgbd_record(metrics)
    )
    _reject_forbidden_inputs(public_rgbd, label="public RGB-D record")
    allowed_public_schemas = {"M2BPublicRGBDEvidenceV2"}
    if partial_public_rgbd_record is not None:
        allowed_public_schemas.add("M2CPartialPublicRGBDAuditInputV1")
    if public_rgbd.get("schema_version") not in allowed_public_schemas:
        raise ValueError("public RGB-D record schema is not a supported frozen audit input")
    _require_false(
        public_rgbd.get("simulator_truth_policy_input"),
        label="public RGB-D record simulator_truth_policy_input",
    )
    if public_rgbd.get("camera_frame") != "m2b_policy_rgbd_optical":
        raise ValueError("public RGB-D camera frame is not the frozen policy frame")
    if public_rgbd.get("depth_semantics") != "METRIC_DISTANCE_TO_IMAGE_PLANE":
        raise ValueError("public RGB-D depth semantics are not metric image-plane distance")
    intrinsics = _finite_numbers(
        public_rgbd.get("camera_intrinsics"), length=9, label="camera intrinsics"
    )
    camera_to_world = _finite_numbers(
        public_rgbd.get("camera_to_world_optical"),
        length=16,
        label="public camera-to-world calibration",
    )
    target_color = _parse_target_color(public_rgbd.get("task_spec"))
    captures = public_rgbd.get("captures")
    if not isinstance(captures, list) or len(captures) < 2:
        raise ValueError("public RGB-D record requires at least two ordered captures")
    if not capture_root.is_dir() or capture_root.is_symlink():
        raise ValueError("capture root must be a regular directory")

    baseline = GeometricRGBDBaseline(
        maximum_association_distance_m=FROZEN_MAXIMUM_ASSOCIATION_DISTANCE_M
    )
    frames: list[dict[str, object]] = []
    snapshots_by_label: dict[str, list[PublicTrackSnapshotV2]] = {}
    prior_timestamp = -1
    for index, raw_capture in enumerate(captures):
        if not isinstance(raw_capture, Mapping):
            raise ValueError(f"capture {index} must be an object")
        _reject_forbidden_inputs(raw_capture, label=f"capture {index}")
        label = raw_capture.get("label")
        timestamp = raw_capture.get("timestamp_ns")
        if not isinstance(label, str) or not label:
            raise ValueError(f"capture {index} lacks a label")
        if label in snapshots_by_label:
            raise ValueError(f"capture label is duplicated: {label}")
        if not isinstance(timestamp, int) or timestamp < 0 or timestamp <= prior_timestamp:
            raise ValueError("capture timestamps must be strictly increasing in saved order")
        prior_timestamp = timestamp
        if raw_capture.get("source") != "PUBLIC_RGBD":
            raise ValueError(f"capture {label} is not public RGB-D")
        rgb_path = _resolve_capture_asset(capture_root, raw_capture.get("rgb_uri"), label="RGB URI")
        depth_path = _resolve_capture_asset(
            capture_root, raw_capture.get("depth_uri"), label="depth URI"
        )
        rgb_sha = _verify_expected_sha(rgb_path, raw_capture.get("rgb_sha256"), label="RGB")
        depth_sha = _verify_expected_sha(depth_path, raw_capture.get("depth_sha256"), label="depth")
        try:
            rgb = np.asarray(Image.open(rgb_path).convert("RGB"), dtype=np.uint8)
            depth = np.load(depth_path, allow_pickle=False)
        except (OSError, ValueError) as error:
            raise ValueError(f"capture {label} public RGB-D cannot be loaded") from error
        if depth.dtype.kind not in {"f"}:
            raise ValueError(f"capture {label} depth must be a floating metric array")
        results = baseline.infer(
            PerceptionInputV1(
                frame_id="m2b_policy_rgbd_optical",
                timestamp_ns=timestamp,
                rgb_uri=str(raw_capture["rgb_uri"]),
                depth_uri=str(raw_capture["depth_uri"]),
                camera_intrinsics=intrinsics,
                camera_frame="m2b_policy_rgbd_optical",
            ),
            depth,
            rgb,
        )
        snapshots = snapshots_from_perception_results(results, camera_to_world)
        slots = canonical_track_slots([_public_track(track) for track in snapshots])
        snapshots_by_label[label] = snapshots
        frames.append(
            {
                "frame_index": index,
                "label": label,
                "timestamp_ns": timestamp,
                "rgb_sha256": rgb_sha,
                "depth_sha256": depth_sha,
                "public_tracks": [_track_report(track) for track in snapshots],
                "canonical_k8_slots": list(slots.track_ids),
            }
        )

    initial_label = "before_failure_identity_binding"
    reassociation_label = "m2c_step_06_reassociate_target"
    if initial_label not in snapshots_by_label or reassociation_label not in snapshots_by_label:
        raise ValueError("captures must include initial binding and step-6 reassociation frames")
    initial_tracks = snapshots_by_label[initial_label]
    initial_target = select_task_target_track(
        initial_tracks,
        visual_color=target_color,
        world_axis="x",
        extremum="max",
        maximum_height_below_tallest_m=0.02,
    )
    initial_frame = next(frame for frame in frames if frame["label"] == initial_label)
    step6_tracks = snapshots_by_label[reassociation_label]
    step6_target = _reassociate_without_confidence_filter(
        initial_tracks,
        step6_tracks,
        task_target_track_id=initial_target.track_id,
    )
    step6_frame = next(frame for frame in frames if frame["label"] == reassociation_label)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "evidence_use": "DIAGNOSTIC_ONLY_NOT_TRAINING_OR_EVALUATION",
        "attempt_identity": (
            {
                field: public_rgbd[field]
                for field in (
                    "matched_key",
                    "scene_seed",
                    "failure_seed",
                    "sdf_sha256",
                    "supervision_sha256",
                )
            }
            if partial_public_rgbd_record is not None
            else None
        ),
        "stage_metrics_sha256": sha256_file(stage_metrics),
        "partial_public_rgbd_record_sha256": (
            sha256_file(partial_public_rgbd_record)
            if partial_public_rgbd_record is not None
            else None
        ),
        "partial_failure_evidence_sha256": (
            {
                "probe_console": public_rgbd["probe_console_sha256"],
                "collection_job": public_rgbd["collection_job_sha256"],
            }
            if partial_public_rgbd_record is not None
            else None
        ),
        "frozen_baseline": {
            "name": "GeometricRGBDBaseline",
            "maximum_association_distance_m": FROZEN_MAXIMUM_ASSOCIATION_DISTANCE_M,
            "confidence_filter_applied": False,
            "canonical_slot_count": PUBLIC_TRACK_SLOT_COUNT,
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "input_file_sha256": {
            "stage_metrics": sha256_file(stage_metrics),
            "frames": [
                {
                    "frame_index": frame["frame_index"],
                    "label": frame["label"],
                    "rgb_sha256": frame["rgb_sha256"],
                    "depth_sha256": frame["depth_sha256"],
                }
                for frame in frames
            ],
        },
        "frames": frames,
        "initial_public_task_selector": {
            "visual_color": target_color,
            **_target_membership(
                initial_target,
                initial_tracks,
                initial_frame["canonical_k8_slots"],
            ),
        },
        "step6_public_reassociation": _target_membership(
            step6_target,
            step6_tracks,
            step6_frame["canonical_k8_slots"],
        ),
    }


def _attempt_paths(root: Path) -> tuple[Path, Path, Path | None]:
    metrics = root / "stage" / "metrics.json"
    if not metrics.is_file():
        metrics = root / "metrics.json"
    if not metrics.is_file():
        raise ValueError(f"attempt root has no stage metrics: {root}")
    for candidate in (root / "m2b_public_rgbd", root / "captures", root):
        if candidate.is_dir() and not candidate.is_symlink():
            partial_record = root / "partial-public-rgbd.json"
            return metrics, candidate, partial_record if partial_record.is_file() else None
    raise ValueError(f"attempt root has no public capture root: {root}")


def _write_new_json(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _validate_aggregate_against_frozen_training_manifest(
    attempts: Sequence[Mapping[str, Any]],
    manifest_path: Path,
) -> dict[str, object]:
    manifest = _load_json(manifest_path, label="frozen S4 training manifest")
    _reject_forbidden_inputs(manifest, label="frozen S4 training manifest")
    if manifest.get("schema_version") != FROZEN_TRAINING_MANIFEST_SCHEMA:
        raise ValueError("frozen S4 training manifest schema is not supported")
    if manifest.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION":
        raise ValueError("S4 training keys were not frozen before collection")
    embedded = manifest.get("manifest_sha256")
    without_digest = dict(manifest)
    without_digest.pop("manifest_sha256", None)
    actual_content = hashlib.sha256(
        json.dumps(without_digest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if embedded != actual_content:
        raise ValueError("frozen S4 training manifest content digest mismatch")
    training = manifest.get("training_keys")
    if not isinstance(training, list) or len(training) != 36:
        raise ValueError("frozen S4 training manifest must contain exactly 36 keys")
    records: dict[str, Mapping[str, Any]] = {}
    sdf_counts: dict[str, int] = {}
    for raw_record in training:
        if not isinstance(raw_record, Mapping):
            raise ValueError("frozen S4 training key is not an object")
        key = raw_record.get("matched_key")
        sdf_sha = raw_record.get("sdf_sha256")
        if not isinstance(key, str) or key in records:
            raise ValueError("frozen S4 training matched keys are invalid or duplicated")
        if not isinstance(sdf_sha, str) or _SHA256.fullmatch(sdf_sha) is None:
            raise ValueError("frozen S4 training SDF digest is invalid")
        records[key] = raw_record
        sdf_counts[sdf_sha] = sdf_counts.get(sdf_sha, 0) + 1
    if sorted(sdf_counts.values()) != [12, 12, 12]:
        raise ValueError("frozen S4 manifest is not three SDF layouts with 12 keys each")

    audited_sdfs: set[str] = set()
    audited_keys: set[str] = set()
    for attempt in attempts:
        identity = attempt.get("attempt_identity")
        if not isinstance(identity, Mapping):
            raise ValueError("aggregate attempt lacks a hash-bound frozen identity")
        key = identity.get("matched_key")
        if not isinstance(key, str) or key not in records or key in audited_keys:
            raise ValueError("aggregate attempt key is absent, non-TRAIN, or duplicated")
        record = records[key]
        for field in (
            "matched_key",
            "scene_seed",
            "failure_seed",
            "sdf_sha256",
            "supervision_sha256",
        ):
            if identity.get(field) != record.get(field):
                raise ValueError(f"aggregate attempt {field} differs from frozen TRAIN key")
        audited_keys.add(key)
        audited_sdfs.add(str(identity["sdf_sha256"]))
    if len(attempts) != 3 or audited_sdfs != set(sdf_counts):
        raise ValueError("aggregate must audit one distinct frozen TRAIN key per SDF layout")
    return {
        "path": str(manifest_path),
        "file_sha256": sha256_file(manifest_path),
        "content_sha256": embedded,
        "training_keys_total": len(training),
        "unique_sdf_layouts_total": len(sdf_counts),
        "keys_per_sdf_layout": sorted(sdf_counts.values()),
        "audited_training_keys": len(audited_keys),
        "audited_unique_sdf_layouts": len(audited_sdfs),
        "coverage_semantics": (
            "one observed TRAIN key per each frozen byte-identical SDF layout; "
            "3/36 key identities physically observed"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-metrics", type=Path)
    parser.add_argument("--capture-root", type=Path)
    parser.add_argument("--partial-public-rgbd-record", type=Path)
    parser.add_argument("--attempt-root", action="append", type=Path, default=[])
    parser.add_argument("--training-keys", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.attempt_root:
        if (
            args.stage_metrics is not None
            or args.capture_root is not None
            or args.partial_public_rgbd_record is not None
        ):
            raise ValueError("--attempt-root cannot be combined with single-attempt inputs")
        if len(args.attempt_root) > 3:
            raise ValueError("at most three attempt roots may be aggregated")
        attempts = []
        for root in args.attempt_root:
            metrics, captures, partial = _attempt_paths(root)
            attempts.append(
                audit_attempt(
                    metrics,
                    captures,
                    partial_public_rgbd_record=partial,
                )
            )
        if args.training_keys is None:
            raise ValueError("aggregate audit requires --training-keys")
        manifest_binding = _validate_aggregate_against_frozen_training_manifest(
            attempts,
            args.training_keys,
        )
        result: object = {
            "schema_version": AGGREGATE_SCHEMA_VERSION,
            "status": (
                "BLOCKED_PUBLIC_INPUT_ADMISSIBILITY"
                if all(
                    attempt["step6_public_reassociation"]["reason"]
                    == PUBLIC_TARGET_OUTSIDE_CANONICAL_K8
                    for attempt in attempts
                )
                else "MIXED_PUBLIC_INPUT_ADMISSIBILITY"
            ),
            "finding": (
                "all audited unique TRAIN geometries reached step 6 with the public "
                "task target visible but outside the frozen literal-ID canonical K=8"
            ),
            "attempts_audited": len(attempts),
            "frozen_training_manifest": manifest_binding,
            "training_samples_packaged": 0,
            "training_samples_eligible": 0,
            "training_executed": False,
            "q_b_evaluation_executed": False,
            "pure_model_success_episodes": None,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "attempts": attempts,
        }
    else:
        if args.training_keys is not None:
            raise ValueError("--training-keys is only valid with --attempt-root")
        if args.stage_metrics is None or args.capture_root is None:
            raise ValueError("single-attempt audit requires --stage-metrics and --capture-root")
        result = audit_attempt(
            args.stage_metrics,
            args.capture_root,
            partial_public_rgbd_record=args.partial_public_rgbd_record,
        )
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite audit output: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_new_json(args.output, result)


if __name__ == "__main__":
    main()
