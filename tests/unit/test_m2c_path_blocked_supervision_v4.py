from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    M2CQ012CheckpointBindingV4,
    PathBlockedPublicObservationV4,
    canonical_checkpoint_binding_sha256_v4,
    load_checkpoint_binding_v4,
    load_public_observation_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)


def observation_payload() -> dict[str, object]:
    tracks = [
        PerceptionTrackV1(
            track_id="track-a",
            category="industrial_cylinder:yellow",
            confidence=0.9,
            pose_xyzquat=[0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0],
        ),
        PerceptionTrackV1(
            track_id="track-b",
            category="industrial_cylinder:blue",
            confidence=0.95,
            pose_xyzquat=[0.2, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0],
        ),
    ]
    candidates = build_public_track_candidates_v4(
        tracks,
        declared_target_attribute="yellow",
    )
    return {
        "schema_version": "PathBlockedPublicObservationV4",
        "observation_id": "fresh-v4-observation",
        "captured_at_ns": 100,
        "source": "PUBLIC_RGBD",
        "fresh": True,
        "rgb_uri": "dataset://policy/rgb/0001.png",
        "depth_uri": "dataset://policy/depth/0001.npy",
        "rgb_sha256": "a" * 64,
        "depth_sha256": "b" * 64,
        "capture_receipt_sha256": "c" * 64,
        "public_track_associator_revision": "PublicTrackAssociatorV2",
        "camera_frame": "policy_rgbd_optical",
        "position_units": "m",
        "calibration_sha256": "d" * 64,
        "perception_tracks": [track.model_dump(mode="json") for track in tracks],
        "declared_target_attribute": "yellow",
        "candidate_payload": canonical_candidate_payload_v4(candidates),
        "candidate_payload_sha256": canonical_candidate_sha256_v4(candidates),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "task_target_track_id_used_for_candidates": False,
    }


def checkpoint_payload() -> dict[str, object]:
    return {
        "checkpoint_schema_version": "QRMFormalCheckpointV4",
        "architecture_revision": "M2C_Q012_V4",
        "public_observation_revision": "PathBlockedPublicObservationV4",
        "public_track_associator_revision": "PublicTrackAssociatorV2",
        "public_track_candidate_revision": "PublicTrackCandidateV4",
        "public_track_candidate_count": 8,
        "pointer_class_count": 9,
        "recapture_policy": "NONE",
    }


def test_v4_observation_recomputes_candidates_and_binds_tracker_protocol() -> None:
    observation = load_public_observation_v4(observation_payload())
    assert observation.schema_version == "PathBlockedPublicObservationV4"
    assert observation.public_track_associator_revision == "PublicTrackAssociatorV2"
    assert observation.candidate_payload.schema_version == "PublicTrackCandidateV4"
    assert observation.candidate_payload.checkpoint_architecture_revision == "M2C_Q012_V4"
    assert [item.track_id for item in observation.candidate_payload.candidates] == [
        "track-a",
        "track-b",
    ]


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("schema_version",), "PathBlockedPublicObservationV3"),
        (("public_track_associator_revision",), "PublicTrackAssociator"),
        (("candidate_payload", "schema_version"), "PublicTrackCandidateV3"),
        (("candidate_payload", "checkpoint_architecture_revision"), "M2C_Q012_V3"),
        (("position_units",), "cm"),
        (("teacher_used",), True),
        (("privileged_truth_policy_input",), True),
        (("task_target_track_id_used_for_candidates",), True),
    ],
)
def test_v4_observation_rejects_cross_revision_and_forbidden_flags(
    path: tuple[str, ...],
    bad_value: object,
) -> None:
    payload = copy.deepcopy(observation_payload())
    target = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = bad_value  # type: ignore[index]
    with pytest.raises(ValidationError):
        load_public_observation_v4(payload)


def test_v4_observation_rejects_candidate_tamper_hash_tamper_and_extra_fields() -> None:
    payload = copy.deepcopy(observation_payload())
    payload["candidate_payload"]["candidates"][0]["track_id"] = "track-forged"  # type: ignore[index]
    with pytest.raises(ValidationError, match="not recomputable"):
        PathBlockedPublicObservationV4.model_validate(payload)

    payload = copy.deepcopy(observation_payload())
    payload["candidate_payload_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="SHA-256 mismatch"):
        PathBlockedPublicObservationV4.model_validate(payload)

    payload = copy.deepcopy(observation_payload())
    payload["task_target_track_id"] = "track-a"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PathBlockedPublicObservationV4.model_validate(payload)


def test_m2c_q012_v4_checkpoint_guard_rejects_every_cross_revision() -> None:
    binding = load_checkpoint_binding_v4(checkpoint_payload())
    assert isinstance(binding, M2CQ012CheckpointBindingV4)
    assert len(canonical_checkpoint_binding_sha256_v4(binding)) == 64
    for key, bad in (
        ("checkpoint_schema_version", "QRMFormalCheckpointV3"),
        ("architecture_revision", "M2C_Q012_V3"),
        ("public_observation_revision", "PathBlockedPublicObservationV3"),
        ("public_track_associator_revision", "PublicTrackAssociator"),
        ("public_track_candidate_revision", "PublicTrackCandidateV3"),
        ("public_track_candidate_count", 9),
        ("pointer_class_count", 8),
        ("recapture_policy", "LATEST"),
    ):
        payload = checkpoint_payload()
        payload[key] = bad
        with pytest.raises(ValidationError):
            load_checkpoint_binding_v4(payload)
    payload = checkpoint_payload()
    payload["teacher_used"] = False
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_checkpoint_binding_v4(payload)
