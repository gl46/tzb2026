#!/usr/bin/env python3
"""Build Teacher-free Student transitions from an Isaac M1B RGB-D capture.

The capture intentionally stores policy-visible runtime frames and simulator
supervision in different JSONL files.  This offline join runs public RGB-D
perception first, validates both contracts, and emits ``EpisodeTransitionV0``
without ever placing simulator entity truth in an ``ObservationV0``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from xh_agent.data.isaac_m1b_episode import (
    IsaacM1BRuntimeFrameV1,
    IsaacM1BSupervisionFrameV1,
    build_transition,
    observation_from_runtime_frame,
)
from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1, PerceptionResultV1
from xh_agent.runtime.m1b_center_correction import (
    M1BPublicGeometryXYCorrectionV1,
    M1BTableSupportedCylinderCenterV1,
)


OFFICIAL_ROBOT = "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_capture_metrics(
    dataset_root: Path,
    *,
    runtime_path: Path,
    supervision_path: Path,
) -> dict[str, object]:
    metrics_path = dataset_root / "metrics.json"
    if not metrics_path.is_file():
        raise FileNotFoundError(metrics_path)
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    expected_capture_source = _sha256(
        Path(__file__).with_name("isaac_m1b_dataset_benchmark.py")
    )
    robot_asset = payload.get("robot_asset")
    protocol = payload.get("student_dataset_protocol")
    capture_mode = payload.get("capture_mode")
    expected_training_eligible = capture_mode == "DYNAMIC_STUDENT_DATASET"
    if (
        payload.get("status") != "PASS"
        or capture_mode
        not in {
            "DYNAMIC_STUDENT_DATASET",
            "CALIBRATION_ONLY_STATIC_PERCEPTION",
        }
        or payload.get("dataset_benchmark_source_sha256")
        != expected_capture_source
        or not isinstance(robot_asset, dict)
        or robot_asset.get("provenance") != OFFICIAL_ROBOT
        or robot_asset.get("local_simplified_robot_used") is not False
        or robot_asset.get("variants")
        != {"Gripper": "Default", "Mesh": "Performance"}
        or not isinstance(protocol, dict)
        or protocol.get("runtime_frames_sha256") != _sha256(runtime_path)
        or protocol.get("supervision_frames_sha256")
        != _sha256(supervision_path)
        or protocol.get("streams_physically_separate") is not True
        or protocol.get("policy_segmentation_input") is not False
        or protocol.get("teacher_required") is not False
        or protocol.get("training_eligible")
        is not expected_training_eligible
    ):
        raise ValueError(
            "capture metrics do not prove an official, hash-bound, "
            "Teacher-free M1B dataset"
        )
    return payload


def _read_jsonl(path: Path, model: type[IsaacM1BRuntimeFrameV1] | type[IsaacM1BSupervisionFrameV1]) -> list[IsaacM1BRuntimeFrameV1] | list[IsaacM1BSupervisionFrameV1]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                records.append(model.model_validate_json(line))
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    if not records:
        raise ValueError(f"{path} contains no records")
    return records


def _dataset_path(dataset_root: Path, uri: str) -> Path:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported dataset URI: {uri}")
    relative = Path(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"dataset URI escapes the dataset root: {uri}")
    path = dataset_root / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _infer_public_results(
    dataset_root: Path,
    frame: IsaacM1BRuntimeFrameV1,
    pipeline: GeometricRGBDBaseline,
) -> list[PerceptionResultV1]:
    camera = frame.policy_camera
    depth = np.load(_dataset_path(dataset_root, camera.depth_uri))
    rgb = np.asarray(Image.open(_dataset_path(dataset_root, camera.rgb_uri)).convert("RGB"))
    perception_input = PerceptionInputV1(
        frame_id=camera.name,
        timestamp_ns=frame.timestamp_ns,
        rgb_uri=camera.rgb_uri,
        depth_uri=camera.depth_uri,
        camera_intrinsics=camera.camera_intrinsics,
        camera_frame=f"{camera.name}_optical",
    )
    return pipeline.infer(perception_input, depth, rgb)


def _selected_track_id(
    frame: IsaacM1BRuntimeFrameV1,
    results: list[PerceptionResultV1],
    *,
    center_offset_m: float,
    support_bounds_m: tuple[float, float],
    public_xy_correction: M1BPublicGeometryXYCorrectionV1 | None,
) -> str | None:
    observation = observation_from_runtime_frame(
        frame,
        results,
        table_supported_center_offset_m=center_offset_m,
        table_support_world_z_bounds_m=support_bounds_m,
        current_task_id=f"{frame.episode_id}-observe-dynamics",
        public_xy_correction=public_xy_correction,
    )
    if not observation.object_tracks:
        return None
    return min(observation.object_tracks, key=lambda track: track.pose[0]).object_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--table-supported-z",
        type=Path,
        default=Path("configs/m1b_table_supported_cylinder_center.json"),
    )
    parser.add_argument(
        "--xy-correction",
        type=Path,
        default=None,
    )
    parser.add_argument("--min-component-pixels", type=int, default=50)
    parser.add_argument("--max-component-pixels", type=int, default=50_000)
    parser.add_argument("--color-similarity", type=float, default=0.95)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    runtime_path = dataset_root / "runtime_frames.jsonl"
    supervision_path = dataset_root / "supervision_frames.jsonl"
    capture_metrics = _load_capture_metrics(
        dataset_root,
        runtime_path=runtime_path,
        supervision_path=supervision_path,
    )
    runtime_records = _read_jsonl(runtime_path, IsaacM1BRuntimeFrameV1)
    supervision_records = _read_jsonl(
        supervision_path,
        IsaacM1BSupervisionFrameV1,
    )
    runtime = [
        record for record in runtime_records if isinstance(record, IsaacM1BRuntimeFrameV1)
    ]
    supervision = [
        record
        for record in supervision_records
        if isinstance(record, IsaacM1BSupervisionFrameV1)
    ]
    if len(runtime) < 2 or len(runtime) != len(supervision):
        raise ValueError(
            "runtime/supervision streams must contain the same number of frames "
            "and at least two frames"
        )
    for policy_frame, truth_frame in zip(runtime, supervision):
        if (
            policy_frame.episode_id,
            policy_frame.step_id,
            policy_frame.timestamp_ns,
        ) != (
            truth_frame.episode_id,
            truth_frame.step_id,
            truth_frame.timestamp_ns,
        ):
            raise ValueError("runtime/supervision frame keys do not match")

    support = M1BTableSupportedCylinderCenterV1.from_file(args.table_supported_z)
    public_xy_correction = (
        M1BPublicGeometryXYCorrectionV1.from_file(args.xy_correction)
        if args.xy_correction is not None
        else None
    )
    pipeline = GeometricRGBDBaseline(
        min_component_pixels=args.min_component_pixels,
        max_component_pixels=args.max_component_pixels,
        color_similarity=args.color_similarity,
    )
    all_results = [
        _infer_public_results(dataset_root, frame, pipeline) for frame in runtime
    ]
    output = args.output or dataset_root / "episode_transitions.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    transitions = []
    public_track_counts = []
    with output.open("w", encoding="utf-8") as stream:
        for index in range(len(runtime) - 1):
            selected = _selected_track_id(
                runtime[index],
                all_results[index],
                center_offset_m=support.center_offset_above_support_m,
                support_bounds_m=support.support_world_z_bounds_m,
                public_xy_correction=public_xy_correction,
            )
            transition = build_transition(
                runtime[index],
                runtime[index + 1],
                all_results[index],
                all_results[index + 1],
                supervision[index + 1],
                table_supported_center_offset_m=support.center_offset_above_support_m,
                table_support_world_z_bounds_m=support.support_world_z_bounds_m,
                selected_public_track_id=selected,
                public_xy_correction=public_xy_correction,
            )
            policy_json = json.dumps(
                {
                    "before": transition.observation_before.model_dump(),
                    "after": transition.observation_after.model_dump(),
                },
                sort_keys=True,
            )
            if any(entity in policy_json for entity in supervision[index + 1].perfect_object_poses_world_xyzw):
                raise RuntimeError(
                    "simulator entity ID leaked into policy-visible observations"
                )
            serialized = transition.model_dump_json()
            stream.write(serialized + "\n")
            transitions.append(transition)
            public_track_counts.append(len(transition.observation_before.object_tracks))

    metrics = {
        "schema_version": "IsaacM1BTransitionBuildMetricsV1",
        "status": "PASS",
        "transition_builder_source_sha256": _sha256(Path(__file__)),
        "mode": "SIM_ONLY",
        "dataset_root": str(dataset_root),
        "runtime_frames": len(runtime),
        "supervision_frames": len(supervision),
        "transitions": len(transitions),
        "public_track_count_min": min(public_track_counts),
        "public_track_count_max": max(public_track_counts),
        "public_track_count_total": sum(public_track_counts),
        "teacher_response_nonnull": sum(
            transition.teacher_response is not None for transition in transitions
        ),
        "policy_segmentation_uri_nonnull": sum(
            transition.observation_before.segmentation_uri is not None
            or transition.observation_after.segmentation_uri is not None
            for transition in transitions
        ),
        "runtime_frames_sha256": _sha256(runtime_path),
        "supervision_frames_sha256": _sha256(supervision_path),
        "episode_transitions_sha256": _sha256(output),
        "capture_metrics_sha256": _sha256(dataset_root / "metrics.json"),
        "capture_dataset_benchmark_source_sha256": capture_metrics[
            "dataset_benchmark_source_sha256"
        ],
        "capture_mode": capture_metrics["capture_mode"],
        "student_training_eligible": capture_metrics[
            "student_dataset_protocol"
        ]["training_eligible"],
        "table_supported_z_fingerprint": support.fingerprint,
        "public_xy_correction_runtime_enabled": (
            public_xy_correction is not None
        ),
        "public_xy_correction_fingerprint": (
            public_xy_correction.fingerprint
            if public_xy_correction is not None
            else None
        ),
        "public_xy_correction_training_input_sha256": (
            public_xy_correction.training_input_sha256
            if public_xy_correction is not None
            else None
        ),
        "tilted_center_support_offset": "PUBLIC_PERCEIVED_RADIUS",
        "center_xy_projection": (
            "PUBLIC_RAY_PLANE_WORLD_X_PLUS_"
            "VISIBLE_SURFACE_RADIUS_WORLD_Y"
        ),
        "truth_boundary": (
            "public RGB-D inference precedes the offline supervision join; "
            "ObservationV0 contains no simulator entity IDs or label segmentation"
        ),
        "robot_asset_required": OFFICIAL_ROBOT,
        "official_robot_variants": {
            "Gripper": "Default",
            "Mesh": "Performance",
        },
        "local_simplified_robot_used": False,
    }
    metrics_path = output.with_name("transition_metrics.json")
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
