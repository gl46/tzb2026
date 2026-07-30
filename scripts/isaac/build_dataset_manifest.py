#!/usr/bin/env python3
"""Convert real Isaac captures into validated READY canonical shards."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from xh_agent.data_engine.isaac.contract import (
    ACTION_DIMENSION_NAMES,
    ShardState,
    atomic_write_json,
    canonical_json_sha256,
    sha256_file,
    stable_split,
    transition_shard_state,
    validate_episode,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def gripper_value(state: str) -> float:
    return {"open": 0.0, "partially_open": 0.5, "closed": 1.0}.get(state, 0.5)


def camera_delta(world_delta: np.ndarray, camera_to_world: list[float]) -> np.ndarray:
    rotation = np.asarray(camera_to_world, dtype=float).reshape(4, 4)[:3, :3]
    return rotation.T @ world_delta


def qrm_action(values: list[float]) -> dict[str, Any]:
    return {
        "coordinate_frame": "camera_optical",
        "representation": "delta_ee_cam_r6d_gripper",
        "units": "m_rad_norm",
        "frequency_hz": 5.0,
        "chunk_length": 4,
        "dimension_names": ACTION_DIMENSION_NAMES,
        "normalization_revision": "qrm-lite-beta-real-isaac-v1",
        "values": [values] * 4,
    }


def executed_action(transition: dict[str, Any]) -> dict[str, Any]:
    action = transition["action_trajectory"]
    return {
        "coordinate_frame": action["coordinate_frame"],
        "representation": action["representation"],
        "units": action["units"],
        "frequency_hz": action["fps"],
        "chunk_length": len(action["values"]),
        "dimension_names": action["dimension_names"],
        "normalization_revision": action["normalization_revision"],
        "values": action["values"],
    }


def link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def copy_media(
    capture_root: Path,
    shard_root: Path,
    episode_id: str,
    before_step: int,
    after_step: int,
) -> tuple[dict[str, str], list[Path]]:
    uris: dict[str, str] = {}
    copied: list[Path] = []
    for phase, step in (("before", before_step), ("after", after_step)):
        stem = f"{step:06d}"
        for kind, extension in (
            ("rgb", ".png"),
            ("depth", ".npy"),
            ("semantic", ".png"),
            ("instance", ".png"),
        ):
            source = capture_root / "policy_rgbd" / kind / f"{stem}{extension}"
            relative = Path("media") / episode_id / f"{phase}_{kind}{extension}"
            destination = shard_root / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            link_or_copy(source, destination)
            copied.append(destination)
            ready_name = shard_root.name.replace(".WRITING", ".READY")
            uris[f"{phase}_{kind}"] = f"dataset://{ready_name}/{relative.as_posix()}"
    return uris, copied


def residual_label(transition: dict[str, Any]) -> tuple[list[float], str, str, list[str]]:
    observation = transition["observation_before"]
    tracks = observation["object_tracks"]
    truth = transition["simulator_supervision"]["perfect_object_poses"]
    if not tracks:
        return [0.0] * 10, "REOBSERVE", "TRACKING_LOST", ["missing:public_track_observed"]
    selected = min(tracks, key=lambda item: item["pose"][0])
    public_xyz = np.asarray(selected["pose"][:3], dtype=float)
    truth_xyz = [np.asarray(pose[:3], dtype=float) for pose in truth.values()]
    if not truth_xyz:
        return [0.0] * 10, "STOP_OR_ABORT", "UNKNOWN", ["missing:simulator_label"]
    nearest = min(truth_xyz, key=lambda xyz: float(np.linalg.norm(xyz - public_xyz)))
    correction_world = nearest - public_xyz
    correction_cam = np.clip(
        camera_delta(correction_world, observation["camera_extrinsics"]),
        -0.03,
        0.03,
    )
    uncertainty = float(observation.get("uncertainty", 1.0))
    failure = uncertainty > 0.45 or float(np.linalg.norm(correction_world)) > 0.03
    skill = "REOBSERVE" if failure else "APPROACH"
    failure_type = "TRACKING_LOST" if failure else "NONE"
    residuals = ["public_track_low_confidence"] if failure else []
    values = [*correction_cam.tolist(), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return values, skill, failure_type, residuals


def canonical_episode(
    transition: dict[str, Any],
    *,
    dataset_version: str,
    seed: int,
    worker_id: int,
    code_revision: str,
    config_hash: str,
    shard_root: Path,
    capture_root: Path,
) -> dict[str, Any]:
    before = json.loads(json.dumps(transition["observation_before"]))
    after = json.loads(json.dumps(transition["observation_after"]))
    episode_id = f"isaac-s{seed}-w{worker_id}-t{before['step_id']:06d}"
    before["episode_id"] = episode_id
    after["episode_id"] = episode_id
    media, _ = copy_media(
        capture_root, shard_root, episode_id, int(before["step_id"]), int(after["step_id"])
    )
    before["rgb_uri"], before["depth_uri"] = media["before_rgb"], media["before_depth"]
    after["rgb_uri"], after["depth_uri"] = media["after_rgb"], media["after_depth"]
    before["segmentation_uri"] = None
    after["segmentation_uri"] = None
    residual, skill, failure_type, predicate_residual = residual_label(transition)
    expected = ["public_track_observed", "safe_action_candidate"]
    observed = ["safe_action_candidate"]
    if after["object_tracks"]:
        observed.append("public_track_observed")
    split, split_kind = stable_split(seed)
    zeros = [0.0] * 10
    episode = {
        "schema_version": "IsaacIndustrialEpisodeV1",
        "dataset_version": dataset_version,
        "episode_id": episode_id,
        "scene_seed": seed,
        "scene_group_id": f"isaac-scene-{seed}",
        "split": split,
        "split_kind": split_kind,
        "worker_id": worker_id,
        "code_revision": code_revision,
        "isaac_version": "6.0.1",
        "scene_asset_revision": canonical_json_sha256(
            transition["simulator_supervision"]["physical_parameters"]
        ),
        "config_hash": config_hash,
        "observation_before": before,
        "observation_after": after,
        "task_spec": transition["task_spec"],
        "robot_state": {
            "joint_names": transition["action_trajectory"]["dimension_names"],
            "joint_position": before["joint_position"],
            "joint_velocity": before["joint_velocity"],
            "end_effector_pose_world_xyzw": before["end_effector_pose"],
            "gripper_state": before["gripper_state"],
        },
        "skill_history": [{"step_id": before["step_id"], "skill": "OBSERVE"}],
        "failure_context": {
            "schema_version": "FailureContextV1",
            "last_skill": "OBSERVE",
            "expected_predicates": expected,
            "observed_predicates": observed,
            "predicate_residual": predicate_residual,
            "failure_type": failure_type,
            "retry_count": 0,
            "attempted_recoveries": [],
            "last_action_summary": "Isaac articulation excitation",
            "last_target_track_id": transition["task_spec"].get("target_object_id"),
        },
        "nominal_skill": skill,
        "nominal_action": qrm_action(zeros),
        "executed_action": executed_action(transition),
        "residual_action": qrm_action(residual),
        "expected_predicates": expected,
        "observed_predicates": observed,
        "recovery_sequence": ["REOBSERVE"] if failure_type != "NONE" else [],
        "result": {
            "observation_quality_pass": failure_type == "NONE",
            "task_success": bool(
                transition["simulator_supervision"].get("task_success", False)
            ),
            "failure_type": failure_type,
        },
        "simulator_supervision": {
            **transition["simulator_supervision"],
            "training_and_evaluation_only": True,
            "mask_uris": {
                "before_semantic": media["before_semantic"],
                "before_instance": media["before_instance"],
                "after_semantic": media["after_semantic"],
                "after_instance": media["after_instance"],
            },
        },
        "provenance": {
            **transition["provenance"],
            "source": "real_isaac_rgbd_adjacent_frame_transition",
            "residual_label": "nearest_hard_truth_minus_public_track_camera_frame",
            "teacher": "absent",
        },
    }
    errors = validate_episode(episode)
    if errors:
        raise ValueError(f"{episode_id}: {errors}")
    return episode


def ensure_transitions(project_root: Path, capture_root: Path) -> Path:
    output = capture_root / "episode_transitions.jsonl"
    if output.is_file():
        return output
    command = [
        sys.executable,
        str(project_root / "scripts" / "build_isaac_m1b_transitions.py"),
        "--dataset-root",
        str(capture_root),
        "--output",
        str(output),
        "--table-supported-z",
        str(project_root / "configs" / "m1b_table_supported_cylinder_center.json"),
        "--xy-correction",
        str(project_root / "configs" / "m1b_public_geometry_xy_correction.json"),
    ]
    subprocess.run(command, check=True, cwd=project_root)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--dataset-version", default="isaac-industrial-v1-pilot")
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--shard-size", type=int, default=50)
    parser.add_argument("--manifest-out", type=Path)
    args = parser.parse_args()
    dataset_root = args.data_root / args.dataset_version
    raw_root = dataset_root / "raw"
    shards_root = dataset_root / "shards"
    shards_root.mkdir(parents=True, exist_ok=True)
    config_hash = sha256_file(
        args.project_root / "configs" / "isaac_dataset_v1_pilot.yaml"
    )
    sources: list[tuple[int, int, Path, Path]] = []
    for run_root in sorted(raw_root.glob("seeds-*-*")):
        summary_path = run_root / "dual-benchmark-summary.json"
        if not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text())
        if summary.get("status") != "PASS":
            continue
        for source in summary["worker_sources"]:
            seed = int(Path(source["sdf"]).stem.split("-")[-1])
            worker_id = int(source["worker_id"])
            capture = run_root / f"worker{worker_id}" / "output"
            transitions = ensure_transitions(args.project_root, capture)
            sources.append((seed, worker_id, capture, transitions))
    if not sources:
        raise SystemExit(f"no PASS capture sources under {raw_root}")
    all_rows: list[tuple[int, int, Path, dict[str, Any]]] = []
    for seed, worker_id, capture, transitions in sorted(sources):
        for row in read_jsonl(transitions):
            all_rows.append((seed, worker_id, capture, row))
    seen: set[str] = set()
    shard_manifests: list[dict[str, Any]] = []
    counts = {"train": 0, "val": 0, "test": 0}
    failure_count = 0
    for shard_index, begin in enumerate(range(0, len(all_rows), args.shard_size)):
        rows = all_rows[begin : begin + args.shard_size]
        final_root = shards_root / f"shard-{shard_index:05d}.READY"
        if final_root.exists():
            prior = json.loads((final_root / "manifest.json").read_text())
            shard_manifests.append(prior)
            for split, value in prior["split_counts"].items():
                counts[split] += int(value)
            failure_count += int(prior["failure_or_recovery_episodes"])
            seen.update(prior["episode_ids"])
            continue
        writing = shards_root / f"shard-{shard_index:05d}.WRITING"
        writing.mkdir(parents=True, exist_ok=False)
        episodes: list[dict[str, Any]] = []
        try:
            for seed, worker_id, capture, transition in rows:
                episode = canonical_episode(
                    transition,
                    dataset_version=args.dataset_version,
                    seed=seed,
                    worker_id=worker_id,
                    code_revision=args.code_revision,
                    config_hash=config_hash,
                    shard_root=writing,
                    capture_root=capture,
                )
                if episode["episode_id"] in seen:
                    raise ValueError(f"duplicate episode: {episode['episode_id']}")
                seen.add(episode["episode_id"])
                episodes.append(episode)
            episodes_path = writing / "episodes.jsonl"
            episodes_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in episodes)
            )
            split_counts = {
                split: sum(row["split"] == split for row in episodes)
                for split in ("train", "val", "test")
            }
            shard_failures = sum(
                row["failure_context"]["failure_type"] != "NONE" for row in episodes
            )
            state = transition_shard_state(ShardState.WRITING, ShardState.VALIDATING)
            files = sorted(
                path for path in writing.rglob("*") if path.is_file() and path.name != "manifest.json"
            )
            manifest = {
                "schema_version": "IsaacIndustrialShardManifestV1",
                "dataset_version": args.dataset_version,
                "shard_id": f"shard-{shard_index:05d}",
                "state": state.value,
                "episode_count": len(episodes),
                "episode_ids": [row["episode_id"] for row in episodes],
                "scene_seeds": sorted({row["scene_seed"] for row in episodes}),
                "split_counts": split_counts,
                "failure_or_recovery_episodes": shard_failures,
                "episodes_sha256": sha256_file(episodes_path),
                "files": {
                    str(path.relative_to(writing)): sha256_file(path) for path in files
                },
                "code_revision": args.code_revision,
                "config_hash": config_hash,
            }
            manifest["manifest_content_hash"] = canonical_json_sha256(manifest)
            manifest["state"] = transition_shard_state(state, ShardState.READY).value
            atomic_write_json(writing / "manifest.json", manifest)
            writing.replace(final_root)
            shard_manifests.append(manifest)
            for split, value in split_counts.items():
                counts[split] += value
            failure_count += shard_failures
        except Exception:
            quarantine = shards_root / f"shard-{shard_index:05d}.QUARANTINED"
            if writing.exists():
                writing.replace(quarantine)
            raise
    manifest = {
        "schema_version": "IsaacIndustrialDatasetManifestV1",
        "dataset_version": args.dataset_version,
        "status": "READY",
        "code_revision": args.code_revision,
        "config_hash": config_hash,
        "episodes_valid": len(seen),
        "episodes_quarantined": sum(
            1 for _ in shards_root.glob("*.QUARANTINED")
        ),
        "failure_or_recovery_episodes": failure_count,
        "failure_or_recovery_fraction": failure_count / max(len(seen), 1),
        "split_counts": counts,
        "scene_seeds": sorted({seed for seed, *_ in sources}),
        "shards": [
            {
                "shard_id": item["shard_id"],
                "state": item["state"],
                "episode_count": item["episode_count"],
                "manifest_content_hash": item["manifest_content_hash"],
            }
            for item in shard_manifests
        ],
    }
    manifest["dataset_manifest_hash"] = canonical_json_sha256(manifest)
    output = args.manifest_out or dataset_root / "manifest.json"
    atomic_write_json(output, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
