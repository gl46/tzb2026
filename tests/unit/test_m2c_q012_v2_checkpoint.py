from __future__ import annotations

import json

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.contracts import (
    PerceptionTrackV1,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.models_q012 import FormalModelId
from xh_agent.policy.qrm_lite.models_q012_v2 import (
    ARCHITECTURE_REVISION,
    CHECKPOINT_SCHEMA_VERSION,
    DESTINATION_LABELS,
    POINTER_LABELS,
    PUBLIC_TRACK_SLOT_COUNT,
    PUBLIC_TRACK_SLOT_FEATURE_DIM,
    TENSOR_ATTRIBUTES,
    build_formal_model_v2,
    load_formal_checkpoint_v2,
    save_formal_checkpoint_v2,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import (
    PUBLIC_TRACK_ENCODING_REVISION,
    PUBLIC_TRACK_NORMALIZATION,
    PUBLIC_TRACK_POSE_FRAME,
    PUBLIC_TRACK_SLOT_FEATURE_NAMES,
)


def observation(track_ids: list[str]) -> QRMObservationV1:
    return QRMObservationV1(
        episode_id="m2c-v2-test",
        step_id=1,
        timestamp_ns=1,
        instruction="clear the public blocker and regrasp the target",
        task_target_track_id="track-task",
        current_skill_stage="RECOVERY",
        camera_frame="policy_rgbd_optical",
        camera_intrinsics=[1.0] * 9,
        perception_tracks=[
            PerceptionTrackV1(
                track_id=track_id,
                category="yellow",
                confidence=0.9,
                pose_xyzquat=[0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0],
            )
            for track_id in track_ids
        ],
    )


def checkpoint_payload(path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as payload:
        return {key: np.asarray(payload[key]).copy() for key in payload.files}


def write_payload(path, payload: dict[str, np.ndarray]) -> None:
    np.savez(path, **payload)


def mutate_metadata(payload: dict[str, np.ndarray], key: str, value: object) -> None:
    metadata = json.loads(str(payload["metadata_json"].item()))
    metadata[key] = value
    payload["metadata_json"] = np.asarray(
        json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    )


def test_v2_architecture_has_frozen_public_slot_and_head_shapes() -> None:
    model = build_formal_model_v2(FormalModelId.Q2)
    assert PUBLIC_TRACK_SLOT_COUNT == 8
    assert PUBLIC_TRACK_SLOT_FEATURE_DIM == 13
    assert len(PUBLIC_TRACK_SLOT_FEATURE_NAMES) == 13
    assert model.base_context_dim == 113
    assert model.context_dim == 217
    assert model.coarse.out_dim == 73
    assert POINTER_LABELS == (
        "SLOT_0",
        "SLOT_1",
        "SLOT_2",
        "SLOT_3",
        "SLOT_4",
        "SLOT_5",
        "SLOT_6",
        "SLOT_7",
        "NONE",
    )
    assert DESTINATION_LABELS == (
        "BIN_CELL_0",
        "BIN_CELL_1",
        "BIN_CELL_2",
        "BIN_CELL_3",
        "BIN_CELL_4",
        "BIN_CELL_5",
        "NONE",
    )
    assert model.tensor_shapes().as_dict() == {
        "coarse_w1": (217, 256),
        "coarse_b1": (256,),
        "coarse_w2": (256, 73),
        "coarse_b2": (73,),
        "pointer_w": (256, 9),
        "pointer_b": (9,),
        "destination_w": (256, 7),
        "destination_b": (7,),
        "mlp_w1": (257, 512),
        "mlp_b1": (512,),
        "mlp_w2": (512, 40),
        "mlp_b2": (40,),
    }


def test_v2_pointer_is_masked_and_ties_choose_lower_canonical_slot() -> None:
    model = build_formal_model_v2(FormalModelId.Q0)
    for name in TENSOR_ATTRIBUTES:
        owner, attribute = TENSOR_ATTRIBUTES[name]
        target = model if owner is None else getattr(model, owner)
        setattr(target, attribute, np.zeros_like(getattr(target, attribute)))

    no_tracks = model.predict(observation([]))
    assert no_tracks.coarse is not None
    assert no_tracks.coarse.target_track_id is None
    assert no_tracks.pointer_probabilities is not None
    assert np.array_equal(
        no_tracks.pointer_probabilities,
        np.asarray([0.0] * 8 + [1.0]),
    )

    tied = model.predict(observation(["track-z", "track-a"]))
    assert tied.coarse is not None
    assert tied.coarse.target_track_id == "track-a"
    assert tied.coarse.destination_cell == "BIN_CELL_0"
    assert tied.meta["target_track_id_provenance"] == "MODEL"
    assert tied.meta["destination_cell_provenance"] == "MODEL"


def test_v2_pointer_never_selects_truncated_ninth_track() -> None:
    model = build_formal_model_v2(FormalModelId.Q0)
    model.pointer_w[:] = 0.0
    model.pointer_b[:] = -1.0
    model.pointer_b[7] = 5.0
    model.pointer_b[8] = 4.0
    track_ids = [f"track-{index}" for index in range(9)]
    output = model.predict(observation(list(reversed(track_ids))))
    assert output.coarse is not None
    assert output.coarse.target_track_id == "track-7"
    assert output.coarse.target_track_id != "track-8"


def test_v2_checkpoint_exact_round_trip_and_metadata(tmp_path) -> None:
    source = build_formal_model_v2(FormalModelId.Q2)
    checkpoint = tmp_path / "Q2-m2c-v2.npz"
    save_formal_checkpoint_v2(checkpoint, source)
    loaded = load_formal_checkpoint_v2(
        checkpoint,
        expected_model_id=FormalModelId.Q2.value,
    )
    assert loaded.meta_checkpoint_revision == ARCHITECTURE_REVISION
    assert loaded.checkpoint_metadata() == source.checkpoint_metadata()
    assert loaded.checkpoint_metadata()["checkpoint_schema_version"] == (
        CHECKPOINT_SCHEMA_VERSION
    )
    assert loaded.checkpoint_metadata()["slot_feature_names"] == list(
        PUBLIC_TRACK_SLOT_FEATURE_NAMES
    )
    assert loaded.checkpoint_metadata()["public_track_encoding_revision"] == (
        PUBLIC_TRACK_ENCODING_REVISION
    )
    assert loaded.checkpoint_metadata()["public_track_pose_frame"] == (
        PUBLIC_TRACK_POSE_FRAME
    )
    assert loaded.checkpoint_metadata()["public_track_normalization"] == (
        PUBLIC_TRACK_NORMALIZATION
    )
    for name, (owner, attribute) in TENSOR_ATTRIBUTES.items():
        source_owner = source if owner is None else getattr(source, owner)
        loaded_owner = loaded if owner is None else getattr(loaded, owner)
        assert np.array_equal(
            getattr(source_owner, attribute),
            getattr(loaded_owner, attribute),
        ), name


@pytest.mark.parametrize("tensor_name", sorted(TENSOR_ATTRIBUTES))
def test_v2_checkpoint_rejects_every_tensor_shape_mismatch(
    tmp_path,
    tensor_name: str,
) -> None:
    checkpoint = tmp_path / "Q2-m2c-v2.npz"
    save_formal_checkpoint_v2(
        checkpoint,
        build_formal_model_v2(FormalModelId.Q2),
    )
    payload = checkpoint_payload(checkpoint)
    value = payload[tensor_name]
    payload[tensor_name] = np.zeros(value.shape + (1,))
    write_payload(checkpoint, payload)
    with pytest.raises(ValueError, match=f"tensor {tensor_name} shape mismatch"):
        load_formal_checkpoint_v2(checkpoint)


@pytest.mark.parametrize("tensor_name", sorted(TENSOR_ATTRIBUTES))
def test_v2_checkpoint_rejects_nonfinite_tensor(
    tmp_path,
    tensor_name: str,
) -> None:
    checkpoint = tmp_path / "Q2-m2c-v2.npz"
    save_formal_checkpoint_v2(
        checkpoint,
        build_formal_model_v2(FormalModelId.Q2),
    )
    payload = checkpoint_payload(checkpoint)
    value = payload[tensor_name].copy()
    value.flat[0] = np.inf
    payload[tensor_name] = value
    write_payload(checkpoint, payload)
    with pytest.raises(ValueError, match=f"tensor {tensor_name} is non-finite"):
        load_formal_checkpoint_v2(checkpoint)


@pytest.mark.parametrize(
    ("metadata_key", "bad_value"),
    [
        ("checkpoint_schema_version", "QRMFormalCheckpointV1"),
        ("architecture_revision", "M2B_Q012_V1"),
        ("base_context_dim", 110),
        ("context_dim", 113),
        ("hidden_dim", 255),
        ("public_track_slot_count", 9),
        ("public_track_slot_feature_dim", 12),
        ("public_track_encoding_revision", "UNKNOWN"),
        ("public_track_pose_frame", "guessed_world"),
        ("public_track_normalization", "guessed"),
        ("slot_feature_names", ["unknown"] * 13),
        ("pointer_labels", list(reversed(POINTER_LABELS))),
        ("destination_labels", list(reversed(DESTINATION_LABELS))),
        ("skill_labels", ["OBSERVE"]),
        ("context_skill_vocab", ["UNKNOWN"]),
        ("tensor_shapes", {}),
    ],
)
def test_v2_checkpoint_rejects_any_semantic_metadata_mismatch(
    tmp_path,
    metadata_key: str,
    bad_value: object,
) -> None:
    checkpoint = tmp_path / "Q2-m2c-v2.npz"
    save_formal_checkpoint_v2(
        checkpoint,
        build_formal_model_v2(FormalModelId.Q2),
    )
    payload = checkpoint_payload(checkpoint)
    mutate_metadata(payload, metadata_key, bad_value)
    write_payload(checkpoint, payload)
    with pytest.raises(ValueError, match="metadata/layout mismatch"):
        load_formal_checkpoint_v2(checkpoint)


def test_v2_checkpoint_rejects_missing_unknown_and_wrong_model(tmp_path) -> None:
    checkpoint = tmp_path / "Q2-m2c-v2.npz"
    save_formal_checkpoint_v2(
        checkpoint,
        build_formal_model_v2(FormalModelId.Q2),
    )
    payload = checkpoint_payload(checkpoint)
    payload.pop("pointer_b")
    write_payload(checkpoint, payload)
    with pytest.raises(ValueError, match="missing fields"):
        load_formal_checkpoint_v2(checkpoint)

    save_formal_checkpoint_v2(
        checkpoint,
        build_formal_model_v2(FormalModelId.Q2),
    )
    payload = checkpoint_payload(checkpoint)
    payload["unexpected"] = np.zeros(1)
    write_payload(checkpoint, payload)
    with pytest.raises(ValueError, match="unsupported fields"):
        load_formal_checkpoint_v2(checkpoint)

    save_formal_checkpoint_v2(
        checkpoint,
        build_formal_model_v2(FormalModelId.Q2),
    )
    with pytest.raises(ValueError, match="model mismatch"):
        load_formal_checkpoint_v2(
            checkpoint,
            expected_model_id=FormalModelId.Q1.value,
        )
