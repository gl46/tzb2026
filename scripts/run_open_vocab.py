#!/usr/bin/env python3
"""Run an optional Grounding DINO semantic proposal outside the control stack."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="IDEA-Research/grounding-dino-tiny")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--prompt", default="industrial cylinder.")
    parser.add_argument("--threshold", type=float, default=0.25)
    args = parser.parse_args()
    if not args.image.is_file():
        raise SystemExit(f"image does not exist: {args.image}")
    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    except ImportError as error:
        raise SystemExit(f"OPEN_VOCAB_DEPENDENCY_MISSING: {error}") from error
    processor = AutoProcessor.from_pretrained(args.model, revision=args.revision)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(args.model, revision=args.revision)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    image = Image.open(args.image).convert("RGB")
    inputs = processor(images=image, text=args.prompt, return_tensors="pt").to(device)
    with torch.inference_mode():
        outputs = model(**inputs)
    target_sizes = torch.tensor([image.size[::-1]], device=device)
    result = processor.post_process_grounded_object_detection(outputs, inputs.input_ids, box_threshold=args.threshold, text_threshold=args.threshold, target_sizes=target_sizes)[0]
    proposals = [{"label": str(label), "score": float(score), "bbox_xyxy": [float(value) for value in box.tolist()]} for label, score, box in zip(result["labels"], result["scores"], result["boxes"])]
    payload = {"backend": "GroundingDINO", "model": args.model, "requested_revision": args.revision, "resolved_revision": getattr(model.config, "_commit_hash", None), "device": device, "prompt": args.prompt, "proposals": proposals, "online_input": {"image": str(args.image)}, "simulator_supervision_used": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "OK", "proposals": len(proposals), "device": device, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
