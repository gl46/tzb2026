"""Explicit QRM model-output to runtime-request materialization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from xh_agent.policy.qrm_lite.contracts import FailureType, QRMObservationV1
from xh_agent.policy.qrm_lite.skill_registry import (
    RuntimeSkillRegistryV1,
    RuntimeSkillRequestV1,
    resolve_registered_skill,
)

if TYPE_CHECKING:
    from xh_agent.policy.qrm_lite.models_q012 import ModelOutput


RECOVERY_STAGE_SKILLS = {
    "RECOVERY_DECISION",
    "REGRASP",
    "REOBSERVE",
    "RETRY_TOP",
    "ALTERNATE_OBLIQUE",
    "ALTERNATE_SIDE",
    "SAFE_PLACE_NON_TARGET",
    "REASSOCIATE_TARGET",
    "RETRY_RELEASE",
    "ABORT_SAFE",
}


def normalize_runtime_phase(stage: str | None) -> str:
    """Normalize only declared recovery-stage labels to RECOVERY."""
    phase = (stage or "OBSERVE").upper()
    return "RECOVERY" if phase in RECOVERY_STAGE_SKILLS else phase


def build_runtime_skill_request(
    observation: QRMObservationV1,
    output: ModelOutput,
    registry: RuntimeSkillRegistryV1,
    *,
    task_target_track_id: str | None = None,
) -> RuntimeSkillRequestV1:
    """Build a versioned request without guessing action frames or units.

    The registry is the sole source of runtime protocol fields.  Target IDs
    may come only from the model output or the public TaskSpec contract.
    """
    if output.coarse is None:
        raise ValueError("model output has no coarse intent")
    failure_active = (
        observation.failure_context.failure_type != FailureType.NONE
    )
    recovery_selected = failure_active and output.recovery_skill is not None
    selected_skill = (
        output.recovery_skill
        if recovery_selected
        else output.coarse.skill_type
    )
    if selected_skill is None:
        raise ValueError("model output has no selected skill")
    class_namespace = "recovery" if recovery_selected else "skill"
    model_class_id = f"coarse.{class_namespace}.{selected_skill}"
    canonical, alias, _ = resolve_registered_skill(registry, selected_skill)
    spec = registry.skills.get(canonical or "")
    parameters: dict[str, object] = {}
    if spec is not None and alias is None and "grasp_family" in (
        set(spec.required_parameters) | set(spec.optional_parameters)
    ):
        grasp_family = output.coarse.grasp_family
        if grasp_family and grasp_family != "unknown":
            parameters["grasp_family"] = grasp_family
    return RuntimeSkillRequestV1(
        model_class_id=model_class_id,
        skill=selected_skill,
        task_target_track_id=(
            task_target_track_id or observation.task_target_track_id
        ),
        model_target_track_id=output.coarse.target_track_id,
        available_track_ids=[
            track.track_id for track in observation.perception_tracks
        ],
        parameters=parameters,
        coordinate_frame=(
            spec.coordinate_frame if spec is not None else "UNRESOLVED"
        ),
        units=spec.units if spec is not None else "UNRESOLVED",
        current_phase=normalize_runtime_phase(observation.current_skill_stage),
        confidence=getattr(output, "confidence", None),
        residual_values=None,
    )
