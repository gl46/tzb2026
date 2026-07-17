"""Pluggable open-vocabulary boundary; no model weight is imported by default."""
from __future__ import annotations

from .interfaces import PerceptionInputV1, PerceptionResultV1


class OpenVocabularyAdapter:
    """A stable adapter for Grounding DINO-style 2-D semantic proposals.

    The adapter intentionally fails closed until an explicitly recorded model
    revision is installed outside Git.  Geometry remains available without it.
    """

    model_name = "GroundingDINO"
    license = "Apache-2.0"

    def infer(self, observation: PerceptionInputV1, prompts: list[str]) -> list[PerceptionResultV1]:
        del observation, prompts
        raise RuntimeError("OPEN_VOCAB_MODEL_NOT_INSTALLED: use geometric_rgbd_v1 fallback")
