from __future__ import annotations

import copy

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    PUBLIC_TRACK_CANDIDATE_COUNT_V4,
    PUBLIC_TRACK_CANDIDATE_REVISION_V4,
    PUBLIC_TRACK_CHECKPOINT_ARCHITECTURE_V4,
    PUBLIC_TRACK_POINTER_NONE_INDEX_V4,
    CandidatePointerErrorCodeV4,
    InvalidPublicTrackCandidateV4,
    PublicTrackRoleV4,
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
    decode_qwen_track_literal_v4,
    decode_track_pointer_v4,
    encode_track_pointer_target_v4,
    public_track_candidate_slots_v4,
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
        pose_xyzquat=(pose if pose is not None else [0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0]),
    )


def test_adr0021_ordering_is_carried_verbatim_to_v4_k8() -> None:
    tracks = [
        track("other-z", confidence=1.0),
        track("target-b", category="INDUSTRIAL:YELLOW", confidence=0.8),
        track("target-a", category="yellow-cylinder", confidence=0.8),
        track("target-c", category="yellow", confidence=0.9),
        *(track(f"other-{index}", confidence=0.7 - index / 100) for index in range(8)),
    ]
    slots = public_track_candidate_slots_v4(
        tracks,
        declared_attribute_token="Yellow",
    )
    assert slots.track_ids[:4] == ("target-c", "target-a", "target-b", "other-z")
    assert slots.valid_mask.tolist() == [True] * 8
    assert [candidate.role for candidate in slots.candidates[:3]] == [
        PublicTrackRoleV4.ROLE_TARGET_ATTRIBUTE_MATCH,
    ] * 3
    assert PUBLIC_TRACK_CANDIDATE_COUNT_V4 == 8
    assert PUBLIC_TRACK_CANDIDATE_REVISION_V4 == "PublicTrackCandidateV4"
    assert PUBLIC_TRACK_CHECKPOINT_ARCHITECTURE_V4 == "M2C_Q012_V4"


def test_canonical_payload_hash_and_pointer_are_v4_exact() -> None:
    candidates = build_public_track_candidates_v4(
        [track("b"), track("a", category="yellow")],
        declared_target_attribute="yellow",
    )
    payload = canonical_candidate_payload_v4(candidates)
    assert payload["schema_version"] == "PublicTrackCandidateV4"
    assert payload["checkpoint_architecture_revision"] == "M2C_Q012_V4"
    assert payload["valid_mask"] == [True, True, False, False, False, False, False, False]
    assert payload["task_target_track_id_used"] is False
    assert len(canonical_candidate_sha256_v4(candidates)) == 64

    slots = public_track_candidate_slots_v4(
        [track("b"), track("a", category="yellow")],
        declared_attribute_token="yellow",
    )
    assert encode_track_pointer_target_v4("a", slots) == 0
    assert encode_track_pointer_target_v4(None, slots) == PUBLIC_TRACK_POINTER_NONE_INDEX_V4
    logits = np.full(9, -1.0)
    logits[0] = 1.0
    assert decode_track_pointer_v4(logits, slots) == "a"
    logits[8] = 2.0
    assert decode_track_pointer_v4(logits, slots) is None
    assert decode_qwen_track_literal_v4("b", slots) == "b"
    assert decode_qwen_track_literal_v4("NONE", slots) is None


def test_missing_fields_and_forbidden_inputs_fail_closed() -> None:
    missing_pose = track("missing").model_copy(update={"pose_xyzquat": None})
    slots = public_track_candidate_slots_v4(
        [track("valid", category="yellow"), missing_pose],
        declared_attribute_token="yellow",
    )
    assert slots.track_ids == ("valid", None, None, None, None, None, None, None)

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
        "receipt_sha256",
        "task_success",
    ):
        with pytest.raises(InvalidPublicTrackCandidateV4) as error:
            public_track_candidate_slots_v4(
                [{**public, forbidden: "secret"}],
                declared_attribute_token="yellow",
            )
        assert error.value.code == CandidatePointerErrorCodeV4.INVALID_PUBLIC_TRACK


def test_v4_candidate_builder_has_no_target_identity_channel() -> None:
    tracks = [track("a", category="yellow"), track("b", category="blue")]
    before = public_track_candidate_slots_v4(
        copy.deepcopy(tracks),
        declared_attribute_token="yellow",
    )
    after = public_track_candidate_slots_v4(
        copy.deepcopy(tracks),
        declared_attribute_token="yellow",
    )
    assert before.candidates == after.candidates
    assert np.array_equal(before.valid_mask, after.valid_mask)


def test_duplicate_invalid_logits_and_masked_slot_fail_closed() -> None:
    with pytest.raises(InvalidPublicTrackCandidateV4) as error:
        public_track_candidate_slots_v4(
            [track("same"), track("same")],
            declared_attribute_token="yellow",
        )
    assert error.value.code == CandidatePointerErrorCodeV4.DUPLICATE_TRACK_ID
    slots = public_track_candidate_slots_v4(
        [track("a")],
        declared_attribute_token="yellow",
    )
    with pytest.raises(InvalidPublicTrackCandidateV4) as error:
        decode_track_pointer_v4([0.0] * 8 + [float("nan")], slots)
    assert error.value.code == CandidatePointerErrorCodeV4.INVALID_POINTER_LOGITS
    logits = np.zeros(9)
    logits[1] = 1.0
    with pytest.raises(InvalidPublicTrackCandidateV4) as error:
        decode_track_pointer_v4(logits, slots)
    assert error.value.code == CandidatePointerErrorCodeV4.MASKED_POINTER_SLOT
