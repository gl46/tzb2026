"""Qwen3.5 multimodal backbone wrapper for QRM-Lite.

Importing this module must not download weights or allocate GPU memory.
Heavy deps (torch/transformers/peft) are imported lazily inside methods.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_MODEL_ID = "Qwen/Qwen3.5-4B"
DEFAULT_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"


@dataclass
class BackboneFeatures:
    pooled: Any  # torch.Tensor [B, H]
    hidden_states: Any | None = None
    attention_mask: Any | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyContextFeatures:
    backbone: BackboneFeatures
    context_vector: Any  # torch.Tensor [B, C]
    meta: dict[str, Any] = field(default_factory=dict)


class Qwen35Backbone:
    """Lazy-loading multimodal encoder + optional LoRA adapters."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        revision: str = DEFAULT_REVISION,
        *,
        device: str | None = None,
        dtype: str = "bfloat16",
        cache_dir: str | None = None,
        local_files_only: bool = False,
        trust_remote_code: bool = True,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.device_pref = device
        self.dtype_name = dtype
        self.cache_dir = cache_dir or os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
        self.local_files_only = local_files_only
        self.trust_remote_code = trust_remote_code
        self._model = None
        self._processor = None
        self._device = None
        self._dtype = None
        self._peft_attached = False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _resolve_device_dtype(self):
        import torch

        if self.device_pref:
            device = torch.device(self.device_pref)
        else:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dtype_map = {
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
            "float16": torch.float16,
            "fp16": torch.float16,
            "float32": torch.float32,
            "fp32": torch.float32,
        }
        dtype = dtype_map.get(self.dtype_name, torch.bfloat16)
        if device.type == "cpu" and dtype in {torch.bfloat16, torch.float16}:
            # keep bf16 on CPU if available; else fall back
            dtype = torch.float32
        return device, dtype

    def load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self._device, self._dtype = self._resolve_device_dtype()
        kwargs: dict[str, Any] = {
            "trust_remote_code": self.trust_remote_code,
            "local_files_only": self.local_files_only,
        }
        # Local directories / empty revision should not pass a bogus revision pin.
        if self.revision:
            kwargs["revision"] = self.revision
        if self.cache_dir:
            kwargs["cache_dir"] = self.cache_dir

        self._processor = AutoProcessor.from_pretrained(self.model_id, **kwargs)
        model_kwargs = dict(kwargs)
        # transformers>=4.46 prefers dtype=; keep torch_dtype as fallback for older builds.
        model_kwargs["dtype"] = self._dtype
        try:
            self._model = AutoModelForImageTextToText.from_pretrained(self.model_id, **model_kwargs)
        except TypeError:
            model_kwargs.pop("dtype", None)
            model_kwargs["torch_dtype"] = self._dtype
            self._model = AutoModelForImageTextToText.from_pretrained(self.model_id, **model_kwargs)
        self._model.to(self._device)
        self._model.eval()

    def attach_lora(
        self,
        *,
        r: int = 8,
        alpha: int = 16,
        dropout: float = 0.05,
        target_modules: list[str] | None = None,
    ) -> None:
        self.load()
        from peft import LoraConfig, get_peft_model

        if self._peft_attached:
            return
        # Conservative targets; if modules missing, peft will raise and caller can adjust.
        targets = target_modules or ["q_proj", "k_proj", "v_proj", "o_proj"]
        cfg = LoraConfig(
            r=r,
            lora_alpha=alpha,
            lora_dropout=dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=targets,
        )
        self._model = get_peft_model(self._model, cfg)
        self._model.train()
        self._peft_attached = True

    def _prepare_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        """batch keys: texts:list[str], images: optional list of PIL/np/path.

        Qwen3.5 / Qwen3-VL processors require chat-template image placeholders so that
        image token counts match vision features. Plain text+images without template
        yields tokens:0 features:N errors.
        """
        self.load()
        assert self._processor is not None
        texts = batch["texts"]
        images = batch.get("images")
        if images is None:
            # text-only: still prefer chat template when available
            rendered: list[str] = []
            for t in texts:
                if hasattr(self._processor, "apply_chat_template"):
                    messages = [{"role": "user", "content": [{"type": "text", "text": t}]}]
                    rendered.append(
                        self._processor.apply_chat_template(
                            messages, tokenize=False, add_generation_prompt=True
                        )
                    )
                else:
                    rendered.append(t)
            proc = self._processor(text=rendered, return_tensors="pt", padding=True)
        else:
            if len(images) != len(texts):
                raise ValueError("texts and images must have the same batch size")
            rendered = []
            for t, img in zip(texts, images):
                if hasattr(self._processor, "apply_chat_template"):
                    messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "image": img},
                                {"type": "text", "text": t},
                            ],
                        }
                    ]
                    rendered.append(
                        self._processor.apply_chat_template(
                            messages, tokenize=False, add_generation_prompt=True
                        )
                    )
                else:
                    rendered.append(t)
            proc = self._processor(
                text=rendered, images=images, return_tensors="pt", padding=True
            )
        return {k: (v.to(self._device) if hasattr(v, "to") else v) for k, v in proc.items()}

    @staticmethod
    def _pool_hidden(hidden: Any, attention_mask: Any | None) -> Any:
        # hidden: [B, T, H]
        if attention_mask is None:
            return hidden.mean(dim=1)
        mask = attention_mask.unsqueeze(-1).to(hidden.dtype)
        summed = (hidden * mask).sum(dim=1)
        denom = mask.sum(dim=1).clamp(min=1.0)
        return summed / denom

    def encode_multimodal(self, batch: dict[str, Any]) -> BackboneFeatures:
        self.load()
        import torch

        assert self._model is not None
        inputs = self._prepare_batch(batch)
        with torch.set_grad_enabled(bool(batch.get("requires_grad", False))):
            outputs = self._model(
                **inputs,
                output_hidden_states=True,
                return_dict=True,
                use_cache=False,
            )
        hidden_states = outputs.hidden_states
        last = hidden_states[-1]
        attn = inputs.get("attention_mask")
        pooled = self._pool_hidden(last, attn)
        return BackboneFeatures(
            pooled=pooled,
            hidden_states=hidden_states if batch.get("keep_hidden_states") else None,
            attention_mask=attn,
            meta={
                "model_id": self.model_id,
                "revision": self.revision,
                "device": str(self._device),
                "dtype": str(self._dtype),
            },
        )

    def forward_policy_context(self, batch: dict[str, Any]) -> PolicyContextFeatures:
        feats = self.encode_multimodal(batch)
        # Context vector is backbone pooled features; extra projections live in context.py.
        return PolicyContextFeatures(backbone=feats, context_vector=feats.pooled, meta=dict(feats.meta))

    def save_adapter(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        if self._model is None:
            raise RuntimeError("model not loaded")
        if hasattr(self._model, "save_pretrained") and self._peft_attached:
            self._model.save_pretrained(path)
        else:
            # Save a tiny marker + optional full state if requested
            marker = {
                "model_id": self.model_id,
                "revision": self.revision,
                "peft_attached": self._peft_attached,
            }
            (path / "adapter_marker.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
            if bool(os.environ.get("QRM_SAVE_FULL_STATE", "0") == "1"):
                import torch

                torch.save(self._model.state_dict(), path / "full_state.pt")

    def load_adapter(self, path: str | Path) -> None:
        """Load a saved LoRA adapter for inference without mutating base weights."""

        path = Path(path)
        self.load()
        if self._peft_attached:
            raise RuntimeError("a LoRA adapter is already attached")
        if (path / "adapter_config.json").exists():
            from peft import PeftModel

            self._model = PeftModel.from_pretrained(
                self._model,
                str(path),
                is_trainable=False,
            )
            self._model.eval()
            self._peft_attached = True
            return
        marker = path / "adapter_marker.json"
        if marker.exists():
            return
        raise FileNotFoundError(f"no adapter found under {path}")


def assert_import_is_side_effect_free() -> None:
    """Used by unit tests: constructing the class must not touch GPU."""
    _ = Qwen35Backbone(local_files_only=True)
