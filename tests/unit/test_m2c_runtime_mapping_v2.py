from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import generate_industrial_scenes as scene_generator
from generate_industrial_scenes import bin_cell_targets
from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV2,
    FailureContextV1,
    FailureType,
    PerceptionTrackV1,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.runtime_adapter_v2 import (
    build_runtime_skill_request_v2,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    DESTINATION_CELL_VALUES,
    FROZEN_SCENE_GENERATOR_SHA256,
    DestinationResolutionError,
    MappingRejectionV2,
    ParameterProvenanceV2,
    RuntimeSkillRegistryV2,
    RuntimeSkillRequestV2,
    load_registry_v2,
    resolve_destination_cell_v2,
    validate_runtime_mapping_v2,
)


ROOT = Path(__file__).resolve().parents[2]
V1_PATH = ROOT / "configs/qrm_runtime_mapping.yaml"
V2_PATH = ROOT / "configs/qrm_runtime_mapping_v2.yaml"
REQUEST_SCHEMA_PATH = ROOT / "schemas/runtime-skill-v2.schema.json"


@pytest.fixture
def registry() -> RuntimeSkillRegistryV2:
    return load_registry_v2(V2_PATH)


def _track(track_id: str) -> PerceptionTrackV1:
    return PerceptionTrackV1(
        track_id=track_id,
        category="industrial_cylinder:red",
        confidence=0.9,
        pose_xyzquat=[0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0],
    )


def _recovery_observation(*track_ids: str) -> QRMObservationV1:
    return QRMObservationV1(
        episode_id="episode-runtime-v2",
        step_id=7,
        instruction="clear the blocker then grasp the task target",
        task_target_track_id="task-target",
        current_skill_stage="RECOVERY_DECISION",
        perception_tracks=[_track(track_id) for track_id in track_ids],
        failure_context=FailureContextV1(failure_type=FailureType.PATH_BLOCKED),
    )


def _decision(intent: CoarseIntentV2) -> SimpleNamespace:
    return SimpleNamespace(coarse=intent, recovery_skill=None, confidence=0.99)


def _pass_gate(
    action: str,
    parameters: dict[str, object],
) -> tuple[bool, str]:
    assert action.startswith("B0_") or action.startswith("PUBLIC_")
    assert parameters
    return True, "delegated check passed"


def _assert_b0_fallback(result: object) -> None:
    assert result.status == "INVALID"
    assert result.fallback_required is True
    assert result.fallback_action == "B0_SAFE_HOLD"
    assert result.execution_attribution == "NONE_B0_FALLBACK"


def test_v2_registry_diff_is_exactly_adr_authorized_delta() -> None:
    v1 = yaml.safe_load(V1_PATH.read_text())
    v2 = yaml.safe_load(V2_PATH.read_text())
    assert v1["schema_version"] == "RuntimeSkillRegistryV1"
    assert v2["schema_version"] == "RuntimeSkillRegistryV2"
    assert v1["model_output_schema"] == "CoarseIntentV1"
    assert v2["model_output_schema"] == "CoarseIntentV2"

    normalized = copy.deepcopy(v2)
    normalized["schema_version"] = v1["schema_version"]
    normalized["model_output_schema"] = v1["model_output_schema"]
    for skill in ("MOVE", "PLACE", "SAFE_PLACE_NON_TARGET"):
        assert normalized["skills"][skill]["parameter_enums"] == {
            "destination": list(DESTINATION_CELL_VALUES)
        }
        normalized["skills"][skill]["parameter_enums"] = {}
    assert normalized == v1


def test_registry_and_request_schema_round_trip(registry: RuntimeSkillRegistryV2) -> None:
    restored_registry = RuntimeSkillRegistryV2.model_validate_json(registry.model_dump_json())
    assert restored_registry == registry
    assert restored_registry.model_output_schema == "CoarseIntentV2"

    request = build_runtime_skill_request_v2(
        _recovery_observation("task-target", "blocker"),
        _decision(
            CoarseIntentV2(
                skill_type="MOVE",
                target_track_id="blocker",
                destination_cell="BIN_CELL_2",
            )
        ),
        registry,
    )
    restored_request = RuntimeSkillRequestV2.model_validate_json(request.model_dump_json())
    assert restored_request == request
    assert request.schema_version == "RuntimeSkillRequestV2"


def test_checked_in_runtime_request_schema_is_exact() -> None:
    checked_in = json.loads(REQUEST_SCHEMA_PATH.read_text())
    assert checked_in == RuntimeSkillRequestV2.model_json_schema()


def test_model_selects_blocker_and_records_each_parameter_provenance(
    registry: RuntimeSkillRegistryV2,
) -> None:
    observation = _recovery_observation("task-target", "blocker", "another")
    request = build_runtime_skill_request_v2(
        observation,
        _decision(
            CoarseIntentV2(
                skill_type="MOVE",
                target_track_id="blocker",
                destination_cell="BIN_CELL_3",
            )
        ),
        registry,
    )
    assert request.canonical_track_ids[:3] == ["another", "blocker", "task-target"]
    assert request.model_target_slot == 1
    assert request.target_track_provenance == ParameterProvenanceV2.MODEL

    seen: list[dict[str, object]] = []

    def gate(action: str, parameters: dict[str, object]) -> tuple[bool, str]:
        assert action == "B0_PUBLIC_GEOMETRY_MOVE"
        seen.append(parameters.copy())
        return True, "checked"

    result = validate_runtime_mapping_v2(
        request,
        registry,
        ik_check=gate,
        collision_check=gate,
        safety_check=gate,
        bin_cell_targets_provider=bin_cell_targets,
    )
    assert result.status == "VALID"
    assert result.fallback_required is False
    assert result.target_track_id == "blocker"
    assert result.target_track_id != observation.task_target_track_id
    assert result.parameters == {
        "destination": "BIN_CELL_3",
        "target_track_id": "blocker",
    }
    assert result.parameter_provenance == {
        "destination": ParameterProvenanceV2.MODEL,
        "target_track_id": ParameterProvenanceV2.MODEL,
        "destination_world_xyz_m": ParameterProvenanceV2.REGISTRY_DERIVED,
    }
    expected = list(bin_cell_targets()[3])
    assert result.execution_parameters["destination_world_xyz_m"] == expected
    assert len(seen) == 3
    assert all(parameters["destination_world_xyz_m"] == expected for parameters in seen)


def test_destination_resolution_has_frozen_explicit_protocol() -> None:
    result = resolve_destination_cell_v2(
        "BIN_CELL_5",
        bin_cell_targets_provider=bin_cell_targets,
    )
    assert result.world_xyz_m == pytest.approx(bin_cell_targets()[5])
    assert result.coordinate_frame == "world"
    assert result.units == "m"
    assert result.dimensions == 3
    assert result.normalization == "none"
    assert result.source == "generate_industrial_scenes.bin_cell_targets"
    assert result.source_sha256 == FROZEN_SCENE_GENERATOR_SHA256


def test_free_form_destination_is_invalid_and_uses_b0_fallback(
    registry: RuntimeSkillRegistryV2,
) -> None:
    request = build_runtime_skill_request_v2(
        _recovery_observation("blocker", "task-target"),
        _decision(CoarseIntentV2(skill_type="MOVE", target_track_id="blocker")),
        registry,
    ).model_copy(deep=True)
    request.parameters["destination"] = [0.1, 0.2, 0.3]
    request.parameter_provenance["destination"] = ParameterProvenanceV2.MODEL
    result = validate_runtime_mapping_v2(request, registry)
    _assert_b0_fallback(result)
    assert result.rejection_reason == MappingRejectionV2.INVALID_DESTINATION_CELL


def test_recovery_forbids_taskspec_fallback_even_for_a_fresh_task_track(
    registry: RuntimeSkillRegistryV2,
) -> None:
    request = build_runtime_skill_request_v2(
        _recovery_observation("task-target", "blocker"),
        _decision(CoarseIntentV2(skill_type="GRASP", grasp_family="top_down")),
        registry,
    )
    assert request.model_target_track_id is None
    assert request.task_target_track_id == "task-target"
    assert request.target_track_provenance == ParameterProvenanceV2.NONE
    result = validate_runtime_mapping_v2(request, registry)
    _assert_b0_fallback(result)
    assert result.rejection_reason == MappingRejectionV2.MISSING_MODEL_TARGET

    forged = request.model_copy(
        update={
            "model_target_track_id": "task-target",
            "model_target_slot": request.canonical_track_ids.index("task-target"),
            "target_track_provenance": ParameterProvenanceV2.TASK_SPEC_FALLBACK,
        }
    )
    forged_result = validate_runtime_mapping_v2(forged, registry)
    _assert_b0_fallback(forged_result)
    assert forged_result.rejection_reason == MappingRejectionV2.TASK_SPEC_FALLBACK_FORBIDDEN


def test_ninth_track_and_mismatched_pointer_are_invalid_b0_fallback(
    registry: RuntimeSkillRegistryV2,
) -> None:
    track_ids = [f"track-{index:02d}" for index in range(9)]
    observation = _recovery_observation(*reversed(track_ids))
    request = build_runtime_skill_request_v2(
        observation,
        _decision(CoarseIntentV2(skill_type="LIFT", target_track_id="track-08")),
        registry,
    )
    assert request.canonical_track_ids == track_ids[:8]
    assert request.model_target_slot is None
    stale = validate_runtime_mapping_v2(request, registry)
    _assert_b0_fallback(stale)
    assert stale.rejection_reason == MappingRejectionV2.STALE_TRACK

    pointer = build_runtime_skill_request_v2(
        observation,
        _decision(CoarseIntentV2(skill_type="LIFT", target_track_id="track-01")),
        registry,
    ).model_copy(update={"model_target_slot": 2})
    invalid_pointer = validate_runtime_mapping_v2(pointer, registry)
    _assert_b0_fallback(invalid_pointer)
    assert invalid_pointer.rejection_reason == MappingRejectionV2.INVALID_POINTER


def test_provider_source_hash_mismatch_and_exception_fail_closed(
    registry: RuntimeSkillRegistryV2,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def non_frozen_provider() -> tuple[tuple[float, float, float], ...]:
        return tuple((0.0, 0.0, 0.0) for _ in range(6))

    with pytest.raises(DestinationResolutionError, match="SHA-256"):
        resolve_destination_cell_v2(
            "BIN_CELL_0",
            bin_cell_targets_provider=non_frozen_provider,
        )

    request = build_runtime_skill_request_v2(
        _recovery_observation("blocker"),
        _decision(
            CoarseIntentV2(
                skill_type="PLACE",
                target_track_id="blocker",
                destination_cell="BIN_CELL_0",
            )
        ),
        registry,
    )
    mismatch = validate_runtime_mapping_v2(
        request,
        registry,
        bin_cell_targets_provider=non_frozen_provider,
    )
    _assert_b0_fallback(mismatch)
    assert mismatch.rejection_reason == MappingRejectionV2.DESTINATION_RESOLUTION_REJECTION

    monkeypatch.setattr(scene_generator, "BIN_CELL_LOCAL_X_M", None)
    with pytest.raises(DestinationResolutionError):
        resolve_destination_cell_v2(
            "BIN_CELL_0",
            bin_cell_targets_provider=scene_generator.bin_cell_targets,
        )
    provider_failure = validate_runtime_mapping_v2(
        request,
        registry,
        bin_cell_targets_provider=scene_generator.bin_cell_targets,
    )
    _assert_b0_fallback(provider_failure)
    assert provider_failure.rejection_reason == MappingRejectionV2.DESTINATION_RESOLUTION_REJECTION


@pytest.mark.parametrize(
    ("gate_name", "expected_reason"),
    [
        ("ik", MappingRejectionV2.IK_REJECTION),
        ("collision", MappingRejectionV2.COLLISION_REJECTION),
        ("safety", MappingRejectionV2.SAFETY_REJECTION),
    ],
)
def test_injected_gate_rejection_is_invalid_b0_fallback(
    gate_name: str,
    expected_reason: MappingRejectionV2,
    registry: RuntimeSkillRegistryV2,
) -> None:
    request = build_runtime_skill_request_v2(
        _recovery_observation("blocker"),
        _decision(CoarseIntentV2(skill_type="LIFT", target_track_id="blocker")),
        registry,
    )

    def reject_gate(
        _action: str,
        _parameters: dict[str, object],
    ) -> tuple[bool, str]:
        return False, "physical gate rejected"

    checks = {
        "ik_check": _pass_gate,
        "collision_check": _pass_gate,
        "safety_check": _pass_gate,
    }
    checks[f"{gate_name}_check"] = reject_gate
    result = validate_runtime_mapping_v2(request, registry, **checks)
    _assert_b0_fallback(result)
    assert result.rejection_reason == expected_reason


def test_gate_exception_fails_closed_and_omitted_gates_match_v1_semantics(
    registry: RuntimeSkillRegistryV2,
) -> None:
    request = build_runtime_skill_request_v2(
        _recovery_observation("blocker"),
        _decision(CoarseIntentV2(skill_type="LIFT", target_track_id="blocker")),
        registry,
    )

    def exploding_gate(
        _action: str,
        _parameters: dict[str, object],
    ) -> tuple[bool, str]:
        raise RuntimeError("gate unavailable")

    failed = validate_runtime_mapping_v2(request, registry, ik_check=exploding_gate)
    _assert_b0_fallback(failed)
    assert failed.rejection_reason == MappingRejectionV2.IK_REJECTION

    delegated_elsewhere = validate_runtime_mapping_v2(request, registry)
    assert delegated_elsewhere.status == "VALID"
    assert [entry["status"] for entry in delegated_elsewhere.gate_trace[-3:]] == [
        "NOT_RUN",
        "NOT_RUN",
        "NOT_RUN",
    ]
