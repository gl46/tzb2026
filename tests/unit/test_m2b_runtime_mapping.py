from __future__ import annotations

import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite.skill_registry import (
    MappingRejection,
    RuntimeSkillRequestV1,
    load_registry,
    validate_runtime_mapping,
)


ROOT = Path(__file__).parents[2]
REGISTRY_PATH = ROOT / "configs" / "qrm_runtime_mapping.yaml"


def request(**updates: object) -> RuntimeSkillRequestV1:
    payload = {
        "model_class_id": "coarse.skill.APPROACH",
        "skill": "APPROACH",
        "task_target_track_id": "track-01",
        "available_track_ids": ["track-01", "track-02"],
        "parameters": {},
        "coordinate_frame": "world",
        "units": "m",
        "current_phase": "APPROACH",
        "confidence": 0.9,
    }
    payload.update(updates)
    return RuntimeSkillRequestV1.model_validate(payload)


def test_registry_is_versioned_and_one_to_one() -> None:
    registry = load_registry(REGISTRY_PATH)
    assert registry.schema_version == "RuntimeSkillRegistryV1"
    aliases = [alias for spec in registry.skills.values() for alias in spec.aliases]
    assert len(aliases) == len(set(aliases))


def test_valid_approach_maps_to_b0_parameterized_runtime_skill() -> None:
    result = validate_runtime_mapping(request(), load_registry(REGISTRY_PATH))
    assert result.status == "VALID"
    assert result.canonical_skill == "APPROACH"
    assert result.runtime_action == "B0_PUBLIC_GEOMETRY_APPROACH"
    assert result.target_track_id == "track-01"
    assert result.execution_attribution == "MODEL_SELECTED_B0_PARAMETERIZED_SKILL"
    planning = {
        gate["gate"]: gate["status"]
        for gate in result.gate_trace
        if gate["gate"] in {"ik", "collision", "safety"}
    }
    assert planning == {
        "ik": "NOT_RUN",
        "collision": "NOT_RUN",
        "safety": "NOT_RUN",
    }


def test_explicit_alias_injects_declared_grasp_family() -> None:
    result = validate_runtime_mapping(
        request(
            skill="ALTERNATE_SIDE",
            model_class_id="coarse.recovery.ALTERNATE_SIDE",
            coordinate_frame="world",
            units="m_rad",
            current_phase="RECOVERY",
        ),
        load_registry(REGISTRY_PATH),
    )
    assert result.status == "VALID"
    assert result.canonical_skill == "REGRASP"
    assert result.alias_applied == "ALTERNATE_SIDE"
    assert result.parameters["grasp_family"] == "side"


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"model_output_schema": "CoarseIntentV0"}, MappingRejection.SCHEMA_VERSION_MISMATCH),
        ({"skill": "approach"}, MappingRejection.ALIAS_OR_CASE_MISMATCH),
        ({"skill": "FLY"}, MappingRejection.UNKNOWN_SKILL_ENUM),
        (
            {"model_class_id": "coarse.skill.GRASP"},
            MappingRejection.MODEL_CLASS_SKILL_MISMATCH,
        ),
        (
            {"task_target_track_id": None, "model_target_track_id": None},
            MappingRejection.MISSING_TARGET_TRACK,
        ),
        ({"task_target_track_id": "track-stale"}, MappingRejection.STALE_TRACK),
        ({"parameters": {"speed": 99}}, MappingRejection.UNSUPPORTED_PARAMETER),
        (
            {"parameters": {"grasp_family": "corner"}},
            MappingRejection.INVALID_PARAMETER_VALUE,
        ),
        ({"coordinate_frame": "camera_optical"}, MappingRejection.COORDINATE_FRAME_MISMATCH),
        ({"units": "rad"}, MappingRejection.UNIT_MISMATCH),
        ({"current_phase": "RELEASE"}, MappingRejection.UNSUPPORTED_PHASE),
        ({"residual_values": [[0.0] * 10]}, MappingRejection.OUT_OF_RANGE_RESIDUAL),
    ],
)
def test_mapping_rejection_reasons_are_distinct(
    updates: dict[str, object],
    reason: MappingRejection,
) -> None:
    result = validate_runtime_mapping(
        request(**updates),
        load_registry(REGISTRY_PATH),
    )
    assert result.status == "REJECTED"
    assert result.rejection_reason == reason
    assert result.execution_attribution == "NONE_FALLBACK"


@pytest.mark.parametrize(
    ("check_name", "reason"),
    [
        ("ik_check", MappingRejection.IK_REJECTION),
        ("collision_check", MappingRejection.COLLISION_REJECTION),
        ("safety_check", MappingRejection.SAFETY_REJECTION),
    ],
)
def test_planning_and_safety_rejections_stay_fail_closed(
    check_name: str,
    reason: MappingRejection,
) -> None:
    result = validate_runtime_mapping(
        request(),
        load_registry(REGISTRY_PATH),
        **{check_name: lambda _action, _parameters: (False, "fixture rejection")},
    )
    assert result.status == "REJECTED"
    assert result.rejection_reason == reason
    assert result.fallback_action == "B0_SAFE_HOLD"


def test_checked_in_runtime_schema_matches_model() -> None:
    from xh_agent.policy.qrm_lite.skill_registry import RuntimeSkillRequestV1

    schema = json.loads((ROOT / "schemas" / "runtime-skill-v1.schema.json").read_text())
    assert schema == RuntimeSkillRequestV1.model_json_schema()
