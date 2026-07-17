"""Safe fusion: semantic proposals may decorate but never replace RGB-D geometry."""
from __future__ import annotations

from .interfaces import PerceptionResultV1


def fuse(geometric: list[PerceptionResultV1], semantic: list[PerceptionResultV1] | None = None) -> list[PerceptionResultV1]:
    if not semantic:
        return geometric
    fused: list[PerceptionResultV1] = []
    for item in geometric:
        match = next((proposal for proposal in semantic if proposal.bbox_or_mask == item.bbox_or_mask), None)
        fused.append(item if match is None else item.model_copy(update={
            "category": match.category,
            "confidence": max(item.confidence, match.confidence),
            "source_components": ["geometric_rgbd_v1", "open_vocab_v1"],
        }))
    return fused
