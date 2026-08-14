from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest
from pydantic import ValidationError

import xh_agent.perception.public_track_associator_v2 as association
from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationCaptureV2,
    PublicAssociationDeploymentBindingV2,
    PublicAssociationProtocolV2,
    PublicAssociationSessionReceiptV2,
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
    M2CQ012DeploymentManifestV4,
    M2CQ012TensorBindingV4,
    PublicAssociationReplayFrameV4,
    PublicDeclaredTargetAttributeBindingV4,
    associated_tracks_to_perception_tracks_v4,
    canonical_checkpoint_binding_sha256_v4,
    load_checkpoint_binding_v4,
    load_m2c_q012_checkpoint_v4,
    load_public_observation_v4,
)
from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
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


def deployment() -> PublicAssociationDeploymentBindingV2:
    payload: dict[str, object] = {
        "schema_version": "PublicAssociationDeploymentBindingV2",
        "associator_revision": "PublicTrackAssociatorV2",
        "associator_implementation_sha256": hashlib.sha256(
            Path(association.__file__).read_bytes()
        ).hexdigest(),
        "capture_source_implementation_sha256": "1" * 64,
        "protocol": protocol().model_dump(mode="json"),
        "protocol_sha256": canonical_sha256(protocol().model_dump(mode="json")),
        "assignment_objective": (
            "MAXIMUM_CARDINALITY_THEN_MINIMUM_TOTAL_QUANTIZED_COST_THEN_LEXICOGRAPHIC_V2"
        ),
        "association_gate_m": 0.12,
        "ambiguity_margin_m": 0.02,
        "cost_quantum_m": 0.000001,
        "max_consecutive_unmatched_captures": 2,
        "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
        "max_current_detections": 32,
    }
    payload["deployment_binding_sha256"] = canonical_sha256(payload)
    return PublicAssociationDeploymentBindingV2.model_validate(payload)


def session_receipt(
    frozen_journal: PublicProprioceptionJournalBindingV2,
    frozen_deployment: PublicAssociationDeploymentBindingV2,
) -> PublicAssociationSessionReceiptV2:
    payload: dict[str, object] = {
        "schema_version": "PublicAssociationSessionReceiptV2",
        "deployment_binding_sha256": frozen_deployment.deployment_binding_sha256,
        "capture_source_implementation_sha256": "1" * 64,
        "proprioception_journal_sha256": frozen_journal.journal_sha256,
        "capture_count": len(frozen_journal.captures),
        "first_capture_receipt_sha256": frozen_journal.captures[0].capture_receipt_sha256,
        "final_capture_receipt_sha256": frozen_journal.captures[-1].capture_receipt_sha256,
    }
    payload["session_receipt_sha256"] = canonical_sha256(payload)
    return PublicAssociationSessionReceiptV2.model_validate(payload)


def attribute_binding(attribute: str = "yellow") -> PublicDeclaredTargetAttributeBindingV4:
    payload: dict[str, object] = {
        "schema_version": "PublicDeclaredTargetAttributeBindingV4",
        "declared_target_attribute": attribute,
        "public_target_selector": f"visual_color={attribute}",
        "selector_source_implementation_sha256": "2" * 64,
        "task_spec_public_receipt_sha256": "3" * 64,
    }
    payload["binding_sha256"] = canonical_sha256(payload)
    return PublicDeclaredTargetAttributeBindingV4.model_validate(payload)


def observation_bundle() -> tuple[
    dict[str, object],
    PublicAssociationDeploymentBindingV2,
    PublicProprioceptionJournalBindingV2,
    PublicAssociationSessionReceiptV2,
    PublicDeclaredTargetAttributeBindingV4,
]:
    first = capture(100, [(0.0, "yellow", 0.8), (0.3, "blue", 0.95)])
    second = capture(
        200,
        [(0.01, "yellow", 0.9), (0.31, "blue", 0.94)],
        previous=first,
    )
    frozen_journal = journal([first, second])
    frozen_deployment = deployment()
    frozen_session = session_receipt(frozen_journal, frozen_deployment)
    frozen_attribute = attribute_binding()
    associator = PublicTrackAssociatorV2(
        expected_deployment=frozen_deployment,
        expected_deployment_binding_sha256=frozen_deployment.deployment_binding_sha256,
        expected_journal=frozen_journal,
        expected_session_receipt=frozen_session,
        expected_session_receipt_sha256=frozen_session.session_receipt_sha256,
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
    return payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute


def load_observation(payload: dict[str, object]):  # noqa: ANN202
    _, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = observation_bundle()
    return load_public_observation_v4(
        payload,
        **observation_kwargs(
            frozen_deployment,
            frozen_journal,
            frozen_session,
            frozen_attribute,
        ),
    )


def observation_kwargs(
    frozen_deployment: PublicAssociationDeploymentBindingV2,
    frozen_journal: PublicProprioceptionJournalBindingV2,
    frozen_session: PublicAssociationSessionReceiptV2,
    frozen_attribute: PublicDeclaredTargetAttributeBindingV4,
) -> dict[str, object]:
    return {
        "expected_deployment": frozen_deployment,
        "expected_deployment_binding_sha256": (frozen_deployment.deployment_binding_sha256),
        "expected_journal": frozen_journal,
        "expected_session_receipt": frozen_session,
        "expected_session_receipt_sha256": frozen_session.session_receipt_sha256,
        "expected_attribute_binding": frozen_attribute,
        "expected_attribute_binding_sha256": frozen_attribute.binding_sha256,
    }


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
        "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
        "max_raw_public_detections": 32,
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


def checkpoint_deployment(
    *,
    file_sha256: str,
    binding: M2CQ012CheckpointBindingV4,
) -> M2CQ012DeploymentManifestV4:
    payload: dict[str, object] = {
        "schema_version": "M2CQ012DeploymentManifestV4",
        "architecture_revision": "M2C_Q012_V4",
        "checkpoint_file_sha256": file_sha256,
        "checkpoint_binding_sha256": canonical_checkpoint_binding_sha256_v4(binding),
    }
    payload["deployment_manifest_sha256"] = canonical_sha256(payload)
    return M2CQ012DeploymentManifestV4.model_validate(payload)


def test_v4_observation_replays_complete_history_before_candidates() -> None:
    payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = (
        observation_bundle()
    )
    observation = load_public_observation_v4(
        payload,
        **observation_kwargs(frozen_deployment, frozen_journal, frozen_session, frozen_attribute),
    )
    assert len(observation.association_history) == 2
    assert observation.public_track_associator_revision == "PublicTrackAssociatorV2"
    assert [item.role for item in observation.candidate_payload.candidates] == [
        "ROLE_TARGET_ATTRIBUTE_MATCH",
        "ROLE_MANIPULABLE_OTHER",
    ]


def test_v4_observation_rejects_omitted_or_forged_replay_history() -> None:
    payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = (
        observation_bundle()
    )
    kwargs = observation_kwargs(frozen_deployment, frozen_journal, frozen_session, frozen_attribute)
    omitted = copy.deepcopy(payload)
    omitted["association_history"] = omitted["association_history"][1:]  # type: ignore[index]
    with pytest.raises(ValueError, match="external proprioception journal"):
        load_public_observation_v4(
            omitted,
            **kwargs,
        )

    forged = copy.deepcopy(payload)
    frame = forged["association_history"][0]  # type: ignore[index]
    frame["associated_tracks"][0]["track_id"] = "track-deadbeef"  # type: ignore[index]
    frame["associated_tracks_sha256"] = canonical_sha256(frame["associated_tracks"])  # type: ignore[index]
    with pytest.raises(ValueError, match="association replay differs at frame 0"):
        load_public_observation_v4(
            forged,
            **kwargs,
        )


def test_v4_observation_rejects_external_binding_and_projection_tamper() -> None:
    payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = (
        observation_bundle()
    )
    kwargs = observation_kwargs(frozen_deployment, frozen_journal, frozen_session, frozen_attribute)
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
    changed_raw = frozen_deployment.model_dump(mode="json")
    changed_raw["protocol"] = changed_protocol.model_dump(mode="json")
    changed_raw["protocol_sha256"] = canonical_sha256(changed_raw["protocol"])
    changed_raw["deployment_binding_sha256"] = canonical_sha256(
        {key: value for key, value in changed_raw.items() if key != "deployment_binding_sha256"}
    )
    changed_deployment = PublicAssociationDeploymentBindingV2.model_validate(changed_raw)
    with pytest.raises(ValueError, match="external expected digest"):
        load_public_observation_v4(
            payload,
            **{**kwargs, "expected_deployment": changed_deployment},
        )

    tampered = copy.deepcopy(payload)
    tampered["perception_tracks"][0]["category"] = "industrial_cylinder:green"  # type: ignore[index]
    with pytest.raises(ValueError, match="tracks differ from association replay"):
        load_public_observation_v4(
            tampered,
            **kwargs,
        )

    tampered = copy.deepcopy(payload)
    tampered["candidate_payload"]["candidates"][0]["track_id"] = "track-deadbeef"  # type: ignore[index]
    with pytest.raises(ValueError, match="not recomputable"):
        load_public_observation_v4(
            tampered,
            **kwargs,
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
    payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = (
        observation_bundle()
    )
    target = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index,assignment]
    target[path[-1]] = bad_value  # type: ignore[index]
    with pytest.raises(ValidationError):
        load_public_observation_v4(
            payload,
            **observation_kwargs(
                frozen_deployment, frozen_journal, frozen_session, frozen_attribute
            ),
        )


def test_v4_observation_forbids_identity_truth_and_extra_fields() -> None:
    payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = (
        observation_bundle()
    )
    payload["task_target_track_id"] = "track-secret"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_public_observation_v4(
            payload,
            **observation_kwargs(
                frozen_deployment, frozen_journal, frozen_session, frozen_attribute
            ),
        )


def test_v4_observation_requires_independently_frozen_attribute_and_nonempty_final() -> None:
    payload, frozen_deployment, frozen_journal, frozen_session, frozen_attribute = (
        observation_bundle()
    )
    kwargs = observation_kwargs(frozen_deployment, frozen_journal, frozen_session, frozen_attribute)
    tampered = copy.deepcopy(payload)
    tampered["declared_target_attribute"] = "blue"
    candidates = build_public_track_candidates_v4(
        [
            PerceptionTrackV1.model_validate(item)
            for item in tampered["perception_tracks"]  # type: ignore[union-attr]
        ],
        declared_target_attribute="blue",
    )
    tampered["candidate_payload"] = canonical_candidate_payload_v4(candidates)
    tampered["candidate_payload_sha256"] = canonical_candidate_sha256_v4(candidates)
    with pytest.raises(ValueError, match="public TaskSpec receipt"):
        load_public_observation_v4(tampered, **kwargs)

    with pytest.raises(ValueError, match="external expected digest"):
        load_public_observation_v4(
            payload,
            **{**kwargs, "expected_attribute_binding_sha256": "0" * 64},
        )

    empty = copy.deepcopy(payload)
    empty["association_history"][-1]["capture"]["detections"] = []  # type: ignore[index]
    with pytest.raises((ValidationError, ValueError)):
        load_public_observation_v4(empty, **kwargs)


def test_checkpoint_loader_binds_file_metadata_inventory_and_tensors(tmp_path: Path) -> None:
    arrays = {
        "encoder_weight": np.asarray([[1.0, 2.0]], dtype=np.float32),
        "pointer_bias": np.asarray([0.0] * 9, dtype=np.float32),
    }
    binding = checkpoint_binding(arrays)
    path = tmp_path / "checkpoint.npz"
    file_sha256 = save_checkpoint(path, arrays, binding)
    frozen_deployment = checkpoint_deployment(file_sha256=file_sha256, binding=binding)
    loaded = load_m2c_q012_checkpoint_v4(
        path,
        expected_deployment=frozen_deployment,
        expected_deployment_manifest_sha256=(frozen_deployment.deployment_manifest_sha256),
    )
    assert loaded.binding == binding
    assert loaded.file_sha256 == file_sha256
    assert np.array_equal(loaded.tensors["encoder_weight"], arrays["encoder_weight"])
    assert isinstance(loaded.tensors, MappingProxyType)
    with pytest.raises(ValueError, match="read-only"):
        loaded.tensors["encoder_weight"][0, 0] = 9.0
    with pytest.raises(TypeError):
        loaded.tensors["new"] = np.asarray([1.0])  # type: ignore[index]
    assert len(canonical_checkpoint_binding_sha256_v4(binding)) == 64

    substituted = checkpoint_deployment(file_sha256=file_sha256, binding=binding)
    with pytest.raises(ValueError, match="external expected digest"):
        load_m2c_q012_checkpoint_v4(
            path,
            expected_deployment=substituted,
            expected_deployment_manifest_sha256="0" * 64,
        )


def test_checkpoint_deployment_rejects_self_consistent_metadata_substitution(
    tmp_path: Path,
) -> None:
    arrays = {"pointer_bias": np.asarray([0.0] * 9, dtype=np.float32)}
    original_binding = checkpoint_binding(arrays)
    path = tmp_path / "checkpoint.npz"
    file_sha256 = save_checkpoint(path, arrays, original_binding)
    frozen_deployment = checkpoint_deployment(
        file_sha256=file_sha256,
        binding=original_binding,
    )

    substituted_arrays = {"pointer_bias": np.asarray([1.0] * 9, dtype=np.float32)}
    substituted_binding = checkpoint_binding(substituted_arrays)
    substituted_path = tmp_path / "substituted.npz"
    save_checkpoint(substituted_path, substituted_arrays, substituted_binding)
    substituted_file_sha = hashlib.sha256(substituted_path.read_bytes()).hexdigest()
    substituted_manifest = checkpoint_deployment(
        file_sha256=substituted_file_sha,
        binding=substituted_binding,
    )
    with pytest.raises(ValueError, match="external expected digest"):
        load_m2c_q012_checkpoint_v4(
            substituted_path,
            expected_deployment=substituted_manifest,
            expected_deployment_manifest_sha256=(frozen_deployment.deployment_manifest_sha256),
        )


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
    dummy_binding = checkpoint_binding({"pointer_bias": np.asarray([0.0] * 9, dtype=np.float32)})
    frozen_deployment = checkpoint_deployment(
        file_sha256="0" * 64,
        binding=dummy_binding,
    )
    with pytest.raises(ValueError, match="file SHA-256 mismatch"):
        load_m2c_q012_checkpoint_v4(
            path,
            expected_deployment=frozen_deployment,
            expected_deployment_manifest_sha256=(frozen_deployment.deployment_manifest_sha256),
        )
    assert not called


def test_checkpoint_metadata_and_tensor_tamper_fail_closed(tmp_path: Path) -> None:
    arrays = {"pointer_bias": np.asarray([0.0] * 9, dtype=np.float32)}
    binding = checkpoint_binding(arrays)

    tampered_arrays = {"pointer_bias": arrays["pointer_bias"].copy()}
    tampered_arrays["pointer_bias"][0] = 1.0
    path = tmp_path / "tensor-tamper.npz"
    file_sha256 = save_checkpoint(path, tampered_arrays, binding)
    frozen_deployment = checkpoint_deployment(file_sha256=file_sha256, binding=binding)
    with pytest.raises(ValueError, match="tensor SHA-256 differs"):
        load_m2c_q012_checkpoint_v4(
            path,
            expected_deployment=frozen_deployment,
            expected_deployment_manifest_sha256=frozen_deployment.deployment_manifest_sha256,
        )

    path = tmp_path / "inventory-tamper.npz"
    file_sha256 = save_checkpoint(
        path,
        {**arrays, "unexpected": np.asarray([1.0], dtype=np.float32)},
        binding,
    )
    frozen_deployment = checkpoint_deployment(file_sha256=file_sha256, binding=binding)
    with pytest.raises(ValueError, match="inventory differs"):
        load_m2c_q012_checkpoint_v4(
            path,
            expected_deployment=frozen_deployment,
            expected_deployment_manifest_sha256=frozen_deployment.deployment_manifest_sha256,
        )

    raw = binding.model_dump(mode="json")
    raw["metadata_sha256"] = "f" * 64
    path = tmp_path / "metadata-tamper.npz"
    np.savez(path, metadata_json=np.asarray(json.dumps(raw)), **arrays)
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    frozen_deployment = checkpoint_deployment(file_sha256=file_sha256, binding=binding)
    with pytest.raises(ValidationError, match="metadata digest mismatch"):
        load_m2c_q012_checkpoint_v4(
            path,
            expected_deployment=frozen_deployment,
            expected_deployment_manifest_sha256=frozen_deployment.deployment_manifest_sha256,
        )


def test_checkpoint_guard_rejects_cross_revision_symlink_and_hardlink(tmp_path: Path) -> None:
    arrays = {"pointer_bias": np.asarray([0.0] * 9, dtype=np.float32)}
    for key, bad in (
        ("checkpoint_schema_version", "QRMFormalCheckpointV3"),
        ("architecture_revision", "M2C_Q012_V3"),
        ("public_observation_revision", "PathBlockedPublicObservationV3"),
        ("public_track_associator_revision", "PublicTrackAssociator"),
        ("raw_detection_capacity_revision", "M2C_V4_RAW_PUBLIC_DETECTIONS_8_V0"),
        ("max_raw_public_detections", 8),
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
    frozen_deployment = checkpoint_deployment(file_sha256=file_sha256, binding=binding)
    symlink = tmp_path / "symlink.npz"
    symlink.symlink_to(original)
    with pytest.raises(OSError):
        load_m2c_q012_checkpoint_v4(
            symlink,
            expected_deployment=frozen_deployment,
            expected_deployment_manifest_sha256=frozen_deployment.deployment_manifest_sha256,
        )
    hardlink = tmp_path / "hardlink.npz"
    os.link(original, hardlink)
    with pytest.raises(ValueError, match="single-link regular file"):
        load_m2c_q012_checkpoint_v4(
            hardlink,
            expected_deployment=frozen_deployment,
            expected_deployment_manifest_sha256=frozen_deployment.deployment_manifest_sha256,
        )
