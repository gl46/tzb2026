#!/usr/bin/env python3
"""Canonical Isaac episode -> QRMTrainingSampleV1 without Oracle inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from xh_agent.data_engine.isaac.contract import audit_policy_projection, policy_projection, sha256_file
from xh_agent.policy.qrm_lite.contracts import (
    CameraFrameActionChunkV1,
    CoarseIntentV1,
    FailureContextV1,
    PerceptionTrackV1,
    QRMObservationV1,
    QRMTrainingSampleV1,
)


def action(payload: dict, *, residual: bool) -> CameraFrameActionChunkV1:
    return CameraFrameActionChunkV1(
        fps=payload["frequency_hz"],
        dimension_names=payload["dimension_names"],
        values=payload["values"],
        normalization_revision=payload["normalization_revision"],
        is_residual=residual,
    )


def qrm_sample(episode: dict, *, failure_context: bool, manifest_hash: str) -> QRMTrainingSampleV1:
    findings = audit_policy_projection(policy_projection(episode))
    if findings:
        raise ValueError(f"{episode['episode_id']}: {findings}")
    before = episode["observation_before"]
    failure = FailureContextV1.model_validate(episode["failure_context"])
    if not failure_context:
        failure = FailureContextV1()
    # QRM contract says base-frame wxyz.  Isaac only proves world-frame xyzw
    # in this corpus, so do not mislabel it as base: leave the optional vector
    # empty and retain the proven world pose in history/provenance.
    observation = QRMObservationV1(
        episode_id=episode["episode_id"],
        step_id=before["step_id"],
        timestamp_ns=before["timestamp_ns"],
        instruction=episode["task_spec"]["source_instruction"],
        rgb_uri=before["rgb_uri"],
        depth_uri=before["depth_uri"],
        camera_frame="policy_rgbd_optical",
        camera_intrinsics=before["camera_intrinsics"],
        camera_extrinsics_base_T_cam=[],
        joint_position=before["joint_position"],
        joint_velocity=before["joint_velocity"],
        end_effector_pose_base=[],
        gripper_state={
            "open": 0.0,
            "partially_open": 0.5,
            "closed": 1.0,
        }.get(before["gripper_state"], 0.5),
        current_skill_stage=episode["nominal_skill"],
        perception_tracks=[
            PerceptionTrackV1(
                track_id=track["object_id"],
                category=track["category"],
                confidence=track["confidence"],
                pose_xyzquat=track["pose"],
            )
            for track in before["object_tracks"]
        ],
        failure_context=failure,
    )
    nominal = action(episode["nominal_action"], residual=False)
    residual = action(episode["residual_action"], residual=True)
    target_values = (
        np.asarray(nominal.values, dtype=float) + np.asarray(residual.values, dtype=float)
    ).tolist()
    target = CameraFrameActionChunkV1(
        fps=nominal.fps,
        dimension_names=nominal.dimension_names,
        values=target_values,
        normalization_revision=nominal.normalization_revision,
        is_residual=False,
    )
    skill = episode["nominal_skill"]
    return QRMTrainingSampleV1(
        sample_id=f"{episode['episode_id']}-fc-{int(failure_context)}",
        episode_id=episode["episode_id"],
        seed=episode["scene_seed"],
        split=episode["split"],
        observation=observation,
        coarse_intent=CoarseIntentV1(
            skill_type=skill,
            target_track_id=episode["task_spec"].get("target_object_id"),
            recovery_mode="reobserve" if skill == "REOBSERVE" else "none",
            reobserve_flag=skill == "REOBSERVE",
            failure_type_aux=failure.failure_type,
        ),
        nominal_action_chunk=nominal,
        residual_action_chunk=residual,
        target_action_chunk=target,
        simulator_supervision=episode["simulator_supervision"],
        provenance={
            "dataset_version": episode["dataset_version"],
            "dataset_manifest_hash": manifest_hash,
            "code_revision": episode["code_revision"],
            "source_schema": episode["schema_version"],
            "failure_context": "on" if failure_context else "off",
            "base_pose_status": "omitted_unproven_world_to_base_transform",
        },
        synthetic=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--failure-context", choices=("on", "off"), default="on")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    manifest_path = args.dataset_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "READY":
        raise SystemExit("dataset is not READY")
    manifest_hash = manifest["dataset_manifest_hash"]
    enabled = args.failure_context == "on"
    samples: list[QRMTrainingSampleV1] = []
    for shard_info in manifest["shards"]:
        if shard_info["state"] != "READY":
            raise ValueError(f"non-READY shard in dataset manifest: {shard_info}")
        shard = args.dataset_root / "shards" / f"{shard_info['shard_id']}.READY"
        for line in (shard / "episodes.jsonl").read_text().splitlines():
            if line.strip():
                samples.append(
                    qrm_sample(
                        json.loads(line),
                        failure_context=enabled,
                        manifest_hash=manifest_hash,
                    )
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(sample.model_dump_json() + "\n" for sample in samples))
    split_counts = {
        split: sum(sample.split == split for sample in samples)
        for split in ("train", "val", "test")
    }
    summary = {
        "schema_version": "QRMIsaacDatasetBuildV1",
        "status": "PASS",
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_hash": manifest_hash,
        "failure_context": args.failure_context,
        "samples": len(samples),
        "split_counts": split_counts,
        "failure_or_recovery_samples": sum(
            sample.coarse_intent.skill_type == "REOBSERVE" for sample in samples
        ),
        "synthetic_samples": sum(sample.synthetic for sample in samples),
        "oracle_policy_findings": 0,
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
    }
    summary_path = args.summary or args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
