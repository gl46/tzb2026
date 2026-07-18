"""Resident Qwen policy service stub for Beta-1 latency measurement.

Not a high-frequency controller. Intended call sites:
- task start
- major skill end
- failure detected
- replan needed
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LatencySample:
    kind: str
    ms: float
    peak_vram_mb: float | None = None
    text_tokens: int | None = None
    vision_tokens: int | None = None


@dataclass
class QwenPolicyService:
    model_id: str
    device: str = "cuda"
    dtype: str = "bfloat16"
    local_files_only: bool = True
    _backbone: Any = field(default=None, repr=False)
    _loaded: bool = False
    cold_start_ms: float | None = None
    samples: list[LatencySample] = field(default_factory=list)

    def start(self) -> None:
        """Load model once (cold start)."""
        if self._loaded:
            return
        t0 = time.perf_counter()
        from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone

        self._backbone = Qwen35Backbone(
            model_id=self.model_id,
            revision="",
            device=self.device,
            dtype=self.dtype,
            local_files_only=self.local_files_only,
        )
        self._backbone.load()
        self.cold_start_ms = (time.perf_counter() - t0) * 1000.0
        self._loaded = True
        self.samples.append(LatencySample(kind="cold_start", ms=self.cold_start_ms))

    def warm_forward(self, text: str, image=None) -> dict[str, Any]:
        self.start()
        assert self._backbone is not None
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        batch: dict[str, Any] = {"texts": [text], "keep_hidden_states": False}
        if image is not None:
            batch["images"] = [image]
        feats = self._backbone.encode_multimodal(batch)
        ms = (time.perf_counter() - t0) * 1000.0
        peak = None
        if torch.cuda.is_available():
            peak = torch.cuda.max_memory_allocated() / (1024**2)
        sample = LatencySample(kind="warm_multimodal" if image is not None else "warm_text", ms=ms, peak_vram_mb=peak)
        self.samples.append(sample)
        return {
            "latency_ms": ms,
            "peak_vram_mb": peak,
            "pooled_shape": list(feats.pooled.shape),
            "device": feats.meta.get("device"),
        }

    def summary(self) -> dict[str, Any]:
        warm = [s.ms for s in self.samples if s.kind.startswith("warm")]
        warm_sorted = sorted(warm)

        def pct(p: float) -> float | None:
            if not warm_sorted:
                return None
            k = min(len(warm_sorted) - 1, max(0, int(round((p / 100.0) * (len(warm_sorted) - 1)))))
            return warm_sorted[k]

        return {
            "model_id": self.model_id,
            "cold_start_ms": self.cold_start_ms,
            "n_warm": len(warm),
            "warm_p50_ms": pct(50),
            "warm_p90_ms": pct(90),
            "target_warm_p50_ms": 5000.0,
            "meets_warm_p50_target": (pct(50) is not None and pct(50) <= 5000.0),
            "note": "8-10s warm latency is acceptable only for post-failure low-frequency decisions",
        }

    def save_report(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")
