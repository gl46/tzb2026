"""Materialize one ADR-0020 model intent into a strict V2 request."""

from __future__ import annotations

from typing import Any

from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV2,
    FailureType,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import canonical_track_slots
from xh_agent.policy.qrm_lite.runtime_adapter import normalize_runtime_phase
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    ParameterProvenanceV2,
    RuntimeSkillRegistryV2,
    RuntimeSkillRequestV2,
    resolve_registered_skill_v2,
)


def _coarse_intent_v2(model_decision: Any) -> CoarseIntentV2:
    if isinstance(model_decision, CoarseIntentV2):
        return model_decision
    coarse = getattr(model_decision, "coarse", None)
    if not isinstance(coarse, CoarseIntentV2):
        raise ValueError("model decision has no CoarseIntentV2 intent")
    return coarse


def _selected_skill(
    observation: QRMObservationV1,
    model_decision: Any,
    intent: CoarseIntentV2,
) -> str:
    failure_active = observation.failure_context.failure_type != FailureType.NONE
    recovery_skill = getattr(model_decision, "recovery_skill", None)
    if failure_active and recovery_skill is not None:
        return str(recovery_skill)
    return intent.skill_type


def _model_class_id(
    selected_skill: str,
    current_phase: str,
    registry: RuntimeSkillRegistryV2,
) -> str:
    canonical, _, _ = resolve_registered_skill_v2(registry, selected_skill)
    spec = registry.skills.get(canonical or "")
    candidates = []
    if current_phase == "RECOVERY":
        candidates.append(f"coarse.recovery.{selected_skill}")
    candidates.append(f"coarse.skill.{selected_skill}")
    if spec is not None:
        for candidate in candidates:
            if candidate in spec.model_class_ids:
                return candidate
    return candidates[0]


def build_runtime_skill_request_v2(
    observation: QRMObservationV1,
    model_decision: Any,
    registry: RuntimeSkillRegistryV2,
    *,
    task_target_track_id: str | None = None,
) -> RuntimeSkillRequestV2:
    """Bind a V2 model decision to the fresh canonical public-track slots.

    During RECOVERY, an absent model pointer remains absent even if TaskSpec
    carries a target.  The validator therefore cannot silently substitute the
    task target for a blocker or any later model-owned chain target.
    """

    intent = _coarse_intent_v2(model_decision)
    current_phase = normalize_runtime_phase(observation.current_skill_stage)
    selected_skill = _selected_skill(observation, model_decision, intent)
    canonical, alias, _ = resolve_registered_skill_v2(registry, selected_skill)
    spec = registry.skills.get(canonical or "")

    slots = canonical_track_slots(observation.perception_tracks)
    canonical_track_ids = list(slots.track_ids)
    model_target_slot: int | None = None
    if intent.target_track_id is not None:
        try:
            model_target_slot = canonical_track_ids.index(intent.target_track_id)
        except ValueError:
            model_target_slot = None

    parameters: dict[str, object] = {}
    parameter_provenance: dict[str, ParameterProvenanceV2] = {}
    allowed = (
        set(spec.required_parameters) | set(spec.optional_parameters) if spec is not None else set()
    )
    if (
        spec is not None
        and alias is None
        and "grasp_family" in allowed
        and intent.grasp_family
        and intent.grasp_family != "unknown"
    ):
        parameters["grasp_family"] = intent.grasp_family
        parameter_provenance["grasp_family"] = ParameterProvenanceV2.MODEL
    if intent.destination_cell is not None:
        parameters["destination"] = intent.destination_cell
        parameter_provenance["destination"] = ParameterProvenanceV2.MODEL

    public_task_target = task_target_track_id or observation.task_target_track_id
    target_provenance = (
        ParameterProvenanceV2.MODEL
        if intent.target_track_id is not None
        else ParameterProvenanceV2.NONE
    )
    if (
        current_phase != "RECOVERY"
        and intent.target_track_id is None
        and public_task_target is not None
        and "target_track_id" in allowed
    ):
        target_provenance = ParameterProvenanceV2.TASK_SPEC_FALLBACK

    confidence = getattr(model_decision, "confidence", None)
    return RuntimeSkillRequestV2(
        model_class_id=_model_class_id(
            selected_skill,
            current_phase,
            registry,
        ),
        skill=selected_skill,
        task_target_track_id=public_task_target,
        model_target_track_id=intent.target_track_id,
        model_target_slot=model_target_slot,
        target_track_provenance=target_provenance,
        canonical_track_ids=canonical_track_ids,
        parameters=parameters,
        parameter_provenance=parameter_provenance,
        coordinate_frame=(spec.coordinate_frame if spec is not None else "UNRESOLVED"),
        units=spec.units if spec is not None else "UNRESOLVED",
        current_phase=current_phase,
        confidence=confidence,
        residual_values=None,
    )
