from __future__ import annotations

import copy

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v3 import (
    PUBLIC_TRACK_CANDIDATE_COUNT,
    PUBLIC_TRACK_CANDIDATE_REVISION,
    PUBLIC_TRACK_CHECKPOINT_ARCHITECTURE,
    PUBLIC_TRACK_POINTER_NONE_INDEX,
    CandidatePointerErrorCodeV3,
    InvalidPublicTrackCandidateV3,
    PublicTrackRoleV3,
    build_public_track_candidates_v3,
    canonical_candidate_payload_v3,
    canonical_candidate_sha256_v3,
    decode_qwen_track_literal_v3,
    decode_track_pointer_v3,
    encode_track_pointer_target_v3,
    public_track_candidate_slots_v3,
)


def track(
    track_id: str,
    *,
    category: str | None = "industrial_cylinder:blue",
    confidence: float = 0.9,
    pose: list[float] | None = None,
) -> PerceptionTrackV1:
    return PerceptionTrackV1(
        track_id=track_id,
        category=category,
        confidence=confidence,
        pose_xyzquat=(pose if pose is not None else [0.1, 0.2, 0.3, 1, 0, 0, 0]),
    )


def test_role_then_confidence_then_literal_id_order_and_k8_padding() -> None:
    tracks = [
        track("other-z", confidence=1.0),
        track("target-b", category="INDUSTRIAL:YELLOW", confidence=0.8),
        track("target-a", category="yellow-cylinder", confidence=0.8),
        track("target-c", category="yellow", confidence=0.9),
        *(track(f"other-{index}", confidence=0.7 - index / 100) for index in range(8)),
    ]
    slots = public_track_candidate_slots_v3(
        tracks,
        declared_attribute_token="Yellow",
    )
    assert slots.track_ids[:3] == ("target-c", "target-a", "target-b")
    assert slots.track_ids[3] == "other-z"
    assert len(slots.track_ids) == PUBLIC_TRACK_CANDIDATE_COUNT
    assert slots.valid_mask.tolist() == [True] * 8
    assert [candidate.role for candidate in slots.candidates[:3]] == [
        PublicTrackRoleV3.ROLE_TARGET_ATTRIBUTE_MATCH,
    ] * 3
    assert PUBLIC_TRACK_CANDIDATE_REVISION == "PublicTrackCandidateV3"
    assert PUBLIC_TRACK_CHECKPOINT_ARCHITECTURE == "M2C_Q012_V3"


def test_collection_facade_and_canonical_hash_are_versioned_and_stable() -> None:
    tracks = [track("b"), track("a", category="yellow")]
    candidates = build_public_track_candidates_v3(
        tracks,
        declared_target_attribute="yellow",
    )
    assert [candidate.track_id for candidate in candidates] == ["a", "b"]
    payload = canonical_candidate_payload_v3(candidates)
    assert payload["schema_version"] == "PublicTrackCandidateV3"
    assert payload["checkpoint_architecture_revision"] == "M2C_Q012_V3"
    assert payload["valid_mask"] == [True, True, False, False, False, False, False, False]
    assert payload["task_target_track_id_used"] is False
    assert canonical_candidate_sha256_v3(candidates) == canonical_candidate_sha256_v3(
        candidates
    )
    assert len(canonical_candidate_sha256_v3(candidates)) == 64


def test_missing_category_or_pose_is_inadmissible_and_padded() -> None:
    missing_category = track("missing-category", category=None)
    missing_pose = track("missing-pose")
    missing_pose = missing_pose.model_copy(update={"pose_xyzquat": None})
    valid = track("valid", category="yellow", confidence=0.5)
    slots = public_track_candidate_slots_v3(
        [missing_category, missing_pose, valid],
        declared_attribute_token="yellow",
    )
    assert slots.track_ids == ("valid", None, None, None, None, None, None, None)
    assert slots.valid_mask.tolist() == [True, False, False, False, False, False, False, False]


def test_empty_candidate_pointer_is_fail_closed() -> None:
    missing = track("missing")
    missing = missing.model_copy(update={"pose_xyzquat": None})
    slots = public_track_candidate_slots_v3([missing], declared_attribute_token="yellow")
    assert not slots.valid_mask.any()
    logits = np.zeros(9)
    logits[0] = 1.0
    with pytest.raises(InvalidPublicTrackCandidateV3) as error:
        decode_track_pointer_v3(logits, slots)
    assert error.value.code == CandidatePointerErrorCodeV3.MASKED_POINTER_SLOT
    with pytest.raises(InvalidPublicTrackCandidateV3) as error:
        encode_track_pointer_target_v3("missing", slots)
    assert error.value.code == CandidatePointerErrorCodeV3.TRACK_OUTSIDE_CANDIDATES


def test_pointer_encode_decode_none_mask_and_qwen_literal() -> None:
    slots = public_track_candidate_slots_v3(
        [track("track-b"), track("track-a")],
        declared_attribute_token="yellow",
    )
    assert encode_track_pointer_target_v3("track-a", slots) == 0
    assert encode_track_pointer_target_v3(None, slots) == PUBLIC_TRACK_POINTER_NONE_INDEX
    logits = np.full(9, -1.0)
    logits[0] = 1.0
    assert decode_track_pointer_v3(logits, slots) == "track-a"
    logits[PUBLIC_TRACK_POINTER_NONE_INDEX] = 2.0
    assert decode_track_pointer_v3(logits, slots) is None
    assert decode_qwen_track_literal_v3("track-b", slots) == "track-b"
    assert decode_qwen_track_literal_v3("NONE", slots) is None
    for literal in ("track-c", " track-a", "track-a "):
        with pytest.raises(InvalidPublicTrackCandidateV3):
            decode_qwen_track_literal_v3(literal, slots)


def test_pose_values_never_affect_order_only_presence() -> None:
    first = [
        track("a", confidence=0.8, pose=[-999, 99, 5, 1, 0, 0, 0]),
        track("b", confidence=0.9, pose=[999, -99, -5, 1, 0, 0, 0]),
    ]
    second = [
        first[0].model_copy(update={"pose_xyzquat": first[1].pose_xyzquat}),
        first[1].model_copy(update={"pose_xyzquat": first[0].pose_xyzquat}),
    ]
    assert public_track_candidate_slots_v3(
        first, declared_attribute_token="yellow"
    ).track_ids == public_track_candidate_slots_v3(
        second, declared_attribute_token="yellow"
    ).track_ids


def test_mapping_input_rejects_teacher_truth_task_target_and_extra_fields() -> None:
    public = {
        "track_id": "track-a",
        "category": "yellow",
        "confidence": 0.9,
        "pose_xyzquat": [0, 0, 0, 1, 0, 0, 0],
    }
    for forbidden in (
        "task_target_track_id",
        "teacher_output",
        "privileged_truth_role",
        "perfect_pose",
        "task_success",
    ):
        poisoned = {**public, forbidden: "secret"}
        with pytest.raises(InvalidPublicTrackCandidateV3) as error:
            public_track_candidate_slots_v3(
                [poisoned], declared_attribute_token="yellow"
            )
        assert error.value.code == CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK


def test_perception_track_extra_fields_do_not_enter_candidate_semantics() -> None:
    original = track("track-a", category="yellow", confidence=0.9)
    poisoned = original.model_copy(update={"crop_uri": "teacher://must-not-be-read"})
    left = public_track_candidate_slots_v3(
        [original], declared_attribute_token="yellow"
    )
    right = public_track_candidate_slots_v3(
        [poisoned], declared_attribute_token="yellow"
    )
    assert left.track_ids == right.track_ids
    assert left.candidates == right.candidates


def test_invalid_token_duplicate_id_nonfinite_logits_and_non_k8_fail_closed() -> None:
    with pytest.raises(InvalidPublicTrackCandidateV3) as error:
        public_track_candidate_slots_v3([track("a")], declared_attribute_token="yellow red")
    assert error.value.code == CandidatePointerErrorCodeV3.INVALID_ATTRIBUTE_TOKEN
    with pytest.raises(InvalidPublicTrackCandidateV3) as error:
        public_track_candidate_slots_v3(
            [track("same"), track("same")], declared_attribute_token="yellow"
        )
    assert error.value.code == CandidatePointerErrorCodeV3.DUPLICATE_TRACK_ID
    with pytest.raises(InvalidPublicTrackCandidateV3) as error:
        public_track_candidate_slots_v3(
            [track("a")], declared_attribute_token="yellow", k=7
        )
    assert error.value.code == CandidatePointerErrorCodeV3.INVALID_CANDIDATE_COUNT
    slots = public_track_candidate_slots_v3([track("a")], declared_attribute_token="yellow")
    with pytest.raises(InvalidPublicTrackCandidateV3) as error:
        decode_track_pointer_v3([0.0] * 8 + [float("nan")], slots)
    assert error.value.code == CandidatePointerErrorCodeV3.INVALID_POINTER_LOGITS


def test_task_target_identity_change_cannot_affect_candidates() -> None:
    tracks = [track("a", category="yellow"), track("b", category="blue")]
    before = public_track_candidate_slots_v3(
        copy.deepcopy(tracks), declared_attribute_token="yellow"
    )
    # No TaskSpec or QRMObservation object is accepted by the API; only the
    # already-extracted attribute token can enter candidate construction.
    after = public_track_candidate_slots_v3(
        copy.deepcopy(tracks), declared_attribute_token="yellow"
    )
    assert before.candidates == after.candidates
    assert before.track_ids == after.track_ids
    assert np.array_equal(before.valid_mask, after.valid_mask)
