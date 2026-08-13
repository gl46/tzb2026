from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationCaptureV2,
    PublicAssociationProtocolV2,
    PublicBBoxOrMaskV2,
    PublicDetectionAttributesV2,
    PublicProprioceptionCaptureBindingV2,
    PublicProprioceptionIntervalV2,
    PublicProprioceptionJournalBindingV2,
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
    PublicTrackAssociatorV2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    M2CQ012CheckpointBindingV4,
    M2CQ012TensorBindingV4,
    PublicAssociationReplayFrameV4,
    associated_tracks_to_perception_tracks_v4,
    canonical_checkpoint_binding_sha256_v4,
    load_checkpoint_binding_v4,
    load_m2c_q012_checkpoint_v4,
    load_public_observation_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)


IDENTITY_TRANSFORM = [
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
]


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def protocol() -> PublicAssociationProtocolV2:
    return PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=IDENTITY_TRANSFORM,
        calibration_sha256=hashlib.sha256(
            json.dumps(IDENTITY_TRANSFORM, separators=(",", ":")).encode("ascii")
        ).hexdigest(),
    )


def proprio(timestamp_ns: int) -> PublicRobotProprioceptionV2:
    return PublicRobotProprioceptionV2(
        timestamp_ns=timestamp_ns,
        world_frame="world",
        end_effector_position_world_m=[0.0, 0.0, 0.8],
        end_effector_orientation_world_xyzw=[0.0, 0.0, 0.0, 1.0],
        gripper_width_m=0.04,
        gripper_closed=False,
    )


def detection(
    timestamp_ns: int,
    x: float,
    color: str,
    *,
    confidence: float,
) -> PublicRGBDDetectionV2:
    return PublicRGBDDetectionV2(
        timestamp_ns=timestamp_ns,
        frame_id="policy_rgbd_optical",
        category="industrial_cylinder",
        attributes=PublicDetectionAttributesV2(visual_color=color),
        position_3d=[x, 0.0, 0.5],
        confidence=confidence,
        bbox_or_mask=PublicBBoxOrMaskV2(x=1, y=2, width=3, height=4),
        visibility=1.0,
        covariance_or_quality={"component_pixels": 100.0},
    )


def capture(
    timestamp_ns: int,
    items: list[tuple[float, str, float]],
    *,
    previous: PublicAssociationCaptureV2 | None = None,
) -> PublicAssociationCaptureV2:
    timestamps = [timestamp_ns] if previous is None else [previous.timestamp_ns, timestamp_ns]
    samples = [proprio(value) for value in timestamps]
    interval = PublicProprioceptionIntervalV2(
        start_capture_timestamp_ns=timestamps[0],
        end_capture_timestamp_ns=timestamp_ns,
        expected_sample_timestamps_ns=timestamps,
        samples=samples,
        samples_sha256=canonical_sha256([sample.model_dump(mode="json") for sample in samples]),
    )
    payload: dict[str, object] = {
        "schema_version": "PublicAssociationCaptureV2",
        "timestamp_ns": timestamp_ns,
        "protocol": protocol().model_dump(mode="json"),
        "previous_capture_receipt_sha256": (previous.capture_receipt_sha256 if previous else None),
        "detections": [
            detection(timestamp_ns, x, color, confidence=confidence).model_dump(mode="json")
            for x, color, confidence in items
        ],
        "proprioception_interval": interval.model_dump(mode="json"),
        "last_physically_executed_public_skill": None,
    }
    payload["capture_receipt_sha256"] = canonical_sha256(payload)
    return PublicAssociationCaptureV2.model_validate(payload)


def journal(
    captures: list[PublicAssociationCaptureV2],
) -> PublicProprioceptionJournalBindingV2:
    payload: dict[str, object] = {
        "schema_version": "PublicProprioceptionJournalBindingV2",
        "protocol_sha256": canonical_sha256(protocol().model_dump(mode="json")),
        "source_implementation_sha256": "1" * 64,
        "captures": [
            PublicProprioceptionCaptureBindingV2(
                capture_timestamp_ns=item.timestamp_ns,
                previous_capture_receipt_sha256=item.previous_capture_receipt_sha256,
                capture_receipt_sha256=item.capture_receipt_sha256,
                expected_sample_timestamps_ns=(
                    item.proprioception_interval.expected_sample_timestamps_ns
                ),
                samples_sha256=item.proprioception_interval.samples_sha256,
            ).model_dump(mode="json")
            for item in captures
        ],
    }
    payload["journal_sha256"] = canonical_sha256(payload)
    return PublicProprioceptionJournalBindingV2.model_validate(payload)


def observation_bundle() -> tuple[
    dict[str, object],
    PublicAssociationProtocolV2,
    PublicProprioceptionJournalBindingV2,
]:
    first = capture(100, [(0.0, "yellow", 0.8), (0.3, "blue", 0.95)])
    second = capture(
        200,
        [(0.01, "yellow", 0.9), (0.31, "blue", 0.94)],
        previous=first,
    )
    frozen_journal = journal([first, second])
    associator = PublicTrackAssociatorV2(
        expected_protocol=protocol(),
        expected_journal=frozen_journal,
    )
    frames: list[PublicAssociationReplayFrameV4] = []
    for item in (first, second):
        associated = associator.associate(item)
        frames.append(
            PublicAssociationReplayFrameV4(
                capture=item,
                associated_tracks=associated,
                associated_tracks_sha256=canonical_sha256(
                    [track.model_dump(mode="json") for track in associated]
                ),
            )
        )
    tracks = associated_tracks_to_perception_tracks_v4(frames[-1].associated_tracks)
    candidates = build_public_track_candidates_v4(
        tracks,
        declared_target_attribute="yellow",
    )
    payload: dict[str, object] = {
        "schema_version": "PathBlockedPublicObservationV4",
        "observation_id": "fresh-v4-observation",
        "captured_at_ns": second.timestamp_ns,
        "source": "PUBLIC_RGBD",
        "fresh": True,
        "rgb_uri": "dataset://policy/rgb/0001.png",
        "depth_uri": "dataset://policy/depth/0001.npy",
        "rgb_sha256": "a" * 64,
        "depth_sha256": "b" * 64,
        "capture_receipt_sha256": second.capture_receipt_sha256,
        "public_track_associator_revision": "PublicTrackAssociatorV2",
        "camera_frame": protocol().declared_camera_frame,
        "position_units": "m",
        "calibration_sha256": protocol().calibration_sha256,
        "association_history": [frame.model_dump(mode="json") for frame in frames],
        "perception_tracks": [track.model_dump(mode="json") for track in tracks],
        "declared_target_attribute": "yellow",
        "candidate_payload": canonical_candidate_payload_v4(candidates),
        "candidate_payload_sha256": canonical_candidate_sha256_v4(candidates),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "task_target_track_id_used_for_candidates": False,
    }
    return payload, protocol(), frozen_journal


def load_observation(payload: dict[str, object]):  # noqa: ANN202
    _, expected_protocol, expected_journal = observation_bundle()
    return load_public_observation_v4(
        payload,
        expected_protocol=expected_protocol,
        expected_journal=expected_journal,
    )


def tensor_sha256(value: np.ndarray) -> str:
    return hashlib.sha256(value.tobytes(order="C")).hexdigest()


def checkpoint_binding(
    arrays: dict[str, np.ndarray],
    **updates: object,
) -> M2CQ012CheckpointBindingV4:
    payload: dict[str, object] = {
        "checkpoint_schema_version": "QRMFormalCheckpointV4",
        "architecture_revision": "M2C_Q012_V4",
        "public_observation_revision": "PathBlockedPublicObservationV4",
        "public_track_associator_revision": "PublicTrackAssociatorV2",
        "public_track_candidate_revision": "PublicTrackCandidateV4",
        "public_track_candidate_count": 8,
        "pointer_class_count": 9,
        "recapture_policy": "NONE",
        "tensors": [
            M2CQ012TensorBindingV4(
                name=name,
                shape=list(value.shape),
                dtype=str(value.dtype),
                sha256=tensor_sha256(value),
            ).model_dump(mode="json")
            for name, value in sorted(arrays.items())
        ],
    }
    payload.update(updates)
    payload["metadata_sha256"] = canonical_sha256(payload)
    return M2CQ012CheckpointBindingV4.model_validate(payload)


def save_checkpoint(
    path: Path,
    arrays: dict[str, np.ndarray],
    binding: M2CQ012CheckpointBindingV4,
) -> str:
    np.savez(
        path,
        metadata_json=np.asarray(
            json.dumps(binding.model_dump(mode="json"), separators=(",", ":"))
        ),
        **arrays,
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_observation_replays_complete_history_before_candidates() -> None:
    payload, expected_protocol, expected_journal = observation_bundle()
    observation = load_public_observation_v4(
        payload,
        expected_protocol=expected_protocol,
        expected_journal=expected_journal,
    )
    assert len(observation.association_history) == 2
    assert observation.public_track_associator_revision == "PublicTrackAssociatorV2"
    assert [item.role for item in observation.candidate_payload.candidates] == [
        "ROLE_TARGET_ATTRIBUTE_MATCH",
        "ROLE_MANIPULABLE_OTHER",
    ]


def test_v4_observation_rejects_omitted_or_forged_replay_history() -> None:
    payload, expected_protocol, expected_journal = observation_bundle()
    omitted = copy.deepcopy(payload)
    omitted["association_history"] = omitted["association_history"][1:]  # type: ignore[index]
    with pytest.raises(ValueError, match="external proprioception journal"):
        load_public_observation_v4(
            omitted,
            expected_protocol=expected_protocol,
            expected_journal=expected_journal,
        )

    forged = copy.deepcopy(payload)
    frame = forged["association_history"][0]  # type: ignore[index]
    frame["associated_tracks"][0]["track_id"] = "track-deadbeef"  # type: ignore[index]
    frame["associated_tracks_sha256"] = canonical_sha256(frame["associated_tracks"])  # type: ignore[index]
    with pytest.raises(ValueError, match="association replay differs at frame 0"):
        load_public_observation_v4(
            forged,
            expected_protocol=expected_protocol,
            expected_journal=expected_journal,
        )


def test_v4_observation_rejects_external_binding_and_projection_tamper() -> None:
    payload, expected_protocol, expected_journal = observation_bundle()
    changed_transform = [*IDENTITY_TRANSFORM]
    changed_transform[3] = 0.01
    changed_protocol = PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=changed_transform,
        calibration_sha256=hashlib.sha256(
            json.dumps(changed_transform, separators=(",", ":")).encode("ascii")
        ).hexdigest(),
    )
    with pytest.raises(ValueError, match="external protocol binding"):
        load_public_observation_v4(
            payload,
            expected_protocol=changed_protocol,
            expected_journal=expected_journal,
        )

    tampered = copy.deepcopy(payload)
    tampered["perception_tracks"][0]["category"] = "industrial_cylinder:green"  # type: ignore[index]
    with pytest.raises(ValueError, match="tracks differ from association replay"):
        load_public_observation_v4(
            tampered,
            expected_protocol=expected_protocol,
            expected_journal=expected_journal,
        )

    tampered = copy.deepcopy(payload)
    tampered["candidate_payload"]["candidates"][0]["track_id"] = "track-deadbeef"  # type: ignore[index]
    with pytest.raises(ValueError, match="not recomputable"):
        load_public_observation_v4(
            tampered,
            expected_protocol=expected_protocol,
            expected_journal=expected_journal,
        )


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
    payload, expected_protocol, expected_journal = observation_bundle()
    target = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = bad_value  # type: ignore[index]
    with pytest.raises(ValidationError):
        load_public_observation_v4(
            payload,
            expected_protocol=expected_protocol,
            expected_journal=expected_journal,
        )


def test_v4_observation_forbids_identity_truth_and_extra_fields() -> None:
    payload, expected_protocol, expected_journal = observation_bundle()
    payload["task_target_track_id"] = "track-secret"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_public_observation_v4(
            payload,
            expected_protocol=expected_protocol,
            expected_journal=expected_journal,
        )


def test_checkpoint_loader_binds_file_metadata_inventory_and_tensors(tmp_path: Path) -> None:
    arrays = {
        "encoder_weight": np.asarray([[1.0, 2.0]], dtype=np.float32),
        "pointer_bias": np.asarray([0.0] * 9, dtype=np.float32),
    }
    binding = checkpoint_binding(arrays)
    path = tmp_path / "checkpoint.npz"
    file_sha256 = save_checkpoint(path, arrays, binding)
    loaded = load_m2c_q012_checkpoint_v4(path, expected_file_sha256=file_sha256)
    assert loaded.binding == binding
    assert loaded.file_sha256 == file_sha256
    assert np.array_equal(loaded.tensors["encoder_weight"], arrays["encoder_weight"])
    assert len(canonical_checkpoint_binding_sha256_v4(binding)) == 64


def test_checkpoint_file_hash_is_checked_before_npz_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "not-a-checkpoint.npz"
    path.write_bytes(b"not an npz")
    called = False

    def forbidden_load(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("np.load must not run before the external file digest passes")

    monkeypatch.setattr(np, "load", forbidden_load)
    with pytest.raises(ValueError, match="file SHA-256 mismatch"):
        load_m2c_q012_checkpoint_v4(path, expected_file_sha256="0" * 64)
    assert not called


def test_checkpoint_metadata_and_tensor_tamper_fail_closed(tmp_path: Path) -> None:
    arrays = {"pointer_bias": np.asarray([0.0] * 9, dtype=np.float32)}
    binding = checkpoint_binding(arrays)

    tampered_arrays = {"pointer_bias": arrays["pointer_bias"].copy()}
    tampered_arrays["pointer_bias"][0] = 1.0
    path = tmp_path / "tensor-tamper.npz"
    file_sha256 = save_checkpoint(path, tampered_arrays, binding)
    with pytest.raises(ValueError, match="tensor SHA-256 differs"):
        load_m2c_q012_checkpoint_v4(path, expected_file_sha256=file_sha256)

    path = tmp_path / "inventory-tamper.npz"
    file_sha256 = save_checkpoint(
        path,
        {**arrays, "unexpected": np.asarray([1.0], dtype=np.float32)},
        binding,
    )
    with pytest.raises(ValueError, match="inventory differs"):
        load_m2c_q012_checkpoint_v4(path, expected_file_sha256=file_sha256)

    raw = binding.model_dump(mode="json")
    raw["metadata_sha256"] = "f" * 64
    path = tmp_path / "metadata-tamper.npz"
    np.savez(path, metadata_json=np.asarray(json.dumps(raw)), **arrays)
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValidationError, match="metadata digest mismatch"):
        load_m2c_q012_checkpoint_v4(path, expected_file_sha256=file_sha256)


def test_checkpoint_guard_rejects_cross_revision_symlink_and_hardlink(tmp_path: Path) -> None:
    arrays = {"pointer_bias": np.asarray([0.0] * 9, dtype=np.float32)}
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
        payload = checkpoint_binding(arrays).model_dump(mode="json")
        payload[key] = bad
        payload["metadata_sha256"] = canonical_sha256(
            {name: value for name, value in payload.items() if name != "metadata_sha256"}
        )
        with pytest.raises(ValidationError):
            load_checkpoint_binding_v4(payload)

    binding = checkpoint_binding(arrays)
    original = tmp_path / "checkpoint.npz"
    file_sha256 = save_checkpoint(original, arrays, binding)
    symlink = tmp_path / "symlink.npz"
    symlink.symlink_to(original)
    with pytest.raises(OSError):
        load_m2c_q012_checkpoint_v4(symlink, expected_file_sha256=file_sha256)
    hardlink = tmp_path / "hardlink.npz"
    os.link(original, hardlink)
    with pytest.raises(ValueError, match="single-link regular file"):
        load_m2c_q012_checkpoint_v4(hardlink, expected_file_sha256=file_sha256)
