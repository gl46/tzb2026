from __future__ import annotations

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v2 import (
    PUBLIC_TRACK_POINTER_NONE_INDEX,
    PUBLIC_TRACK_SLOT_COUNT,
    PUBLIC_TRACK_SLOT_FEATURE_DIM,
    InvalidTrackPointerV2,
    TrackPointerErrorCode,
    canonical_track_slots,
    decode_qwen_track_literal,
    decode_track_pointer,
    encode_public_track_slots,
    encode_track_pointer_target,
)


def track(
    track_id: str,
    *,
    color: str = "yellow",
    confidence: float = 0.9,
    pose: list[float] | None = None,
) -> PerceptionTrackV1:
    return PerceptionTrackV1(
        track_id=track_id,
        category=f"industrial_cylinder:{color}",
        confidence=confidence,
        pose_xyzquat=pose
        or [0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0],
    )


def test_slots_are_literal_sorted_truncated_padded_and_public_only() -> None:
    tracks = [track(f"track-{index:02d}") for index in range(9, -1, -1)]
    slots = canonical_track_slots(tracks)
    assert slots.track_ids == tuple(
        [*(f"track-{index:02d}" for index in range(8))]
    )
    assert slots.valid_mask.tolist() == [True] * PUBLIC_TRACK_SLOT_COUNT
    encoded = encode_public_track_slots(slots)
    assert encoded.shape == (
        PUBLIC_TRACK_SLOT_COUNT * PUBLIC_TRACK_SLOT_FEATURE_DIM,
    )
    rows = encoded.reshape(PUBLIC_TRACK_SLOT_COUNT, PUBLIC_TRACK_SLOT_FEATURE_DIM)
    assert rows[0, :6].tolist() == pytest.approx([1.0, 0.9, 1.0, 0.1, 0.2, 0.3])
    assert rows[0, 9] == 1.0  # red, green, blue, then yellow
    assert not encoded.flags.writeable


def test_padding_and_missing_pose_use_explicit_masks_not_inferred_values() -> None:
    slots = canonical_track_slots(
        [
            PerceptionTrackV1(
                track_id="blocker",
                category="industrial_cylinder:not-registered",
                confidence=0.5,
                pose_xyzquat=None,
            )
        ]
    )
    rows = encode_public_track_slots(slots).reshape(8, 13)
    assert rows[0, :6].tolist() == [1.0, 0.5, 0.0, 0.0, 0.0, 0.0]
    assert rows[0, 12] == 1.0
    assert np.count_nonzero(rows[1:]) == 0


def test_pointer_decode_is_deterministic_and_rejects_masked_or_stale() -> None:
    slots = canonical_track_slots([track("track-b"), track("track-a")])
    tied = np.full((9,), -1.0)
    tied[0] = tied[1] = 2.0
    assert decode_track_pointer(tied, slots) == "track-a"
    assert encode_track_pointer_target("track-b", slots) == 1
    assert encode_track_pointer_target(None, slots) == PUBLIC_TRACK_POINTER_NONE_INDEX
    none_logits = np.zeros((9,))
    none_logits[PUBLIC_TRACK_POINTER_NONE_INDEX] = 1.0
    assert decode_track_pointer(none_logits, slots) is None

    masked = np.zeros((9,))
    masked[2] = 1.0
    with pytest.raises(InvalidTrackPointerV2) as exc:
        decode_track_pointer(masked, slots)
    assert exc.value.code == TrackPointerErrorCode.MASKED_POINTER_SLOT

    with pytest.raises(InvalidTrackPointerV2) as exc:
        encode_track_pointer_target("stale", slots)
    assert exc.value.code == TrackPointerErrorCode.TRACK_OUTSIDE_CANONICAL_SLOTS


def test_qwen_pointer_accepts_only_exact_current_literal() -> None:
    slots = canonical_track_slots([track("track-A")])
    assert decode_qwen_track_literal("track-A", slots) == "track-A"
    assert decode_qwen_track_literal("NONE", slots) is None
    for invalid in ("track-a", " track-A", "track-A ", "task-target"):
        with pytest.raises(InvalidTrackPointerV2) as exc:
            decode_qwen_track_literal(invalid, slots)
        assert exc.value.code == TrackPointerErrorCode.INVALID_QWEN_TRACK_LITERAL


def test_duplicate_ids_and_non_frozen_k_fail_closed() -> None:
    with pytest.raises(InvalidTrackPointerV2) as exc:
        canonical_track_slots([track("same"), track("same")])
    assert exc.value.code == TrackPointerErrorCode.DUPLICATE_TRACK_ID
    with pytest.raises(InvalidTrackPointerV2) as exc:
        canonical_track_slots([track("one")], k=7)
    assert exc.value.code == TrackPointerErrorCode.INVALID_SLOT_COUNT
