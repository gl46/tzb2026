#!/usr/bin/env python3
"""Convert physical perturbation/correction pairs to masked QRM samples."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from m2b.build_coarse_training_v2 import _camera_xyz, _copy_asset
    from m2b.build_dataset_v2 import scene_split
    from m2b.build_residual_pairs import remote_json, remote_sha256
except ModuleNotFoundError:
    from build_coarse_training_v2 import _camera_xyz, _copy_asset
    from build_dataset_v2 import scene_split
    from build_residual_pairs import remote_json, remote_sha256

from xh_agent.policy.qrm_lite.contracts import (
    CameraFrameActionChunkV1,
    CoarseIntentV1,
    FailureContextV1,
    FailureType,
    PerceptionTrackV1,
    QRMObservationV1,
    QRMTrainingSampleV1,
)


DIMENSIONS = [
    "dx",
    "dy",
    "dz",
    "r6d_0",
    "r6d_1",
    "r6d_2",
    "r6d_3",
    "r6d_4",
    "r6d_5",
    "gripper",
]


def _validate_pair(pair: dict[str, Any]) -> None:
    if pair.get("teacher_used") is not False:
        raise ValueError("residual pair has no explicit no-Teacher boundary")
    if pair.get("dimension_names") != DIMENSIONS:
        raise ValueError("residual pair dimensions are missing or ambiguous")
    if pair.get("correction_physically_successful") is not True:
        raise ValueError("unsuccessful correction may not supervise residual")
    nominal = pair["perturbed_nominal"]
    residual = pair["residual_target"]
    corrected = pair["corrected_action"]
    if any(
        abs((source + delta) - target) > 1e-9
        for source, delta, target in zip(nominal, residual, corrected)
    ):
        raise ValueError("residual target does not reconstruct corrected action")
    if not any(abs(value) > 1e-12 for value in residual[:3]):
        raise ValueError("translation residual is degenerate")
    evidence = pair["physical_correction_evidence"]
    if evidence.get("independent_executions") is not True:
        raise ValueError("residual label lacks independent physical executions")
    if evidence.get("policy_input_simulator_truth") is not False:
        raise ValueError("simulator truth crossed the policy-input boundary")
    if (
        evidence.get("perturbed_evidence_path")
        == evidence.get("corrected_evidence_path")
        or evidence.get("perturbed_evidence_sha256")
        == evidence.get("corrected_evidence_sha256")
    ):
        raise ValueError("perturbed and corrected evidence are not independent")


def _capture(payload: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [
        capture
        for capture in payload["m2b_public_rgbd"]["captures"]
        if capture["label"] == label
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one public capture {label!r}")
    return matches[0]


def residual_sample(
    pair: dict[str, Any],
    payload: dict[str, Any],
    *,
    rgb_uri: str,
    depth_uri: str,
) -> QRMTrainingSampleV1:
    _validate_pair(pair)
    capture = _capture(payload, "after_recovery_retreat")
    public = payload["m2b_public_rgbd"]
    recovery = payload["m2b_recovery"]["wrong_object"]
    target_track_id = recovery["reassociated_target_track_id"]
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
                    public["camera_to_world_optical"],
                ),
                1.0,
                0.0,
                0.0,
                0.0,
            ],
        )
        for track in capture["tracks"]
    ]
    context = FailureContextV1(
        last_skill="REASSOCIATE_TARGET",
        previous_skill="REASSOCIATE_TARGET",
        expected_predicates=["grasped=true", "lifted=true"],
        observed_predicates=["target_reassociated=true"],
        predicate_residual=["regrasp_execution_pending=true"],
        failure_type=FailureType.WRONG_OBJECT,
        retry_count=1,
        attempted_recoveries=[
            "SAFE_PLACE_NON_TARGET",
            "REASSOCIATE_TARGET",
        ],
        last_recovery_result="IN_PROGRESS",
        last_action_summary="public target reassociated; regrasp correction pending",
        last_target_track_id=target_track_id,
    )
    observation = QRMObservationV1(
        episode_id=pair["pair_id"],
        step_id=0,
        timestamp_ns=capture["timestamp_ns"],
        instruction="Regrasp the reassociated public TaskSpec target safely.",
        task_target_track_id=target_track_id,
        rgb_uri=rgb_uri,
        depth_uri=depth_uri,
        camera_frame=public["camera_frame"],
        camera_intrinsics=public["camera_intrinsics"],
        camera_extrinsics_base_T_cam=[],
        gripper_state=0.0,
        current_skill_stage="REGRASP",
        perception_tracks=tracks,
        failure_context=context,
    )
    mask = [[1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]

    def chunk(values: list[float], *, residual: bool) -> CameraFrameActionChunkV1:
        return CameraFrameActionChunkV1(
            fps=1.0,
            values=[values],
            action_mask=mask,
            normalization_method="none",
            normalization_revision="m2b-physical-residual-v2",
            is_residual=residual,
        )

    return QRMTrainingSampleV1(
        sample_id=f"{pair['pair_id']}:masked-translation",
        episode_id=pair["pair_id"],
        seed=int(pair["scene_seed"]),
        split=scene_split(int(pair["scene_seed"])),
        observation=observation,
        coarse_intent=CoarseIntentV1(
            skill_type="REGRASP",
            target_track_id=target_track_id,
            grasp_family="top_down",
            recovery_mode="wrong_object",
            failure_type_aux=FailureType.WRONG_OBJECT,
        ),
        nominal_action_chunk=chunk(pair["perturbed_nominal"], residual=False),
        residual_action_chunk=chunk(pair["residual_target"], residual=True),
        target_action_chunk=chunk(pair["corrected_action"], residual=False),
        simulator_supervision={
            "training_and_evaluation_only": True,
            "teacher_used": False,
            "physical_correction_evidence": pair[
                "physical_correction_evidence"
            ],
        },
        provenance={
            "pair_id": pair["pair_id"],
            "label_source": "INDEPENDENT_PHYSICAL_PERTURBATION_CORRECTION",
            "action_frame": "m2b_policy_rgbd_optical",
            "supervised_dimensions": "dx,dy,dz",
            "base_to_camera_extrinsics": "ABSENT_NOT_GUESSED",
        },
        synthetic=False,
    )


def materialize_capture(
    pair: dict[str, Any],
    payload: dict[str, Any],
    *,
    host: str,
    asset_root: Path,
) -> tuple[str, str]:
    capture = _capture(payload, "after_recovery_retreat")
    target = asset_root / "residual" / pair["pair_id"]
    rgb = target / "rgb.png"
    depth = target / "depth.npy"
    evidence_path = pair["physical_correction_evidence"][
        "perturbed_evidence_path"
    ]
    for uri, destination, digest in (
        (capture["rgb_uri"], rgb, capture["rgb_sha256"]),
        (capture["depth_uri"], depth, capture["depth_sha256"]),
    ):
        if not destination.is_file() or hashlib.sha256(
            destination.read_bytes()
        ).hexdigest() != digest:
            _copy_asset(
                host=host,
                evidence_path=evidence_path,
                source_uri=uri,
                destination=destination,
                expected_sha256=digest,
            )
    return (
        f"dataset://residual/{pair['pair_id']}/rgb.png",
        f"dataset://residual/{pair['pair_id']}/depth.npy",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", required=True, type=Path)
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    samples = []
    quarantine = []
    for line in args.pairs.read_text().splitlines():
        if not line.strip():
            continue
        pair = json.loads(line)
        evidence_path = pair["physical_correction_evidence"][
            "perturbed_evidence_path"
        ]
        try:
            _validate_pair(pair)
            evidence = pair["physical_correction_evidence"]
            for path_key, digest_key in (
                ("perturbed_evidence_path", "perturbed_evidence_sha256"),
                ("corrected_evidence_path", "corrected_evidence_sha256"),
            ):
                if remote_sha256(args.host, evidence[path_key]) != evidence[digest_key]:
                    raise ValueError(
                        f"remote evidence hash changed: {evidence[path_key]}"
                    )
            payload = remote_json(args.host, evidence_path)
            rgb_uri, depth_uri = materialize_capture(
                pair, payload, host=args.host, asset_root=args.asset_root
            )
            samples.append(
                residual_sample(
                    pair, payload, rgb_uri=rgb_uri, depth_uri=depth_uri
                )
            )
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            quarantine.append(
                {
                    "pair_id": pair.get("pair_id", "UNKNOWN"),
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
    splits = Counter(sample.split for sample in samples)
    report = {
        "schema_version": "M2BResidualTrainingDatasetReportV1",
        "status": "PASS" if samples and not quarantine else "PARTIAL",
        "samples_valid": len(samples),
        "samples_quarantined": len(quarantine),
        "split_counts": dict(sorted(splits.items())),
        "supervised_dimensions": ["dx", "dy", "dz"],
        "masked_unsupervised_dimensions": [
            "r6d_0",
            "r6d_1",
            "r6d_2",
            "r6d_3",
            "r6d_4",
            "r6d_5",
            "gripper",
        ],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if samples else 1


if __name__ == "__main__":
    raise SystemExit(main())
