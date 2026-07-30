"""TaskSpec compilation boundaries for the M1B-beta non-Oracle baseline."""

from .base import TaskSpecV1
from .deterministic import DeterministicTaskCompiler

__all__ = ["DeterministicTaskCompiler", "TaskSpecV1"]
