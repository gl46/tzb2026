"""ADR-0020 runtime mapping for model-owned recovery decisions.

V2 deliberately leaves the V1 registry and B0 actions untouched.  It adds
only the registered destination-cell vocabulary, strict public-track pointer
binding, parameter provenance, and fail-closed pre-execution delegation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.contracts.models import SkillType
from xh_agent.policy.qrm_lite.public_tracks_v2 import PUBLIC_TRACK_SLOT_COUNT
from xh_agent.policy.qrm_lite.skill_registry import RuntimeSkillSpecV1


FROZEN_SCENE_GENERATOR_SHA256 = "e9f9e20106a05dbec24453ce39422d57aa212709567fb7eba7f8d9beb03cd6c5"
DESTINATION_CELL_VALUES = tuple(f"BIN_CELL_{index}" for index in range(6))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ParameterProvenanceV2(str, Enum):
    MODEL = "MODEL"
    TASK_SPEC_FALLBACK = "TASK_SPEC_FALLBACK"
    REGISTRY_ALIAS = "REGISTRY_ALIAS"
    REGISTRY_DERIVED = "REGISTRY_DERIVED"
    NONE = "NONE"


class MappingRejectionV2(str, Enum):
    UNKNOWN_SKILL_ENUM = "UNKNOWN_SKILL_ENUM"
    ALIAS_OR_CASE_MISMATCH = "ALIAS_OR_CASE_MISMATCH"
    MODEL_CLASS_SKILL_MISMATCH = "MODEL_CLASS_SKILL_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    MISSING_MODEL_TARGET = "MISSING_MODEL_TARGET"
    TASK_SPEC_FALLBACK_FORBIDDEN = "TASK_SPEC_FALLBACK_FORBIDDEN"
    INVALID_POINTER = "INVALID_POINTER"
    STALE_TRACK = "STALE_TRACK"
    UNSUPPORTED_PARAMETER = "UNSUPPORTED_PARAMETER"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    MISSING_PARAMETER_PROVENANCE = "MISSING_PARAMETER_PROVENANCE"
    INVALID_PARAMETER_VALUE = "INVALID_PARAMETER_VALUE"
    INVALID_DESTINATION_CELL = "INVALID_DESTINATION_CELL"
    DESTINATION_RESOLUTION_REJECTION = "DESTINATION_RESOLUTION_REJECTION"
    UNSUPPORTED_PHASE = "UNSUPPORTED_PHASE"
    COORDINATE_FRAME_MISMATCH = "COORDINATE_FRAME_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    OUT_OF_RANGE_RESIDUAL = "OUT_OF_RANGE_RESIDUAL"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    IK_REJECTION = "IK_REJECTION"
    COLLISION_REJECTION = "COLLISION_REJECTION"
    SAFETY_REJECTION = "SAFETY_REJECTION"


class RuntimeSkillRegistryV2(StrictModel):
    schema_version: Literal["RuntimeSkillRegistryV2"] = "RuntimeSkillRegistryV2"
    model_output_schema: Literal["CoarseIntentV2"] = "CoarseIntentV2"
    fallback_action: str
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    skills: dict[str, RuntimeSkillSpecV1]

    @model_validator(mode="after")
    def registry_is_one_to_one(self) -> "RuntimeSkillRegistryV2":
        canonical = set(self.skills)
        known = {item.value for item in SkillType}
        unsupported = canonical - known
        if unsupported:
            raise ValueError(f"registry has non-canonical skills: {sorted(unsupported)}")
        aliases = [alias for spec in self.skills.values() for alias in spec.aliases]
        duplicates = sorted(alias for alias in set(aliases) if aliases.count(alias) > 1)
        if duplicates:
            raise ValueError(f"aliases map to multiple skills: {duplicates}")
        collisions = sorted(set(aliases) & canonical)
        if collisions:
            raise ValueError(f"aliases collide with canonical skills: {collisions}")
        class_ids = [class_id for spec in self.skills.values() for class_id in spec.model_class_ids]
        duplicate_class_ids = sorted(
            class_id for class_id in set(class_ids) if class_ids.count(class_id) > 1
        )
        if duplicate_class_ids:
            raise ValueError(f"model class IDs map to multiple skills: {duplicate_class_ids}")
        return self


class RuntimeSkillRequestV2(StrictModel):
    schema_version: Literal["RuntimeSkillRequestV2"] = "RuntimeSkillRequestV2"
    model_output_schema: str = "CoarseIntentV2"
    model_class_id: str
    skill: str
    task_target_track_id: str | None = None
    model_target_track_id: str | None = None
    model_target_slot: int | None = None
    target_track_provenance: ParameterProvenanceV2 = ParameterProvenanceV2.NONE
    canonical_track_ids: list[str | None] = Field(
        min_length=PUBLIC_TRACK_SLOT_COUNT,
        max_length=PUBLIC_TRACK_SLOT_COUNT,
    )
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_provenance: dict[str, ParameterProvenanceV2] = Field(default_factory=dict)
    coordinate_frame: str
    units: str
    current_phase: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    residual_values: list[list[float]] | None = None


class DestinationResolutionV2(StrictModel):
    destination_cell: Literal[
        "BIN_CELL_0",
        "BIN_CELL_1",
        "BIN_CELL_2",
        "BIN_CELL_3",
        "BIN_CELL_4",
        "BIN_CELL_5",
    ]
    world_xyz_m: tuple[float, float, float]
    coordinate_frame: Literal["world"] = "world"
    units: Literal["m"] = "m"
    dimensions: Literal[3] = 3
    frequency: Literal["one_resolution_per_executed_intent"] = "one_resolution_per_executed_intent"
    normalization: Literal["none"] = "none"
    source: Literal["generate_industrial_scenes.bin_cell_targets"] = (
        "generate_industrial_scenes.bin_cell_targets"
    )
    source_sha256: Literal[FROZEN_SCENE_GENERATOR_SHA256] = FROZEN_SCENE_GENERATOR_SHA256


class RuntimeSkillMappingResultV2(StrictModel):
    schema_version: Literal["RuntimeSkillMappingResultV2"] = "RuntimeSkillMappingResultV2"
    status: Literal["VALID", "INVALID"]
    canonical_skill: str | None = None
    runtime_action: str | None = None
    target_track_id: str | None = None
    target_track_slot: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution_parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_provenance: dict[str, ParameterProvenanceV2] = Field(default_factory=dict)
    destination_resolution: DestinationResolutionV2 | None = None
    rejection_reason: MappingRejectionV2 | None = None
    fallback_action: str
    fallback_required: bool = True
    alias_applied: str | None = None
    execution_attribution: Literal[
        "MODEL_SELECTED_REGISTERED_SKILL",
        "MODEL_AND_RESIDUAL",
        "NONE_B0_FALLBACK",
        "NO_PHYSICAL_EXECUTION",
    ] = "NO_PHYSICAL_EXECUTION"
    gate_trace: list[dict[str, Any]] = Field(default_factory=list)


DryRunV2 = Callable[[str, dict[str, Any]], tuple[bool, str | None]]
BinCellTargetsProvider = Callable[[], Sequence[Sequence[float]]]


class DestinationResolutionError(ValueError):
    """The frozen destination source or its output failed closed."""


def load_registry_v2(path: Path) -> RuntimeSkillRegistryV2:
    return RuntimeSkillRegistryV2.model_validate(yaml.safe_load(path.read_text()))


def _resolve_skill(
    registry: RuntimeSkillRegistryV2,
    raw: str,
) -> tuple[str | None, str | None, MappingRejectionV2 | None]:
    if raw in registry.skills:
        return raw, None, None
    for canonical, spec in registry.skills.items():
        if raw in spec.aliases:
            return canonical, raw, None
    known = set(registry.skills)
    known.update(alias for spec in registry.skills.values() for alias in spec.aliases)
    if raw.upper() in {item.upper() for item in known}:
        return None, None, MappingRejectionV2.ALIAS_OR_CASE_MISMATCH
    return None, None, MappingRejectionV2.UNKNOWN_SKILL_ENUM


def resolve_registered_skill_v2(
    registry: RuntimeSkillRegistryV2,
    raw: str,
) -> tuple[str | None, str | None, MappingRejectionV2 | None]:
    """Resolve only exact canonical labels and declared aliases."""

    return _resolve_skill(registry, raw)


def _import_frozen_bin_cell_targets() -> BinCellTargetsProvider:
    try:
        from generate_industrial_scenes import bin_cell_targets
    except ImportError:
        scripts_dir = Path(__file__).resolve().parents[4] / "scripts"
        generator_path = scripts_dir / "generate_industrial_scenes.py"
        if not generator_path.is_file():
            raise DestinationResolutionError(
                "frozen generate_industrial_scenes.bin_cell_targets is unavailable"
            )
        module_name = "_m2c_frozen_generate_industrial_scenes"
        module_spec = importlib.util.spec_from_file_location(
            module_name,
            generator_path,
        )
        if module_spec is None or module_spec.loader is None:
            raise DestinationResolutionError("frozen scene-generator module could not be loaded")
        module = importlib.util.module_from_spec(module_spec)
        original_path = list(sys.path)
        try:
            sys.path.insert(0, str(scripts_dir))
            module_spec.loader.exec_module(module)
        except Exception as exc:
            raise DestinationResolutionError(
                "frozen generate_industrial_scenes.bin_cell_targets is unavailable"
            ) from exc
        finally:
            sys.path[:] = original_path
        bin_cell_targets = module.bin_cell_targets
    return bin_cell_targets


def _verify_frozen_provider(provider: BinCellTargetsProvider) -> None:
    source_file = inspect.getsourcefile(provider)
    if source_file is None:
        raise DestinationResolutionError("bin_cell_targets provider has no auditable source file")
    path = Path(source_file).resolve()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != FROZEN_SCENE_GENERATOR_SHA256:
        raise DestinationResolutionError("bin_cell_targets source SHA-256 does not match ADR-0020")


def resolve_destination_cell_v2(
    destination_cell: str,
    *,
    bin_cell_targets_provider: BinCellTargetsProvider | None = None,
) -> DestinationResolutionV2:
    """Resolve a registered enum only through the frozen scene generator."""

    if destination_cell not in DESTINATION_CELL_VALUES:
        raise DestinationResolutionError(f"unregistered destination cell: {destination_cell!r}")
    provider = bin_cell_targets_provider or _import_frozen_bin_cell_targets()
    _verify_frozen_provider(provider)
    try:
        targets = provider()
    except Exception as exc:
        raise DestinationResolutionError("frozen bin_cell_targets failed") from exc
    if len(targets) != len(DESTINATION_CELL_VALUES):
        raise DestinationResolutionError("frozen bin target count is not six")
    index = int(destination_cell.removeprefix("BIN_CELL_"))
    raw = targets[index]
    if len(raw) != 3:
        raise DestinationResolutionError("destination target is not 3-D")
    coordinates = tuple(float(value) for value in raw)
    if not all(isfinite(value) for value in coordinates):
        raise DestinationResolutionError("destination target contains NaN or Inf")
    return DestinationResolutionV2(
        destination_cell=destination_cell,
        world_xyz_m=coordinates,
    )


def _canonical_slot_error(request: RuntimeSkillRequestV2) -> MappingRejectionV2 | None:
    populated = [item for item in request.canonical_track_ids if item is not None]
    if (
        len(populated) != len(set(populated))
        or populated != sorted(populated)
        or request.canonical_track_ids[: len(populated)] != populated
    ):
        return MappingRejectionV2.INVALID_POINTER
    if request.model_target_slot is not None:
        if not 0 <= request.model_target_slot < PUBLIC_TRACK_SLOT_COUNT:
            return MappingRejectionV2.INVALID_POINTER
        if request.canonical_track_ids[request.model_target_slot] != request.model_target_track_id:
            return MappingRejectionV2.INVALID_POINTER
    return None


def validate_runtime_mapping_v2(
    request: RuntimeSkillRequestV2,
    registry: RuntimeSkillRegistryV2,
    *,
    ik_check: DryRunV2 | None = None,
    collision_check: DryRunV2 | None = None,
    safety_check: DryRunV2 | None = None,
    bin_cell_targets_provider: BinCellTargetsProvider | None = None,
) -> RuntimeSkillMappingResultV2:
    """Map one V2 intent while preserving V1's delegated-gate semantics.

    An injected gate must pass; a rejection, malformed response, or exception
    fails closed.  As in V1, a gate that the caller does not inject is recorded
    as ``NOT_RUN``.  The physical chain runner is responsible for injecting
    all three pre-execution checks before execution.
    """

    trace: list[dict[str, Any]] = []

    def reject(
        gate: str,
        reason: MappingRejectionV2,
        *,
        canonical: str | None = None,
        action: str | None = None,
        target: str | None = None,
        target_slot: int | None = None,
        parameters: dict[str, Any] | None = None,
        execution_parameters: dict[str, Any] | None = None,
        provenance: dict[str, ParameterProvenanceV2] | None = None,
        resolution: DestinationResolutionV2 | None = None,
        alias: str | None = None,
        detail: str | None = None,
    ) -> RuntimeSkillMappingResultV2:
        entry: dict[str, Any] = {
            "gate": gate,
            "status": "INVALID",
            "reason": reason.value,
        }
        if detail is not None:
            entry["detail"] = detail
        trace.append(entry)
        return RuntimeSkillMappingResultV2(
            status="INVALID",
            canonical_skill=canonical,
            runtime_action=action,
            target_track_id=target,
            target_track_slot=target_slot,
            parameters=parameters or {},
            execution_parameters=execution_parameters or {},
            parameter_provenance=provenance or {},
            destination_resolution=resolution,
            rejection_reason=reason,
            fallback_action=registry.fallback_action,
            fallback_required=True,
            alias_applied=alias,
            gate_trace=trace,
        )

    if request.model_output_schema != registry.model_output_schema:
        return reject("schema", MappingRejectionV2.SCHEMA_VERSION_MISMATCH)
    trace.append({"gate": "schema", "status": "PASS"})

    canonical, alias, error = _resolve_skill(registry, request.skill)
    if error is not None or canonical is None:
        return reject("skill", error or MappingRejectionV2.UNKNOWN_SKILL_ENUM)
    spec = registry.skills[canonical]
    trace.append(
        {
            "gate": "skill",
            "status": "PASS",
            "canonical_skill": canonical,
            "alias": alias,
        }
    )
    context = {"canonical": canonical, "action": spec.runtime_action, "alias": alias}

    if request.model_class_id not in spec.model_class_ids:
        return reject(
            "model_class",
            MappingRejectionV2.MODEL_CLASS_SKILL_MISMATCH,
            **context,
        )
    trace.append({"gate": "model_class", "status": "PASS"})
    if request.current_phase not in spec.supported_phases:
        return reject("phase", MappingRejectionV2.UNSUPPORTED_PHASE, **context)
    trace.append({"gate": "phase", "status": "PASS"})
    if request.coordinate_frame != spec.coordinate_frame:
        return reject(
            "coordinate_frame",
            MappingRejectionV2.COORDINATE_FRAME_MISMATCH,
            **context,
        )
    if request.units != spec.units:
        return reject("units", MappingRejectionV2.UNIT_MISMATCH, **context)
    trace.append({"gate": "protocol", "status": "PASS"})

    pointer_error = _canonical_slot_error(request)
    if pointer_error is not None:
        return reject("track_pointer", pointer_error, **context)

    parameters = dict(spec.alias_parameters.get(alias or "", {}))
    provenance: dict[str, ParameterProvenanceV2] = {
        name: ParameterProvenanceV2.REGISTRY_ALIAS for name in parameters
    }
    parameters.update(request.parameters)
    provenance.update(request.parameter_provenance)

    target_required = "target_track_id" in spec.required_parameters
    target_optional = "target_track_id" in spec.optional_parameters
    target = request.model_target_track_id
    target_slot = request.model_target_slot
    target_provenance = request.target_track_provenance
    if request.current_phase == "RECOVERY":
        if target_provenance == ParameterProvenanceV2.TASK_SPEC_FALLBACK:
            return reject(
                "track_provenance",
                MappingRejectionV2.TASK_SPEC_FALLBACK_FORBIDDEN,
                **context,
            )
        if (target_required or target_optional) and target is not None:
            if target_provenance != ParameterProvenanceV2.MODEL:
                return reject(
                    "track_provenance",
                    MappingRejectionV2.MISSING_MODEL_TARGET,
                    **context,
                )
        if target_required and target is None:
            return reject(
                "track_provenance",
                MappingRejectionV2.MISSING_MODEL_TARGET,
                **context,
            )
    elif target is None and (target_required or target_optional):
        target = request.task_target_track_id
        target_provenance = (
            ParameterProvenanceV2.TASK_SPEC_FALLBACK
            if target is not None
            else ParameterProvenanceV2.NONE
        )
        if target is not None:
            try:
                target_slot = request.canonical_track_ids.index(target)
            except ValueError:
                target_slot = None

    if target_required and target is None:
        return reject("track", MappingRejectionV2.MISSING_MODEL_TARGET, **context)
    if target is not None and (target_required or target_optional):
        if target not in request.canonical_track_ids:
            return reject(
                "track",
                MappingRejectionV2.STALE_TRACK,
                target=target,
                **context,
            )
        actual_slot = request.canonical_track_ids.index(target)
        if target_slot != actual_slot:
            return reject(
                "track_pointer",
                MappingRejectionV2.INVALID_POINTER,
                target=target,
                target_slot=target_slot,
                **context,
            )
        parameters["target_track_id"] = target
        provenance["target_track_id"] = target_provenance
    trace.append(
        {
            "gate": "track",
            "status": "PASS",
            "target": target,
            "slot": target_slot,
            "provenance": target_provenance.value,
        }
    )

    allowed = set(spec.required_parameters) | set(spec.optional_parameters)
    unsupported = set(parameters) - allowed
    if unsupported:
        return reject(
            "parameters",
            MappingRejectionV2.UNSUPPORTED_PARAMETER,
            target=target,
            target_slot=target_slot,
            parameters=parameters,
            provenance=provenance,
            **context,
        )
    missing = set(spec.required_parameters) - set(parameters)
    if missing:
        return reject(
            "parameters",
            MappingRejectionV2.MISSING_PARAMETER,
            target=target,
            target_slot=target_slot,
            parameters=parameters,
            provenance=provenance,
            **context,
        )
    missing_provenance = set(parameters) - set(provenance)
    if missing_provenance:
        return reject(
            "parameter_provenance",
            MappingRejectionV2.MISSING_PARAMETER_PROVENANCE,
            target=target,
            target_slot=target_slot,
            parameters=parameters,
            provenance=provenance,
            **context,
        )
    for name, allowed_values in spec.parameter_enums.items():
        if name in parameters and parameters[name] not in allowed_values:
            reason = (
                MappingRejectionV2.INVALID_DESTINATION_CELL
                if name == "destination"
                else MappingRejectionV2.INVALID_PARAMETER_VALUE
            )
            return reject(
                "parameters",
                reason,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                provenance=provenance,
                **context,
            )
    for name, (minimum, maximum) in spec.parameter_ranges.items():
        if name not in parameters:
            continue
        value = parameters[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            or not minimum <= float(value) <= maximum
        ):
            return reject(
                "parameters",
                MappingRejectionV2.INVALID_PARAMETER_VALUE,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                provenance=provenance,
                **context,
            )
    trace.append({"gate": "parameters", "status": "PASS"})

    resolution: DestinationResolutionV2 | None = None
    execution_parameters = dict(parameters)
    if "destination" in parameters:
        try:
            resolution = resolve_destination_cell_v2(
                str(parameters["destination"]),
                bin_cell_targets_provider=bin_cell_targets_provider,
            )
        except (DestinationResolutionError, IndexError, TypeError, ValueError) as exc:
            return reject(
                "destination_resolution",
                MappingRejectionV2.DESTINATION_RESOLUTION_REJECTION,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                provenance=provenance,
                **context,
                detail=str(exc),
            )
        execution_parameters["destination_world_xyz_m"] = list(resolution.world_xyz_m)
        provenance["destination_world_xyz_m"] = ParameterProvenanceV2.REGISTRY_DERIVED
        trace.append(
            {
                "gate": "destination_resolution",
                "status": "PASS",
                "coordinate_frame": "world",
                "units": "m",
                "dimensions": 3,
                "normalization": "none",
            }
        )

    if request.confidence is not None and request.confidence < registry.minimum_confidence:
        return reject(
            "confidence",
            MappingRejectionV2.LOW_CONFIDENCE,
            target=target,
            target_slot=target_slot,
            parameters=parameters,
            execution_parameters=execution_parameters,
            provenance=provenance,
            resolution=resolution,
            **context,
        )
    trace.append({"gate": "confidence", "status": "PASS"})
    if request.residual_values is not None:
        values = [value for row in request.residual_values for value in row]
        if not all(isfinite(value) for value in values) or not spec.residual_allowed:
            return reject(
                "residual",
                MappingRejectionV2.OUT_OF_RANGE_RESIDUAL,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                execution_parameters=execution_parameters,
                provenance=provenance,
                resolution=resolution,
                **context,
            )
    trace.append({"gate": "residual", "status": "PASS"})

    for name, check, reason in (
        ("ik", ik_check, MappingRejectionV2.IK_REJECTION),
        ("collision", collision_check, MappingRejectionV2.COLLISION_REJECTION),
        ("safety", safety_check, MappingRejectionV2.SAFETY_REJECTION),
    ):
        if check is None:
            trace.append({"gate": name, "status": "NOT_RUN"})
            continue
        try:
            accepted, detail = check(spec.runtime_action, execution_parameters)
        except Exception as exc:  # fail closed on delegated-gate failures
            return reject(
                name,
                reason,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                execution_parameters=execution_parameters,
                provenance=provenance,
                resolution=resolution,
                **context,
                detail=f"{type(exc).__name__}: {exc}",
            )
        if not isinstance(accepted, bool):
            return reject(
                name,
                reason,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                execution_parameters=execution_parameters,
                provenance=provenance,
                resolution=resolution,
                **context,
                detail="delegated gate did not return a boolean decision",
            )
        if not accepted:
            return reject(
                name,
                reason,
                target=target,
                target_slot=target_slot,
                parameters=parameters,
                execution_parameters=execution_parameters,
                provenance=provenance,
                resolution=resolution,
                **context,
                detail=detail,
            )
        trace.append({"gate": name, "status": "PASS", "detail": detail})

    return RuntimeSkillMappingResultV2(
        status="VALID",
        canonical_skill=canonical,
        runtime_action=spec.runtime_action,
        target_track_id=target,
        target_track_slot=target_slot,
        parameters=parameters,
        execution_parameters=execution_parameters,
        parameter_provenance=provenance,
        destination_resolution=resolution,
        fallback_action=registry.fallback_action,
        fallback_required=False,
        alias_applied=alias,
        execution_attribution=(
            "MODEL_AND_RESIDUAL"
            if request.residual_values is not None
            else "MODEL_SELECTED_REGISTERED_SKILL"
        ),
        gate_trace=trace,
    )
