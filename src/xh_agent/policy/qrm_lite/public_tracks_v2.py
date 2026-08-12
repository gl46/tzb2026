"""Canonical public-track slots for the ADR-0020 model pointer head.

Only fields already present in :class:`PerceptionTrackV1` are encoded.  No
simulator entity identity, perfect pose, contact, or task-success field is
accepted by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Sequence

import numpy as np

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1


PUBLIC_TRACK_SLOT_COUNT = 8
PUBLIC_TRACK_POINTER_CLASS_COUNT = PUBLIC_TRACK_SLOT_COUNT + 1
PUBLIC_TRACK_POINTER_NONE_INDEX = PUBLIC_TRACK_SLOT_COUNT

PUBLIC_TRACK_COLORS = (
    "red",
    "green",
    "blue",
    "yellow",
    "magenta",
    "cyan",
    "unknown",
)
PUBLIC_TRACK_SLOT_FEATURE_NAMES = (
    "valid_mask",
    "confidence",
    "pose_present",
    "pose_xyz_0",
    "pose_xyz_1",
    "pose_xyz_2",
    *(f"category_color_{color}" for color in PUBLIC_TRACK_COLORS),
)
PUBLIC_TRACK_SLOT_FEATURE_DIM = len(PUBLIC_TRACK_SLOT_FEATURE_NAMES)
PUBLIC_TRACK_ENCODING_REVISION = "M2C_PUBLIC_TRACK_SLOTS_V2"
PUBLIC_TRACK_POSE_FRAME = "QRMObservationV1.perception_tracks.pose_xyzquat"
PUBLIC_TRACK_NORMALIZATION = "none"

if PUBLIC_TRACK_SLOT_FEATURE_DIM != 13:  # pragma: no cover - import-time guard
    raise RuntimeError("ADR-0020 public-track feature layout must stay 13-D")


class TrackPointerErrorCode(str, Enum):
    INVALID_SLOT_COUNT = "INVALID_SLOT_COUNT"
    EMPTY_TRACK_ID = "EMPTY_TRACK_ID"
    DUPLICATE_TRACK_ID = "DUPLICATE_TRACK_ID"
    TRACK_OUTSIDE_CANONICAL_SLOTS = "TRACK_OUTSIDE_CANONICAL_SLOTS"
    INVALID_POINTER_LOGITS = "INVALID_POINTER_LOGITS"
    MASKED_POINTER_SLOT = "MASKED_POINTER_SLOT"
    INVALID_QWEN_TRACK_LITERAL = "INVALID_QWEN_TRACK_LITERAL"
    NONFINITE_PUBLIC_TRACK_FEATURE = "NONFINITE_PUBLIC_TRACK_FEATURE"


class InvalidTrackPointerV2(ValueError):
    """Fail-closed pointer error with a stable machine-readable code."""

    def __init__(self, code: TrackPointerErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


@dataclass(frozen=True)
class CanonicalTrackSlotsV2:
    """Lexicographically sorted, padded public-track candidates."""

    tracks: tuple[PerceptionTrackV1 | None, ...]
    valid_mask: np.ndarray
    track_ids: tuple[str | None, ...]

    def __post_init__(self) -> None:
        if len(self.tracks) != PUBLIC_TRACK_SLOT_COUNT:
            raise InvalidTrackPointerV2(
                TrackPointerErrorCode.INVALID_SLOT_COUNT,
                f"expected {PUBLIC_TRACK_SLOT_COUNT} slots, got {len(self.tracks)}",
            )
        if len(self.track_ids) != PUBLIC_TRACK_SLOT_COUNT:
            raise InvalidTrackPointerV2(
                TrackPointerErrorCode.INVALID_SLOT_COUNT,
                "track_ids length does not match the frozen slot count",
            )
        mask = np.asarray(self.valid_mask, dtype=np.bool_).reshape(-1).copy()
        if mask.shape != (PUBLIC_TRACK_SLOT_COUNT,):
            raise InvalidTrackPointerV2(
                TrackPointerErrorCode.INVALID_SLOT_COUNT,
                f"valid_mask shape {mask.shape} is not ({PUBLIC_TRACK_SLOT_COUNT},)",
            )
        expected = np.asarray(
            [track is not None for track in self.tracks], dtype=np.bool_
        )
        if not np.array_equal(mask, expected):
            raise InvalidTrackPointerV2(
                TrackPointerErrorCode.INVALID_SLOT_COUNT,
                "valid_mask disagrees with padded track slots",
            )
        expected_ids = tuple(
            track.track_id if track is not None else None for track in self.tracks
        )
        if self.track_ids != expected_ids:
            raise InvalidTrackPointerV2(
                TrackPointerErrorCode.INVALID_SLOT_COUNT,
                "track_ids disagree with padded track slots",
            )
        mask.setflags(write=False)
        object.__setattr__(self, "valid_mask", mask)


def canonical_track_slots(
    tracks: Sequence[PerceptionTrackV1],
    *,
    k: int = PUBLIC_TRACK_SLOT_COUNT,
) -> CanonicalTrackSlotsV2:
    """Sort fresh public tracks by literal ID, truncate to K=8, and pad."""

    if k != PUBLIC_TRACK_SLOT_COUNT:
        raise InvalidTrackPointerV2(
            TrackPointerErrorCode.INVALID_SLOT_COUNT,
            f"ADR-0020 freezes K={PUBLIC_TRACK_SLOT_COUNT}; received K={k}",
        )
    validated = [
        track
        if isinstance(track, PerceptionTrackV1)
        else PerceptionTrackV1.model_validate(track)
        for track in tracks
    ]
    empty = sorted(track.track_id for track in validated if not track.track_id)
    if empty:
        raise InvalidTrackPointerV2(
            TrackPointerErrorCode.EMPTY_TRACK_ID,
            "public track IDs must be non-empty literals",
        )
    ids = [track.track_id for track in validated]
    duplicates = sorted({track_id for track_id in ids if ids.count(track_id) > 1})
    if duplicates:
        raise InvalidTrackPointerV2(
            TrackPointerErrorCode.DUPLICATE_TRACK_ID,
            f"ambiguous public track IDs: {duplicates}",
        )
    ordered = sorted(validated, key=lambda track: track.track_id)[:k]
    padded: tuple[PerceptionTrackV1 | None, ...] = tuple(
        [*ordered, *([None] * (k - len(ordered)))]
    )
    return CanonicalTrackSlotsV2(
        tracks=padded,
        valid_mask=np.asarray([track is not None for track in padded], dtype=np.bool_),
        track_ids=tuple(
            track.track_id if track is not None else None for track in padded
        ),
    )


def _public_color(track: PerceptionTrackV1) -> str:
    raw = (track.category or "").lower()
    tokens = raw.replace("/", ":").split(":")
    matches = [color for color in PUBLIC_TRACK_COLORS[:-1] if color in tokens]
    return matches[0] if len(matches) == 1 else "unknown"


def encode_public_track_slots(slots: CanonicalTrackSlotsV2) -> np.ndarray:
    """Encode K public slots into the frozen flat 8×13 feature layout.

    XYZ values are copied verbatim from the public observation's
    ``pose_xyzquat`` field.  This encoder does not infer a frame or transform
    missing poses; padded/missing-pose coordinates remain zero and are
    disambiguated by the explicit masks.
    """

    if not isinstance(slots, CanonicalTrackSlotsV2):
        raise TypeError("encode_public_track_slots requires CanonicalTrackSlotsV2")
    rows = np.zeros(
        (PUBLIC_TRACK_SLOT_COUNT, PUBLIC_TRACK_SLOT_FEATURE_DIM),
        dtype=np.float64,
    )
    color_offset = 6
    for index, track in enumerate(slots.tracks):
        if track is None:
            continue
        rows[index, 0] = 1.0
        rows[index, 1] = float(track.confidence)
        if track.pose_xyzquat is not None:
            xyz = np.asarray(track.pose_xyzquat[:3], dtype=np.float64)
            if xyz.shape != (3,) or not np.isfinite(xyz).all():
                raise InvalidTrackPointerV2(
                    TrackPointerErrorCode.NONFINITE_PUBLIC_TRACK_FEATURE,
                    f"slot {index} contains a non-finite public XYZ pose",
                )
            rows[index, 2] = 1.0
            rows[index, 3:6] = xyz
        rows[index, color_offset + PUBLIC_TRACK_COLORS.index(_public_color(track))] = 1.0
    if not all(isfinite(float(value)) for value in rows.reshape(-1)):
        raise InvalidTrackPointerV2(
            TrackPointerErrorCode.NONFINITE_PUBLIC_TRACK_FEATURE,
            "encoded public-track tensor contains NaN or Inf",
        )
    encoded = rows.reshape(-1)
    encoded.setflags(write=False)
    return encoded


def encode_track_pointer_target(
    target_track_id: str | None,
    slots: CanonicalTrackSlotsV2,
) -> int:
    """Map a public literal to its canonical class, or the dedicated NONE."""

    if target_track_id is None:
        return PUBLIC_TRACK_POINTER_NONE_INDEX
    for index, slot_id in enumerate(slots.track_ids):
        if slot_id == target_track_id and slots.valid_mask[index]:
            return index
    raise InvalidTrackPointerV2(
        TrackPointerErrorCode.TRACK_OUTSIDE_CANONICAL_SLOTS,
        f"track {target_track_id!r} is absent from the fresh first-K slots",
    )


def decode_track_pointer(
    logits: Sequence[float] | np.ndarray,
    slots: CanonicalTrackSlotsV2,
) -> str | None:
    """Temperature-zero argmax; NumPy's first maximum resolves ties lower."""

    values = np.asarray(logits, dtype=np.float64).reshape(-1)
    if values.shape != (PUBLIC_TRACK_POINTER_CLASS_COUNT,) or not np.isfinite(
        values
    ).all():
        raise InvalidTrackPointerV2(
            TrackPointerErrorCode.INVALID_POINTER_LOGITS,
            "pointer logits must be exactly 9 finite values",
        )
    selected = int(np.argmax(values))
    if selected == PUBLIC_TRACK_POINTER_NONE_INDEX:
        return None
    if not slots.valid_mask[selected]:
        raise InvalidTrackPointerV2(
            TrackPointerErrorCode.MASKED_POINTER_SLOT,
            f"pointer selected padded slot {selected}",
        )
    return slots.track_ids[selected]


def decode_qwen_track_literal(
    literal: str,
    slots: CanonicalTrackSlotsV2,
) -> str | None:
    """Resolve only an exact current literal or exact ``NONE`` token."""

    if literal == "NONE":
        return None
    if literal in slots.track_ids:
        index = slots.track_ids.index(literal)
        if slots.valid_mask[index]:
            return literal
    raise InvalidTrackPointerV2(
        TrackPointerErrorCode.INVALID_QWEN_TRACK_LITERAL,
        f"Qwen literal {literal!r} is absent from the fresh first-K slots",
    )
