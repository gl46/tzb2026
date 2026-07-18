"""CLI: smoke-test Qwen3.5 multimodal forward / hidden states / optional LoRA step.

Usage:
  python -m xh_agent.policy.qrm_lite.inspect_backbone --help
  HF_ENDPOINT=https://hf-mirror.com python -m xh_agent.policy.qrm_lite.inspect_backbone \\
      --model-id Qwen/Qwen3.5-4B --device cuda --run-lora-step
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="QRM-Lite Qwen3.5 backbone smoke test")
    p.add_argument("--model-id", default=os.environ.get("QRM_MODEL_ID", "Qwen/Qwen3.5-4B"))
    p.add_argument(
        "--revision",
        default=os.environ.get("QRM_MODEL_REVISION", "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"),
        help="HF revision pin; pass empty string for local model directories",
    )
    p.add_argument("--device", default=None, help="cuda|cpu|mps; default auto")
    p.add_argument("--dtype", default="bfloat16")
    p.add_argument("--cache-dir", default=os.environ.get("HF_HOME"))
    p.add_argument("--local-files-only", action="store_true")
    p.add_argument("--text", default="Describe the industrial tabletop and name a safe grasp skill.")
    p.add_argument("--image", default=None, help="Optional RGB path for multimodal smoke")
    p.add_argument("--run-lora-step", action="store_true")
    p.add_argument("--adapter-out", default="artifacts/qrm_lite/smoke_adapter")
    p.add_argument("--report-json", default="reports/qrm-lite-backbone-smoke.json")
    return p


def _make_dummy_image():
    from PIL import Image
    import numpy as np

    arr = np.zeros((224, 224, 3), dtype=np.uint8)
    arr[:, :] = (30, 90, 180)
    arr[80:140, 80:140] = (200, 80, 40)
    return Image.fromarray(arr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Prefer domestic mirror if user did not set one.
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone

    report: dict = {
        "model_id": args.model_id,
        "revision": args.revision,
        "hf_endpoint": os.environ.get("HF_ENDPOINT"),
        "text_ok": False,
        "multimodal_ok": False,
        "hidden_states_ok": False,
        "lora_step_ok": False,
        "peak_vram_mb": None,
        "forward_seconds": None,
        "error": None,
    }

    try:
        import torch

        revision = args.revision or None
        # Local filesystem model path: do not force a remote revision.
        if Path(args.model_id).exists():
            revision = None
            args.local_files_only = True
        bb = Qwen35Backbone(
            model_id=args.model_id,
            revision=revision or "",
            device=args.device,
            dtype=args.dtype,
            cache_dir=args.cache_dir,
            local_files_only=args.local_files_only,
        )
        # text-only first
        t0 = time.time()
        feats = bb.encode_multimodal({"texts": [args.text], "keep_hidden_states": True})
        report["forward_seconds"] = time.time() - t0
        report["text_ok"] = True
        report["hidden_states_ok"] = feats.hidden_states is not None
        report["pooled_shape"] = list(feats.pooled.shape)
        report["device"] = feats.meta.get("device")
        report["dtype"] = feats.meta.get("dtype")

        # multimodal
        image = None
        if args.image and Path(args.image).exists():
            from PIL import Image

            image = Image.open(args.image).convert("RGB")
        else:
            image = _make_dummy_image()
        feats_m = bb.encode_multimodal(
            {"texts": [args.text], "images": [image], "keep_hidden_states": True}
        )
        report["multimodal_ok"] = True
        report["multimodal_pooled_shape"] = list(feats_m.pooled.shape)

        if torch.cuda.is_available():
            report["peak_vram_mb"] = round(torch.cuda.max_memory_allocated() / (1024**2), 2)

        if args.run_lora_step:
            bb.attach_lora(r=8, alpha=16)
            bb._model.train()
            opt = torch.optim.AdamW([p for p in bb._model.parameters() if p.requires_grad], lr=1e-4)
            opt.zero_grad(set_to_none=True)
            inputs = bb._prepare_batch({"texts": [args.text], "images": [image]})
            # Causal LM loss if labels present; else use pooled feature MSE to a detach target.
            out = bb._model(**inputs, output_hidden_states=True, return_dict=True)
            if hasattr(out, "logits") and out.logits is not None:
                # shift-free dummy: mean logits as scalar loss proxy if no labels
                loss = out.logits.float().pow(2).mean()
            else:
                hidden = out.hidden_states[-1]
                loss = hidden.float().pow(2).mean()
            loss.backward()
            opt.step()
            out_dir = Path(args.adapter_out)
            bb.save_adapter(out_dir)
            # reload smoke
            bb2 = Qwen35Backbone(
                model_id=args.model_id,
                revision=revision or "",
                device=args.device,
                dtype=args.dtype,
                cache_dir=args.cache_dir,
                local_files_only=args.local_files_only,
            )
            bb2.load()
            if (out_dir / "adapter_config.json").exists():
                bb2.load_adapter(out_dir)
            report["lora_step_ok"] = True
            report["lora_loss"] = float(loss.detach().cpu())
            report["adapter_out"] = str(out_dir)

        if torch.cuda.is_available():
            report["peak_vram_mb"] = round(torch.cuda.max_memory_allocated() / (1024**2), 2)
    except Exception as exc:  # noqa: BLE001 - smoke report must capture real failures
        report["error"] = f"{type(exc).__name__}: {exc}"

    out = Path(args.report_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("multimodal_ok") and report.get("error") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
