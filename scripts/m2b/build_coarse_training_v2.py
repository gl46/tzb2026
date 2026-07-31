#!/usr/bin/env python3
"""Materialize Dataset V2 public observations as coarse-only QRM samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV1,
    FailureContextV1,
    PerceptionTrackV1,
    QRMCoarseTrainingSampleV2,
    QRMObservationV1,
)


GRIPPER_AFTER_FAILURE = {
    "EMPTY_GRASP": 0.0,
    "WRONG_OBJECT": 1.0,
    "RELEASE_FAILURE": 0.0,
}


def _camera_xyz(
    position_world_m: list[float], camera_to_world_optical: list[float]
) -> list[float]:
    transform = np.asarray(camera_to_world_optical, dtype=np.float64).reshape(4, 4)
    world = np.asarray([*position_world_m, 1.0], dtype=np.float64)
    camera = np.linalg.inv(transform) @ world
    if not np.isfinite(camera).all() or abs(float(camera[3])) < 1e-12:
        raise ValueError("public world-to-camera projection is non-finite")
    return [float(value / camera[3]) for value in camera[:3]]


def coarse_sample(
    episode: dict[str, Any], *, rgb_uri: str, depth_uri: str
) -> QRMCoarseTrainingSampleV2:
    failure_type = str(episode["failure_context"]["failure_type"])
    recovery_skill = str(episode["recovery_sequence"][0])
    capture = episode["observation_after"]
    camera = episode["public_camera"]
    context = FailureContextV1.model_validate(episode["failure_context"])
    tracks = [
        PerceptionTrackV1(
            track_id=track["track_id"],
            category=(
                f"{track['category']}:{track['visual_color']}"
                if track.get("visual_color")
                else track["category"]
            ),
            confidence=track["confidence"],
            pose_xyzquat=[
                *_camera_xyz(
                    track["position_world_m"],
                    camera["camera_to_world_optical"],
                ),
                1.0,
                0.0,
                0.0,
                0.0,
            ],
        )
        for track in capture["tracks"]
    ]
    if (
        context.last_carried_track_id
        and context.last_carried_track_id
        not in {track.track_id for track in tracks}
    ):
        retained = next(
            (
                track
                for track in episode["observation_before"]["tracks"]
                if track["track_id"] == context.last_carried_track_id
            ),
            None,
        )
        if retained is None:
            raise ValueError("public carried-track memory has no prior track")
        tracks.append(
            PerceptionTrackV1(
                track_id=retained["track_id"],
                category=(
                    f"{retained['category']}:{retained['visual_color']}"
                    if retained.get("visual_color")
                    else retained["category"]
                ),
                confidence=0.0,
                pose_xyzquat=None,
            )
        )
    action_target_track_id = (
        context.last_carried_track_id
        if recovery_skill in {"SAFE_PLACE_NON_TARGET", "RETRY_RELEASE"}
        and context.last_carried_track_id
        else episode["task_spec"]["target_track_id"]
    )
    transform_digest = hashlib.sha256(
        json.dumps(
            camera["camera_to_world_optical"], separators=(",", ":")
        ).encode()
    ).hexdigest()
    observation = QRMObservationV1(
        episode_id=episode["episode_id"],
        step_id=1,
        timestamp_ns=capture["timestamp_ns"],
        instruction=episode["task_spec"]["instruction"],
        task_target_track_id=episode["task_spec"]["target_track_id"],
        rgb_uri=rgb_uri,
        depth_uri=depth_uri,
        camera_frame=camera["camera_frame"],
        camera_intrinsics=camera["camera_intrinsics"],
        # Only world_T_camera is present in public evidence.  Robot base
        # extrinsics are deliberately left absent rather than guessed.
        camera_extrinsics_base_T_cam=[],
        gripper_state=GRIPPER_AFTER_FAILURE[failure_type],
        current_skill_stage="RECOVERY_DECISION",
        perception_tracks=tracks,
        failure_context=context,
    )
    return QRMCoarseTrainingSampleV2(
        sample_id=f"{episode['episode_id']}:coarse-recovery-0",
        episode_id=episode["episode_id"],
        seed=int(episode["injection_seed"]),
        split=episode["split"],
        observation=observation,
        coarse_intent=CoarseIntentV1(
            skill_type=recovery_skill,
            target_track_id=action_target_track_id,
            recovery_mode=failure_type.lower(),
            reobserve_flag=recovery_skill == "REOBSERVE",
            failure_type_aux=failure_type,
        ),
        simulator_supervision=episode["simulator_supervision"],
        provenance={
            "dataset_version": episode["dataset_version"],
            "split_group": episode["split_group"],
            "evidence_sha256": episode["provenance"]["evidence_sha256"],
            "label_source": "EXECUTED_PUBLIC_RECOVERY_SEQUENCE",
            "continuous_action_target": "ABSENT_NOT_GUESSED",
            "base_to_camera_extrinsics": "ABSENT_NOT_GUESSED",
            "public_camera_to_world_sha256": transform_digest,
            "occluded_carried_track_retention": (
                "PUBLIC_TEMPORAL_MEMORY_CONFIDENCE_ZERO"
                if context.last_carried_track_id
                else "NOT_APPLICABLE"
            ),
        },
    )


def _source_relative(uri: str) -> PurePosixPath:
    prefix = "dataset://"
    if not uri.startswith(prefix):
        raise ValueError(f"unsupported public asset URI: {uri}")
    relative = PurePosixPath(uri[len(prefix) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"public asset URI escapes evidence root: {uri}")
    return relative


def _copy_asset(
    *,
    host: str,
    evidence_path: str,
    source_uri: str,
    destination: Path,
    expected_sha256: str,
) -> None:
    source = PurePosixPath(evidence_path).parent / _source_relative(source_uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["scp", "-q", f"{host}:{source}", str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"cannot copy {source}")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    if digest != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ValueError(f"asset hash mismatch for {source}")


def materialize_observation(
    episode: dict[str, Any], *, host: str, asset_root: Path
) -> tuple[str, str]:
    capture = episode["observation_after"]
    target = asset_root / "episodes" / episode["episode_id"]
    rgb = target / "rgb" / f"{capture['label']}.png"
    depth = target / "depth" / f"{capture['label']}.npy"
    for uri, destination, digest in (
        (capture["rgb_uri"], rgb, capture["rgb_sha256"]),
        (capture["depth_uri"], depth, capture["depth_sha256"]),
    ):
        if not destination.is_file() or hashlib.sha256(
            destination.read_bytes()
        ).hexdigest() != digest:
            _copy_asset(
                host=host,
                evidence_path=episode["provenance"]["evidence_path"],
                source_uri=uri,
                destination=destination,
                expected_sha256=digest,
            )
    return (
        f"dataset://episodes/{episode['episode_id']}/rgb/{capture['label']}.png",
        f"dataset://episodes/{episode['episode_id']}/depth/{capture['label']}.npy",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    samples: list[QRMCoarseTrainingSampleV2] = []
    quarantine: list[dict[str, str]] = []
    for line in args.episodes.read_text().splitlines():
        if not line.strip():
            continue
        episode = json.loads(line)
        try:
            rgb_uri, depth_uri = materialize_observation(
                episode, host=args.host, asset_root=args.asset_root
            )
            samples.append(
                coarse_sample(
                    episode, rgb_uri=rgb_uri, depth_uri=depth_uri
                )
            )
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            quarantine.append(
                {
                    "episode_id": str(episode.get("episode_id", "UNKNOWN")),
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(sample.model_dump_json() + "\n" for sample in samples)
    )
    args.quarantine.parent.mkdir(parents=True, exist_ok=True)
    args.quarantine.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in quarantine)
    )
    report = {
        "schema_version": "M2BCoarseTrainingDatasetReportV1",
        "status": "PASS" if samples and not quarantine else "PARTIAL",
        "samples_valid": len(samples),
        "samples_quarantined": len(quarantine),
        "continuous_action_targets": 0,
        "zero_filled_action_targets": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "asset_root": str(args.asset_root),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if samples else 1


if __name__ == "__main__":
    raise SystemExit(main())
