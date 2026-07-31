#!/usr/bin/env python3
"""Export a small canonical Isaac sample to an auditable LeRobot v3 dataset.

The canonical record is one adjacent-frame transition, so each LeRobot episode
contains one action-aligned frame.  The after-state and after-image are explicit
``observation.next_*`` features.  This avoids inventing a terminal/no-op action.
No Teacher response or simulator supervision is exported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from xh_agent.data_engine.isaac.contract import validate_episode


JOINT_NAMES = [
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
    "panda_finger_joint1",
    "panda_finger_joint2",
]
FPS = 30
LEROBOT_VERSION = "v3.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_episodes(dataset_root: Path) -> list[tuple[dict[str, Any], Path]]:
    records: list[tuple[dict[str, Any], Path]] = []
    for path in sorted((dataset_root / "shards").glob("*.READY/episodes.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            episode = json.loads(line)
            errors = validate_episode(episode)
            if errors:
                raise ValueError(f"{episode.get('episode_id')} is not canonical: {errors}")
            records.append((episode, path.parent))
    return records


def select_diverse_episodes(
    records: list[tuple[dict[str, Any], Path]], limit: int
) -> list[tuple[dict[str, Any], Path]]:
    """Select one transition per scene before using any repeated scene."""

    if not 20 <= limit <= 50:
        raise ValueError("sample size must be between 20 and 50")
    ordered = sorted(
        records,
        key=lambda item: (
            item[0]["scene_group_id"],
            item[0]["episode_id"],
        ),
    )
    selected: list[tuple[dict[str, Any], Path]] = []
    seen_scenes: set[str] = set()
    for item in ordered:
        scene = str(item[0]["scene_group_id"])
        if scene not in seen_scenes:
            selected.append(item)
            seen_scenes.add(scene)
            if len(selected) == limit:
                return selected
    for item in ordered:
        if item not in selected:
            selected.append(item)
            if len(selected) == limit:
                return selected
    raise ValueError(f"requested {limit} episodes but only found {len(records)}")


def resolve_media(uri: str, shard_root: Path) -> Path:
    prefix = f"dataset://{shard_root.name}/"
    if not uri.startswith(prefix):
        raise ValueError(f"media URI does not belong to {shard_root.name}: {uri}")
    path = shard_root / uri.removeprefix(prefix)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _vector(value: Any, width: int, label: str) -> list[float]:
    result = [float(item) for item in value]
    if len(result) != width or not all(math.isfinite(item) for item in result):
        raise ValueError(f"{label} must contain {width} finite values")
    return result


def validate_mapping(episode: dict[str, Any]) -> dict[str, Any]:
    action = episode["executed_action"]
    if action["dimension_names"] != JOINT_NAMES:
        raise ValueError("executed_action joint order is not the official canonical Panda order")
    if action["coordinate_frame"] != "PANDA_DOF_ORDER_BY_NAME":
        raise ValueError("unexpected action coordinate frame")
    if action["units"] != "radian_arm_metre_finger":
        raise ValueError("unexpected action units")
    if float(action["frequency_hz"]) != FPS:
        raise ValueError("unexpected action frequency")
    if action["chunk_length"] != 1 or len(action["values"]) != 1:
        raise ValueError("only adjacent one-action canonical transitions are supported")
    before_ns = int(episode["observation_before"]["timestamp_ns"])
    after_ns = int(episode["observation_after"]["timestamp_ns"])
    expected_ns = round(1_000_000_000 / FPS)
    delta_ns = after_ns - before_ns
    return {
        "delta_ns": delta_ns,
        "expected_delta_ns": expected_ns,
        "absolute_alignment_error_ns": abs(delta_ns - expected_ns),
    }


def _image_payload(path: Path) -> tuple[dict[str, Any], tuple[int, int, int]]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        shape = (rgb.height, rgb.width, 3)
    return {"bytes": path.read_bytes(), "path": None}, shape


def _feature(dtype: str, shape: list[int], names: list[str] | None = None) -> dict[str, Any]:
    return {"dtype": dtype, "shape": shape, "names": names}


def _stats(values: list[list[float]]) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": np.min(array, axis=0).tolist(),
        "max": np.max(array, axis=0).tolist(),
        "mean": np.mean(array, axis=0).tolist(),
        "std": np.std(array, axis=0).tolist(),
        "count": [int(array.shape[0])],
    }


def export(
    dataset_root: Path,
    output_root: Path,
    *,
    limit: int,
    lock_path: Path,
) -> dict[str, Any]:
    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "LeRobot export requires pyarrow; install the lerobot-export dependencies"
        ) from exc

    selected = select_diverse_episodes(collect_episodes(dataset_root), limit)
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_root}")
    (output_root / "data/chunk-000").mkdir(parents=True)
    (output_root / "meta/episodes/chunk-000").mkdir(parents=True)

    columns: dict[str, list[Any]] = {
        "observation.state": [],
        "observation.velocity": [],
        "observation.end_effector_pose": [],
        "observation.next_state": [],
        "observation.images.rgb": [],
        "observation.images.next_rgb": [],
        "action": [],
        "timestamp": [],
        "frame_index": [],
        "episode_index": [],
        "index": [],
        "task_index": [],
        "source.timestamp_ns": [],
        "source.next_timestamp_ns": [],
        "source.episode_id": [],
        "source.split": [],
        "source.task_success": [],
    }
    task_to_index: dict[str, int] = {}
    episode_meta: list[dict[str, Any]] = []
    image_shape: tuple[int, int, int] | None = None
    alignment_errors: list[int] = []
    source_ids: list[str] = []

    for index, (episode, shard_root) in enumerate(selected):
        mapping = validate_mapping(episode)
        alignment_errors.append(mapping["absolute_alignment_error_ns"])
        before = episode["observation_before"]
        after = episode["observation_after"]
        task = str(episode["task_spec"]["source_instruction"])
        task_index = task_to_index.setdefault(task, len(task_to_index))
        before_image, before_shape = _image_payload(resolve_media(before["rgb_uri"], shard_root))
        after_image, after_shape = _image_payload(resolve_media(after["rgb_uri"], shard_root))
        if before_shape != after_shape:
            raise ValueError(f"before/after RGB shape mismatch for {episode['episode_id']}")
        if image_shape is None:
            image_shape = before_shape
        elif image_shape != before_shape:
            raise ValueError("selected RGB observations do not have one stable image shape")

        columns["observation.state"].append(_vector(before["joint_position"], 9, "state"))
        columns["observation.velocity"].append(_vector(before["joint_velocity"], 9, "velocity"))
        columns["observation.end_effector_pose"].append(
            _vector(before["end_effector_pose"], 7, "end_effector_pose")
        )
        columns["observation.next_state"].append(
            _vector(after["joint_position"], 9, "next_state")
        )
        columns["observation.images.rgb"].append(before_image)
        columns["observation.images.next_rgb"].append(after_image)
        columns["action"].append(_vector(episode["executed_action"]["values"][0], 9, "action"))
        columns["timestamp"].append(0.0)
        columns["frame_index"].append(0)
        columns["episode_index"].append(index)
        columns["index"].append(index)
        columns["task_index"].append(task_index)
        columns["source.timestamp_ns"].append(int(before["timestamp_ns"]))
        columns["source.next_timestamp_ns"].append(int(after["timestamp_ns"]))
        columns["source.episode_id"].append(str(episode["episode_id"]))
        columns["source.split"].append(str(episode["split"]))
        columns["source.task_success"].append(bool(episode["result"]["task_success"]))
        source_ids.append(str(episode["episode_id"]))
        episode_meta.append(
            {
                "episode_index": index,
                "tasks": [task],
                "length": 1,
                "data/chunk_index": 0,
                "data/file_index": 0,
                "dataset_from_index": index,
                "dataset_to_index": index + 1,
                "meta/episodes/chunk_index": 0,
                "meta/episodes/file_index": 0,
            }
        )

    assert image_shape is not None
    float9 = pa.list_(pa.float32(), 9)
    float7 = pa.list_(pa.float32(), 7)
    image_type = pa.struct([pa.field("bytes", pa.binary()), pa.field("path", pa.string())])
    schema = pa.schema(
        [
            pa.field("observation.state", float9),
            pa.field("observation.velocity", float9),
            pa.field("observation.end_effector_pose", float7),
            pa.field("observation.next_state", float9),
            pa.field("observation.images.rgb", image_type),
            pa.field("observation.images.next_rgb", image_type),
            pa.field("action", float9),
            pa.field("timestamp", pa.float32()),
            pa.field("frame_index", pa.int64()),
            pa.field("episode_index", pa.int64()),
            pa.field("index", pa.int64()),
            pa.field("task_index", pa.int64()),
            pa.field("source.timestamp_ns", pa.int64()),
            pa.field("source.next_timestamp_ns", pa.int64()),
            pa.field("source.episode_id", pa.string()),
            pa.field("source.split", pa.string()),
            pa.field("source.task_success", pa.bool_()),
        ]
    )
    table = pa.Table.from_pydict(columns, schema=schema)
    data_path = output_root / "data/chunk-000/file-000.parquet"
    pq.write_table(table, data_path, compression="snappy")

    tasks_path = output_root / "meta/tasks.parquet"
    tasks_frame = pd.DataFrame(
        {"task_index": list(task_to_index.values())},
        index=pd.Index(list(task_to_index), name="task"),
    )
    tasks_frame.to_parquet(tasks_path)
    episodes_path = output_root / "meta/episodes/chunk-000/file-000.parquet"
    pq.write_table(pa.Table.from_pylist(episode_meta), episodes_path, compression="snappy")

    features = {
        "observation.state": _feature("float32", [9], JOINT_NAMES),
        "observation.velocity": _feature("float32", [9], JOINT_NAMES),
        "observation.end_effector_pose": _feature(
            "float32", [7], ["x", "y", "z", "qx", "qy", "qz", "qw"]
        ),
        "observation.next_state": _feature("float32", [9], JOINT_NAMES),
        "observation.images.rgb": _feature(
            "image", list(image_shape), ["height", "width", "channels"]
        ),
        "observation.images.next_rgb": _feature(
            "image", list(image_shape), ["height", "width", "channels"]
        ),
        "action": _feature("float32", [9], JOINT_NAMES),
        "timestamp": _feature("float32", [1]),
        "frame_index": _feature("int64", [1]),
        "episode_index": _feature("int64", [1]),
        "index": _feature("int64", [1]),
        "task_index": _feature("int64", [1]),
        "source.timestamp_ns": _feature("int64", [1]),
        "source.next_timestamp_ns": _feature("int64", [1]),
        "source.episode_id": _feature("string", [1]),
        "source.split": _feature("string", [1]),
        "source.task_success": _feature("bool", [1]),
    }
    info = {
        "codebase_version": LEROBOT_VERSION,
        "robot_type": "franka_panda_9d_named_joint_position",
        "total_episodes": limit,
        "total_frames": limit,
        "total_tasks": len(task_to_index),
        "chunks_size": 1000,
        "data_files_size_in_mb": 100,
        "video_files_size_in_mb": 200,
        "fps": FPS,
        "splits": {"train": f"0:{limit}"},
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": None,
        "features": features,
    }
    info_path = output_root / "meta/info.json"
    info_path.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stats = {
        key: _stats(columns[key])
        for key in (
            "observation.state",
            "observation.velocity",
            "observation.end_effector_pose",
            "observation.next_state",
            "action",
        )
    }
    (output_root / "meta/stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copy2(lock_path, output_root / "meta/m2a-upstream-lock.yaml")

    data_readback = pq.read_table(data_path)
    tasks_readback = pd.read_parquet(tasks_path)
    episodes_readback = pq.read_table(episodes_path)
    official_readback: dict[str, Any] = {"status": "NOT_RUN_DATASETS_PACKAGE_MISSING"}
    try:
        import datasets

        hf_features: dict[str, Any] = {}
        for key, feature in features.items():
            if feature["dtype"] == "image":
                hf_features[key] = datasets.Image()
            elif feature["shape"] == [1]:
                hf_features[key] = datasets.Value(feature["dtype"])
            elif len(feature["shape"]) == 1:
                hf_features[key] = datasets.Sequence(
                    datasets.Value(feature["dtype"]),
                    length=feature["shape"][0],
                )
            else:
                raise RuntimeError(f"unsupported formal readback feature: {key}")
        official_dataset = datasets.Dataset.from_parquet(
            str(data_path),
            features=datasets.Features(hf_features),
        )
        first_row = official_dataset[0]
        if len(official_dataset) != limit or len(first_row["action"]) != 9:
            raise RuntimeError("Hugging Face datasets readback content mismatch")
        official_readback = {
            "status": "PASS",
            "rows": len(official_dataset),
            "action_dimension": len(first_row["action"]),
            "rgb_size": list(first_row["observation.images.rgb"].size),
        }
    except ImportError:
        pass

    validation = {
        "parquet_rows": data_readback.num_rows,
        "parquet_columns": data_readback.column_names,
        "tasks_index_name": tasks_readback.index.name,
        "episode_metadata_rows": episodes_readback.num_rows,
        "image_storage_type": str(data_readback.schema.field("observation.images.rgb").type),
        "action_storage_type": str(data_readback.schema.field("action").type),
        "official_huggingface_datasets_readback": official_readback,
    }
    if (
        data_readback.num_rows != limit
        or episodes_readback.num_rows != limit
        or tasks_readback.index.name != "task"
    ):
        raise RuntimeError(f"LeRobot v3 readback validation failed: {validation}")

    files = sorted(path for path in output_root.rglob("*") if path.is_file())
    report = {
        "schema_version": "M2ALingBotPrepReportV1",
        "status": "PASS_BASELINE_PREP_ONLY",
        "teacher_enabled": False,
        "control_stack_integration": False,
        "source_dataset": str(dataset_root),
        "output_root": str(output_root),
        "canonical_episodes_exported": limit,
        "lerobot_codebase_version": LEROBOT_VERSION,
        "frame_semantics": "one action-aligned frame per adjacent canonical transition",
        "feature_mapping": {
            "observation.state": "observation_before.joint_position",
            "observation.velocity": "observation_before.joint_velocity",
            "observation.next_state": "observation_after.joint_position",
            "action": "executed_action.values[0]",
            "observation.images.rgb": "observation_before.rgb_uri",
            "observation.images.next_rgb": "observation_after.rgb_uri",
        },
        "action_protocol": {
            "coordinate_frame": "PANDA_DOF_ORDER_BY_NAME",
            "dimension_names": JOINT_NAMES,
            "units": "radian_arm_metre_finger",
            "frequency_hz": FPS,
            "source_normalization_revision": "isaac-m1b-joint-identity-v1",
            "normalization_applied_by_exporter": False,
            "remapping_applied_by_exporter": False,
        },
        "time_alignment": {
            "expected_delta_ns": round(1_000_000_000 / FPS),
            "max_absolute_error_ns": max(alignment_errors),
            "all_within_one_ns": max(alignment_errors) <= 1,
        },
        "source_split_counts": dict(
            sorted(Counter(item[0]["split"] for item in selected).items())
        ),
        "distinct_scene_groups": len({item[0]["scene_group_id"] for item in selected}),
        "duplicate_source_episode_ids": len(source_ids) - len(set(source_ids)),
        "privileged_simulator_truth_exported": False,
        "teacher_response_exported": False,
        "validation": validation,
        "baseline_resource_audit": {
            "model_repository_bytes": 86_071_862_266,
            "planning_disk_headroom_bytes": 180_000_000_000,
            "node2_gpu": "NVIDIA A100-SXM4-80GB",
            "node2_gpu_count": 1,
            "official_reference_gpu_count": 8,
            "single_a100_vram_status": "NOT_VALIDATED_AND_NOT_CLAIMED",
            "planning_time_budget": "4-8 hours for isolated env, download, and one smoke only",
            "full_training_time": "NOT_ESTIMATED_OUT_OF_SCOPE",
            "node2_system_python_missing_dependencies": [
                "torch",
                "torchvision",
                "torchaudio",
                "diffusers",
                "transformers",
                "tokenizers",
                "accelerate",
                "imageio",
                "easydict",
                "ftfy",
                "flash_attn",
            ],
        },
        "files": {
            str(path.relative_to(output_root)): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        },
        "output_bytes": sum(path.stat().st_size for path in files),
        "limitations": [
            "This is a format-validation sample, not LingBot training.",
            "Each canonical record has one action; no terminal action was invented.",
            "LingBot-World v2 is non-commercial CC BY-NC-SA 4.0.",
            "The official v2 example uses eight GPUs; no single-A100 runtime claim is made.",
            "No LingBot weight was downloaded and no VRAM/throughput metric was fabricated.",
        ],
    }
    (output_root / "export-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def write_reports(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    time_alignment = report["time_alignment"]
    markdown_path.write_text(
        "\n".join(
            [
                "# M2A S7 LingBot / LeRobot preparation",
                "",
                f"- status: **{report['status']}**",
                "- Teacher: disabled; this baseline is not connected to the control stack.",
                f"- canonical episodes exported: {report['canonical_episodes_exported']}",
                f"- distinct scene groups: {report['distinct_scene_groups']}",
                f"- LeRobot dataset version: `{report['lerobot_codebase_version']}`",
                "- action: raw 9D named Panda joint-position target at 30 Hz; no remapping "
                "or normalization was applied",
                f"- maximum adjacent-frame alignment error: "
                f"{time_alignment['max_absolute_error_ns']} ns",
                f"- privileged simulator truth exported: "
                f"{report['privileged_simulator_truth_exported']}",
                f"- Teacher response exported: {report['teacher_response_exported']}",
                f"- output bytes: {report['output_bytes']}",
                "- official Hugging Face datasets image/action readback: "
                f"{report['validation']['official_huggingface_datasets_readback']['status']}",
                "",
                "## Baseline decision",
                "",
                "- Current upstream candidate: LingBot-World v2 14B causal-fast.",
                "- License: CC BY-NC-SA 4.0; commercial use is blocked pending human review.",
                "- Official example uses eight GPUs. Disk, VRAM, and runtime must be measured "
                "in a separate authorized baseline task; they are not guessed here.",
                "- Model repository metadata reports 86.07 GB; reserve about 180 GB planning "
                "headroom for weights, caches, and an isolated environment.",
                "- Planning budget for environment setup, download, and one smoke: 4–8 hours. "
                "This is not a measured runtime or a training estimate.",
                "- node2 has one A100 80 GB, while the official command uses eight GPUs; "
                "single-A100 feasibility is unvalidated.",
                "- v1 remains recorded as an Apache-2.0 historical fallback, but was not "
                "silently selected because upstream marks it unmaintained.",
                "",
                "## Limitations",
                "",
                *[f"- {item}" for item in report["limitations"]],
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("configs/lingbot_lerobot.lock.yaml"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("reports/m2a-s7-lingbot-prep.json"),
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("reports/m2a-s7-lingbot-prep.md"),
    )
    args = parser.parse_args()
    report = export(
        args.dataset_root.resolve(),
        args.output_root.resolve(),
        limit=args.limit,
        lock_path=args.lock.resolve(),
    )
    write_reports(report, args.report_json, args.report_md)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
