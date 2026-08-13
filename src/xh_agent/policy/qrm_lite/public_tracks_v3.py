"""ADR-0021 public semantic-role candidate contract.

This module is intentionally independent from ``public_tracks_v2``.  V2's
literal-ID semantics remain frozen historical evidence.  V3 consumes only a
fresh sequence of :class:`PerceptionTrackV1` values plus one TaskSpec-declared
attribute token supplied explicitly by the caller; no observation object or
TaskSpec target identity enters this API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Mapping, Sequence

import numpy as np

from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1


PUBLIC_TRACK_CANDIDATE_REVISION = "PublicTrackCandidateV3"
PUBLIC_TRACK_CHECKPOINT_ARCHITECTURE = "M2C_Q012_V3"
PUBLIC_TRACK_CANDIDATE_COUNT = 8
PUBLIC_TRACK_POINTER_CLASS_COUNT = 9
PUBLIC_TRACK_POINTER_NONE_INDEX = 8
PUBLIC_TRACK_RECAPTURE_POLICY = "NONE"
ATTRIBUTE_TOKEN_PATTERN = re.compile(r"^[a-z0-9_-]+$")


class PublicTrackRoleV3(str, Enum):
    ROLE_TARGET_ATTRIBUTE_MATCH = "ROLE_TARGET_ATTRIBUTE_MATCH"
    ROLE_MANIPULABLE_OTHER = "ROLE_MANIPULABLE_OTHER"


class CandidatePointerErrorCodeV3(str, Enum):
    INVALID_CANDIDATE_COUNT = "INVALID_CANDIDATE_COUNT"
    INVALID_ATTRIBUTE_TOKEN = "INVALID_ATTRIBUTE_TOKEN"
    INVALID_PUBLIC_TRACK = "INVALID_PUBLIC_TRACK"
    DUPLICATE_TRACK_ID = "DUPLICATE_TRACK_ID"
    EMPTY_CANDIDATE_LIST = "EMPTY_CANDIDATE_LIST"
    TRACK_OUTSIDE_CANDIDATES = "TRACK_OUTSIDE_CANDIDATES"
    INVALID_POINTER_LOGITS = "INVALID_POINTER_LOGITS"
    MASKED_POINTER_SLOT = "MASKED_POINTER_SLOT"
    INVALID_QWEN_TRACK_LITERAL = "INVALID_QWEN_TRACK_LITERAL"


class InvalidPublicTrackCandidateV3(ValueError):
    def __init__(self, code: CandidatePointerErrorCodeV3, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


@dataclass(frozen=True)
class PublicTrackCandidateV3:
    track_id: str
    category: str
    confidence: float
    pose_present: bool
    role: PublicTrackRoleV3

    def __post_init__(self) -> None:
        if not self.track_id or not self.category or not self.pose_present:
            raise InvalidPublicTrackCandidateV3(
                CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK,
                "candidate requires non-empty track_id/category and present pose",
            )
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise InvalidPublicTrackCandidateV3(
                CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK,
                "candidate confidence must be finite in [0, 1]",
            )


@dataclass(frozen=True)
class PublicTrackCandidateSlotsV3:
    candidates: tuple[PublicTrackCandidateV3 | None, ...]
    valid_mask: np.ndarray
    track_ids: tuple[str | None, ...]

    def __post_init__(self) -> None:
        if len(self.candidates) != PUBLIC_TRACK_CANDIDATE_COUNT:
            raise InvalidPublicTrackCandidateV3(
                CandidatePointerErrorCodeV3.INVALID_CANDIDATE_COUNT,
                "candidate slots must contain exactly K=8 entries",
            )
        expected_ids = tuple(
            candidate.track_id if candidate is not None else None
            for candidate in self.candidates
        )
        if self.track_ids != expected_ids:
            raise InvalidPublicTrackCandidateV3(
                CandidatePointerErrorCodeV3.INVALID_CANDIDATE_COUNT,
                "track IDs disagree with padded candidates",
            )
        mask = np.asarray(self.valid_mask, dtype=np.bool_).reshape(-1).copy()
        expected_mask = np.asarray(
            [candidate is not None for candidate in self.candidates], dtype=np.bool_
        )
        if mask.shape != (PUBLIC_TRACK_CANDIDATE_COUNT,) or not np.array_equal(
            mask, expected_mask
        ):
            raise InvalidPublicTrackCandidateV3(
                CandidatePointerErrorCodeV3.INVALID_CANDIDATE_COUNT,
                "valid mask disagrees with padded candidates",
            )
        mask.setflags(write=False)
        object.__setattr__(self, "valid_mask", mask)


def _attribute_token(token: str) -> str:
    if not isinstance(token, str):
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_ATTRIBUTE_TOKEN,
            "declared attribute token must be a string",
        )
    normalized = token.strip().casefold()
    if ATTRIBUTE_TOKEN_PATTERN.fullmatch(normalized) is None:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_ATTRIBUTE_TOKEN,
            "declared attribute token must be one lowercase alphanumeric token",
        )
    return normalized


def _track_from_public_fields(
    raw: PerceptionTrackV1 | Mapping[str, object],
) -> PerceptionTrackV1:
    if isinstance(raw, PerceptionTrackV1):
        # Deliberately copy only ADR-0021 section-1 fields.
        return PerceptionTrackV1(
            track_id=raw.track_id,
            category=raw.category,
            confidence=raw.confidence,
            pose_xyzquat=raw.pose_xyzquat,
        )
    if not isinstance(raw, Mapping):
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK,
            "candidate input must be PerceptionTrackV1 or a public-field mapping",
        )
    allowed = {"track_id", "category", "confidence", "pose_xyzquat"}
    extra = set(raw) - allowed
    if extra:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK,
            f"candidate input contains fields outside ADR-0021: {sorted(extra)}",
        )
    try:
        return PerceptionTrackV1.model_validate(dict(raw))
    except ValueError as error:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK,
            f"invalid public track fields: {error}",
        ) from error


def public_track_candidate_slots_v3(
    tracks: Sequence[PerceptionTrackV1 | Mapping[str, object]],
    *,
    declared_attribute_token: str,
    k: int = PUBLIC_TRACK_CANDIDATE_COUNT,
) -> PublicTrackCandidateSlotsV3:
    """Role-rank fresh public tracks, truncate K=8, and pad masked slots."""

    if k != PUBLIC_TRACK_CANDIDATE_COUNT:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_CANDIDATE_COUNT,
            f"ADR-0021 freezes K=8; received K={k}",
        )
    attribute = _attribute_token(declared_attribute_token)
    validated = [_track_from_public_fields(track) for track in tracks]
    ids = [track.track_id for track in validated]
    if any(not track_id for track_id in ids):
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_PUBLIC_TRACK,
            "public track IDs must be non-empty",
        )
    duplicates = sorted({track_id for track_id in ids if ids.count(track_id) > 1})
    if duplicates:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.DUPLICATE_TRACK_ID,
            f"ambiguous public track IDs: {duplicates}",
        )
    candidates: list[PublicTrackCandidateV3] = []
    for track in validated:
        # Inadmissible tracks are excluded, never repaired or inferred.
        if not isinstance(track.category, str) or not track.category.strip():
            continue
        if track.pose_xyzquat is None:
            continue
        role = (
            PublicTrackRoleV3.ROLE_TARGET_ATTRIBUTE_MATCH
            if attribute in track.category.casefold()
            else PublicTrackRoleV3.ROLE_MANIPULABLE_OTHER
        )
        candidates.append(
            PublicTrackCandidateV3(
                track_id=track.track_id,
                category=track.category,
                confidence=float(track.confidence),
                pose_present=True,
                role=role,
            )
        )
    role_rank = {
        PublicTrackRoleV3.ROLE_TARGET_ATTRIBUTE_MATCH: 0,
        PublicTrackRoleV3.ROLE_MANIPULABLE_OTHER: 1,
    }
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            role_rank[candidate.role],
            -candidate.confidence,
            candidate.track_id,
        ),
    )[:k]
    padded: tuple[PublicTrackCandidateV3 | None, ...] = tuple(
        [*ordered, *([None] * (k - len(ordered)))]
    )
    return PublicTrackCandidateSlotsV3(
        candidates=padded,
        valid_mask=np.asarray([item is not None for item in padded], dtype=np.bool_),
        track_ids=tuple(item.track_id if item is not None else None for item in padded),
    )


def build_public_track_candidates_v3(
    tracks: Sequence[PerceptionTrackV1 | Mapping[str, object]],
    *,
    declared_target_attribute: str,
    k: int = PUBLIC_TRACK_CANDIDATE_COUNT,
) -> list[PublicTrackCandidateV3]:
    """Stable collection facade returning only ordered, admissible candidates."""

    slots = public_track_candidate_slots_v3(
        tracks,
        declared_attribute_token=declared_target_attribute,
        k=k,
    )
    return [candidate for candidate in slots.candidates if candidate is not None]


def canonical_candidate_payload_v3(
    candidates: Sequence[PublicTrackCandidateV3],
) -> dict[str, object]:
    """Return the exact versioned payload used by collection evidence."""

    if len(candidates) > PUBLIC_TRACK_CANDIDATE_COUNT:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_CANDIDATE_COUNT,
            "canonical candidate payload exceeds K=8",
        )
    ids = [candidate.track_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.DUPLICATE_TRACK_ID,
            "canonical candidate payload repeats a track ID",
        )
    return {
        "schema_version": PUBLIC_TRACK_CANDIDATE_REVISION,
        "checkpoint_architecture_revision": PUBLIC_TRACK_CHECKPOINT_ARCHITECTURE,
        "candidate_count_bound": PUBLIC_TRACK_CANDIDATE_COUNT,
        "recapture_policy": PUBLIC_TRACK_RECAPTURE_POLICY,
        "candidates": [
            {
                "track_id": candidate.track_id,
                "category": candidate.category,
                "confidence": candidate.confidence,
                "pose_present": candidate.pose_present,
                "role": candidate.role.value,
            }
            for candidate in candidates
        ],
        "valid_mask": [
            *([True] * len(candidates)),
            *([False] * (PUBLIC_TRACK_CANDIDATE_COUNT - len(candidates))),
        ],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "task_target_track_id_used": False,
    }


def canonical_candidate_sha256_v3(
    candidates: Sequence[PublicTrackCandidateV3],
) -> str:
    payload = canonical_candidate_payload_v3(candidates)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def encode_track_pointer_target_v3(
    target_track_id: str | None,
    slots: PublicTrackCandidateSlotsV3,
) -> int:
    if target_track_id is None:
        return PUBLIC_TRACK_POINTER_NONE_INDEX
    for index, track_id in enumerate(slots.track_ids):
        if track_id == target_track_id and slots.valid_mask[index]:
            return index
    raise InvalidPublicTrackCandidateV3(
        CandidatePointerErrorCodeV3.TRACK_OUTSIDE_CANDIDATES,
        f"track {target_track_id!r} is absent from fresh V3 candidates",
    )


def decode_track_pointer_v3(
    logits: Sequence[float] | np.ndarray,
    slots: PublicTrackCandidateSlotsV3,
) -> str | None:
    values = np.asarray(logits, dtype=np.float64).reshape(-1)
    if values.shape != (PUBLIC_TRACK_POINTER_CLASS_COUNT,) or not np.isfinite(
        values
    ).all():
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.INVALID_POINTER_LOGITS,
            "pointer logits must be exactly nine finite values",
        )
    selected = int(np.argmax(values))
    if selected == PUBLIC_TRACK_POINTER_NONE_INDEX:
        return None
    if not slots.valid_mask[selected]:
        raise InvalidPublicTrackCandidateV3(
            CandidatePointerErrorCodeV3.MASKED_POINTER_SLOT,
            f"pointer selected padded slot {selected}",
        )
    return slots.track_ids[selected]


def decode_qwen_track_literal_v3(
    literal: str,
    slots: PublicTrackCandidateSlotsV3,
) -> str | None:
    if literal == "NONE":
        return None
    if literal in slots.track_ids:
        index = slots.track_ids.index(literal)
        if slots.valid_mask[index]:
            return literal
    raise InvalidPublicTrackCandidateV3(
        CandidatePointerErrorCodeV3.INVALID_QWEN_TRACK_LITERAL,
        f"Qwen literal {literal!r} is absent from fresh V3 candidates",
    )
