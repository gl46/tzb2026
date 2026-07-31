"""Inference loader for trained Qwen LoRA coarse recovery adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone
from xh_agent.policy.qrm_lite.coarse_prompt import coarse_prompt
from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV1,
    FailureType,
    QRMObservationV1,
)


@dataclass(frozen=True)
class QwenCoarsePrediction:
    coarse: CoarseIntentV1
    recovery_skill: str | None
    confidence: float
    probabilities: dict[str, float]
    used_failure_context: bool
    model_id: str = "QWEN35_LORA_COARSE_M2B"


def prediction_from_probabilities(
    observation: QRMObservationV1,
    probabilities: dict[str, float],
    *,
    use_failure_context: bool,
) -> QwenCoarsePrediction:
    if not probabilities:
        raise ValueError("coarse prediction probabilities are empty")
    skill, confidence = max(
        probabilities.items(), key=lambda item: (item[1], item[0])
    )
    failure_active = observation.failure_context.failure_type != FailureType.NONE
    action_target_track_id = (
        observation.failure_context.last_carried_track_id
        if skill in {"SAFE_PLACE_NON_TARGET", "RETRY_RELEASE"}
        and observation.failure_context.last_carried_track_id
        else observation.task_target_track_id
    )
    return QwenCoarsePrediction(
        coarse=CoarseIntentV1(
            skill_type=skill,
            target_track_id=action_target_track_id,
            recovery_mode=(
                observation.failure_context.failure_type.value.lower()
                if failure_active
                else "none"
            ),
            reobserve_flag=skill == "REOBSERVE",
            failure_type_aux=(
                observation.failure_context.failure_type
                if failure_active
                else None
            ),
        ),
        recovery_skill=skill if failure_active else None,
        confidence=float(confidence),
        probabilities=dict(probabilities),
        used_failure_context=use_failure_context,
    )


class QwenCoarseRecoveryPolicy:
    def __init__(
        self,
        *,
        model_id: str,
        adapter_path: Path,
        head_path: Path | None = None,
        revision: str = "",
        device: str = "cuda",
    ) -> None:
        import torch

        self.backbone = Qwen35Backbone(
            model_id=model_id,
            revision=revision,
            device=device,
            dtype="bfloat16",
            local_files_only=Path(model_id).exists(),
        )
        self.backbone.load_adapter(adapter_path)
        state = torch.load(
            head_path or adapter_path / "coarse_head.pt",
            map_location="cpu",
            weights_only=True,
        )
        self.labels = [str(label) for label in state["labels"]]
        self.use_failure_context = state["failure_context"] == "on"
        hidden_size = int(state["hidden_size"])
        assert self.backbone._device is not None
        self.classifier = torch.nn.Linear(
            hidden_size,
            len(self.labels),
            device=self.backbone._device,
            dtype=torch.float32,
        )
        self.classifier.load_state_dict(state["classifier_state_dict"])
        self.classifier.eval()

    def predict(
        self,
        observation: QRMObservationV1,
        image: Image.Image | str | Path,
    ) -> QwenCoarsePrediction:
        import torch

        public_image = (
            Image.open(image).convert("RGB")
            if isinstance(image, (str, Path))
            else image.convert("RGB")
        )
        with torch.no_grad():
            features = self.backbone.encode_multimodal(
                {
                    "texts": [
                        coarse_prompt(
                            observation,
                            use_failure_context=self.use_failure_context,
                            allowed_skills=self.labels,
                        )
                    ],
                    "images": [public_image],
                }
            )
            logits = self.classifier(features.pooled.float())
            values = torch.softmax(logits, dim=-1)[0].detach().cpu().tolist()
        probabilities: dict[str, Any] = dict(zip(self.labels, values))
        return prediction_from_probabilities(
            observation,
            probabilities,
            use_failure_context=self.use_failure_context,
        )
