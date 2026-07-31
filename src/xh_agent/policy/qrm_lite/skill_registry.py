"""Versioned model-skill to runtime-action mapping with fail-closed reasons."""

from __future__ import annotations

from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.contracts.models import SkillType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MappingRejection(str, Enum):
    UNKNOWN_SKILL_ENUM = "UNKNOWN_SKILL_ENUM"
    ALIAS_OR_CASE_MISMATCH = "ALIAS_OR_CASE_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    MISSING_TARGET_TRACK = "MISSING_TARGET_TRACK"
    STALE_TRACK = "STALE_TRACK"
    UNSUPPORTED_PARAMETER = "UNSUPPORTED_PARAMETER"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    UNSUPPORTED_PHASE = "UNSUPPORTED_PHASE"
    COORDINATE_FRAME_MISMATCH = "COORDINATE_FRAME_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    OUT_OF_RANGE_RESIDUAL = "OUT_OF_RANGE_RESIDUAL"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    IK_REJECTION = "IK_REJECTION"
    COLLISION_REJECTION = "COLLISION_REJECTION"
    SAFETY_REJECTION = "SAFETY_REJECTION"


class RuntimeSkillSpecV1(StrictModel):
    aliases: list[str] = Field(default_factory=list)
    alias_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    runtime_action: str
    required_parameters: list[str] = Field(default_factory=list)
    optional_parameters: list[str] = Field(default_factory=list)
    coordinate_frame: str
    units: str
    supported_phases: list[str] = Field(min_length=1)
    residual_allowed: bool = False

    @model_validator(mode="after")
    def aliases_have_known_defaults(self) -> "RuntimeSkillSpecV1":
        unknown = set(self.alias_parameters) - set(self.aliases)
        if unknown:
            raise ValueError(
                f"alias_parameters contains undeclared aliases: {sorted(unknown)}"
            )
        return self


class RuntimeSkillRegistryV1(StrictModel):
    schema_version: Literal["RuntimeSkillRegistryV1"] = (
        "RuntimeSkillRegistryV1"
    )
    model_output_schema: Literal["CoarseIntentV1"] = "CoarseIntentV1"
    fallback_action: str
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    skills: dict[str, RuntimeSkillSpecV1]

    @model_validator(mode="after")
    def registry_is_one_to_one(self) -> "RuntimeSkillRegistryV1":
        canonical = set(self.skills)
        known = {item.value for item in SkillType}
        unsupported = canonical - known
        if unsupported:
            raise ValueError(
                f"registry has non-canonical skills: {sorted(unsupported)}"
            )
        aliases = [
            alias for spec in self.skills.values() for alias in spec.aliases
        ]
        duplicates = sorted(
            alias for alias in set(aliases) if aliases.count(alias) > 1
        )
        if duplicates:
            raise ValueError(f"aliases map to multiple skills: {duplicates}")
        collisions = sorted(set(aliases) & canonical)
        if collisions:
            raise ValueError(f"aliases collide with canonical skills: {collisions}")
        return self


class RuntimeSkillRequestV1(StrictModel):
    schema_version: Literal["RuntimeSkillRequestV1"] = "RuntimeSkillRequestV1"
    model_output_schema: str = "CoarseIntentV1"
    model_class_id: str
    skill: str
    task_target_track_id: str | None = None
    model_target_track_id: str | None = None
    available_track_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    coordinate_frame: str
    units: str
    current_phase: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    residual_values: list[list[float]] | None = None


class RuntimeSkillMappingResultV1(StrictModel):
    schema_version: Literal["RuntimeSkillMappingResultV1"] = (
        "RuntimeSkillMappingResultV1"
    )
    status: Literal["VALID", "REJECTED"]
    canonical_skill: str | None = None
    runtime_action: str | None = None
    target_track_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    rejection_reason: MappingRejection | None = None
    fallback_action: str
    alias_applied: str | None = None
    execution_attribution: Literal[
        "MODEL_SELECTED_B0_PARAMETERIZED_SKILL",
        "MODEL_AND_RESIDUAL",
        "NONE_FALLBACK",
    ] = "NONE_FALLBACK"
    gate_trace: list[dict[str, Any]] = Field(default_factory=list)


DryRun = Callable[[str, dict[str, Any]], tuple[bool, str | None]]


def load_registry(path: Path) -> RuntimeSkillRegistryV1:
    return RuntimeSkillRegistryV1.model_validate(
        yaml.safe_load(path.read_text())
    )


def _resolve_skill(
    registry: RuntimeSkillRegistryV1,
    raw: str,
) -> tuple[str | None, str | None, MappingRejection | None]:
    if raw in registry.skills:
        return raw, None, None
    for canonical, spec in registry.skills.items():
        if raw in spec.aliases:
            return canonical, raw, None
    known = set(registry.skills)
    known.update(alias for spec in registry.skills.values() for alias in spec.aliases)
    if raw.upper() in {item.upper() for item in known}:
        return None, None, MappingRejection.ALIAS_OR_CASE_MISMATCH
    return None, None, MappingRejection.UNKNOWN_SKILL_ENUM


def validate_runtime_mapping(
    request: RuntimeSkillRequestV1,
    registry: RuntimeSkillRegistryV1,
    *,
    ik_check: DryRun | None = None,
    collision_check: DryRun | None = None,
    safety_check: DryRun | None = None,
) -> RuntimeSkillMappingResultV1:
    trace: list[dict[str, Any]] = []

    def reject(
        gate: str,
        reason: MappingRejection,
    ) -> RuntimeSkillMappingResultV1:
        trace.append({"gate": gate, "status": "REJECTED", "reason": reason.value})
        return RuntimeSkillMappingResultV1(
            status="REJECTED",
            rejection_reason=reason,
            fallback_action=registry.fallback_action,
            gate_trace=trace,
        )

    if request.model_output_schema != registry.model_output_schema:
        return reject("schema", MappingRejection.SCHEMA_VERSION_MISMATCH)
    trace.append({"gate": "schema", "status": "PASS"})
    canonical, alias, error = _resolve_skill(registry, request.skill)
    if error is not None or canonical is None:
        return reject("skill", error or MappingRejection.UNKNOWN_SKILL_ENUM)
    trace.append(
        {
            "gate": "skill",
            "status": "PASS",
            "canonical_skill": canonical,
            "alias": alias,
        }
    )
    spec = registry.skills[canonical]
    if request.current_phase not in spec.supported_phases:
        return reject("phase", MappingRejection.UNSUPPORTED_PHASE)
    trace.append({"gate": "phase", "status": "PASS"})
    if request.coordinate_frame != spec.coordinate_frame:
        return reject("coordinate_frame", MappingRejection.COORDINATE_FRAME_MISMATCH)
    if request.units != spec.units:
        return reject("units", MappingRejection.UNIT_MISMATCH)
    trace.append({"gate": "protocol", "status": "PASS"})
    parameters = dict(spec.alias_parameters.get(alias or "", {}))
    parameters.update(request.parameters)
    target = request.model_target_track_id or request.task_target_track_id
    if "target_track_id" in spec.required_parameters:
        if not target:
            return reject("track", MappingRejection.MISSING_TARGET_TRACK)
        if target not in request.available_track_ids:
            return reject("track", MappingRejection.STALE_TRACK)
        parameters["target_track_id"] = target
    trace.append({"gate": "track", "status": "PASS", "target": target})
    allowed = set(spec.required_parameters) | set(spec.optional_parameters)
    unsupported = set(parameters) - allowed
    if unsupported:
        return reject("parameters", MappingRejection.UNSUPPORTED_PARAMETER)
    missing = set(spec.required_parameters) - set(parameters)
    if missing:
        return reject("parameters", MappingRejection.MISSING_PARAMETER)
    trace.append({"gate": "parameters", "status": "PASS"})
    if request.confidence is not None and request.confidence < registry.minimum_confidence:
        return reject("confidence", MappingRejection.LOW_CONFIDENCE)
    trace.append({"gate": "confidence", "status": "PASS"})
    if request.residual_values is not None:
        values = [value for row in request.residual_values for value in row]
        valid = all(isfinite(value) for value in values)
        if not valid or not spec.residual_allowed:
            return reject("residual", MappingRejection.OUT_OF_RANGE_RESIDUAL)
    trace.append({"gate": "residual", "status": "PASS"})
    for name, check, reason in (
        ("ik", ik_check, MappingRejection.IK_REJECTION),
        ("collision", collision_check, MappingRejection.COLLISION_REJECTION),
        ("safety", safety_check, MappingRejection.SAFETY_REJECTION),
    ):
        if check is not None:
            accepted, detail = check(spec.runtime_action, parameters)
            if not accepted:
                trace.append(
                    {"gate": name, "status": "REJECTED", "detail": detail}
                )
                return RuntimeSkillMappingResultV1(
                    status="REJECTED",
                    canonical_skill=canonical,
                    runtime_action=spec.runtime_action,
                    target_track_id=target,
                    parameters=parameters,
                    rejection_reason=reason,
                    fallback_action=registry.fallback_action,
                    alias_applied=alias,
                    gate_trace=trace,
                )
        trace.append({"gate": name, "status": "PASS"})
    residual_used = request.residual_values is not None
    return RuntimeSkillMappingResultV1(
        status="VALID",
        canonical_skill=canonical,
        runtime_action=spec.runtime_action,
        target_track_id=target,
        parameters=parameters,
        fallback_action=registry.fallback_action,
        alias_applied=alias,
        execution_attribution=(
            "MODEL_AND_RESIDUAL"
            if residual_used
            else "MODEL_SELECTED_B0_PARAMETERIZED_SKILL"
        ),
        gate_trace=trace,
    )
