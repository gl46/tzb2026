"""Optional Qwen boundary which intentionally has no bundled language model."""

from __future__ import annotations

from .base import TaskSpecV1


class QwenTaskCompilerAdapter:
    def compile(self, instruction: str) -> TaskSpecV1:
        del instruction
        raise RuntimeError("QWEN_SMOKE_DISABLED: deterministic compiler is the M1B-beta baseline")
