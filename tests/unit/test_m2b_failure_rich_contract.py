from __future__ import annotations

import json
from pathlib import Path

import pytest

from xh_agent.data_engine.isaac.failure_rich import (
    PhysicalFailureEvidenceV2,
    ResidualCorrectionPairV2,
    failure_rich_group_key,
    validate_failure_recovery_episode,
)


ROOT = Path(__file__).parents[2]


def evidence(failure_type: str) -> dict:
    common = {
        "failure_type": failure_type,
        "injection_commanded": True,
        "public_observed_predicates": [],
    }
    if failure_type == "EMPTY_GRASP":
        return {
            **common,
            "close_command_issued": True,
            "bilateral_grasp_observed": False,
            "attachment_created": False,
            "target_lift_delta_m": 0.001,
            "public_observed_predicates": ["grasped=false", "lifted=false"],
        }
    if failure_type == "WRONG_OBJECT":
        return {
            **common,
            "close_command_issued": True,
            "bilateral_grasp_observed": True,
            "contacted_entity_id": "cylinder_02",
            "attached_entity_id": "cylinder_02",
            "task_target_entity_id": "cylinder_01",
            "task_target_track_id": "track-target",
            "carried_public_track_id": "track-carried",
            "public_observed_predicates": ["carried_target_match=false"],
        }
    return {
        **common,
        "release_command_issued": True,
        "attachment_remained_after_release": True,
        "carried_follow_delta_m": 0.02,
        "public_observed_predicates": ["released=false"],
    }


@pytest.mark.parametrize(
    "failure_type",
    ["EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"],
)
def test_mandatory_failure_evidence_requires_physical_state(
    failure_type: str,
) -> None:
    parsed = PhysicalFailureEvidenceV2.model_validate(evidence(failure_type))
    assert parsed.failure_type.value == failure_type


def test_empty_grasp_label_without_close_is_rejected() -> None:
    payload = evidence("EMPTY_GRASP")
    payload["close_command_issued"] = False
    with pytest.raises(ValueError, match="close command"):
        PhysicalFailureEvidenceV2.model_validate(payload)


def test_wrong_object_must_attach_actual_contact() -> None:
    payload = evidence("WRONG_OBJECT")
    payload["attached_entity_id"] = "cylinder_03"
    with pytest.raises(ValueError, match="contacted entity"):
        PhysicalFailureEvidenceV2.model_validate(payload)


def test_release_failure_requires_follow_after_release() -> None:
    payload = evidence("RELEASE_FAILURE")
    payload["carried_follow_delta_m"] = 0.0
    with pytest.raises(ValueError, match="follow evidence"):
        PhysicalFailureEvidenceV2.model_validate(payload)


def test_residual_pair_is_reconstructible_and_non_degenerate() -> None:
    nominal = [0.01, -0.01, 0.002] + [0.0] * 7
    corrected = [0.0] * 10
    residual = [b - a for a, b in zip(nominal, corrected)]
    pair = ResidualCorrectionPairV2(
        dimension_names=["dx", "dy", "dz", "r0", "r1", "r2", "r3", "r4", "r5", "gripper"],
        perturbed_nominal=nominal,
        corrected_action=corrected,
        residual_target=residual,
        perturbation_xyz_m=nominal[:3],
        correction_physically_successful=True,
    )
    assert pair.residual_target[:3] == [-0.01, 0.01, -0.002]


def test_residual_pair_rejects_unreconstructible_target() -> None:
    with pytest.raises(ValueError, match="corrected - nominal"):
        ResidualCorrectionPairV2(
            dimension_names=["dx", "dy", "dz", "r0", "r1", "r2", "r3", "r4", "r5", "gripper"],
            perturbed_nominal=[0.01, 0.01, 0.002] + [0.0] * 7,
            corrected_action=[0.0] * 10,
            residual_target=[0.0] * 10,
            perturbation_xyz_m=[0.01, 0.01, 0.002],
            correction_physically_successful=True,
        )


def test_failure_context_and_recovery_must_match_physics() -> None:
    sequence = ["REOBSERVE", "REGRASP"]
    episode = {
        "observation_before": {"object_tracks": [{"track_id": "track-target"}]},
        "observation_after": {"object_tracks": [{"track_id": "track-target"}]},
        "recovery_observations": [],
        "task_spec": {"target_track_id": "track-target"},
        "failure_context": {
            "failure_type": "EMPTY_GRASP",
            "last_skill": "GRASP",
            "previous_skill": "GRASP",
            "expected_predicates": ["grasped", "lifted"],
            "observed_predicates": ["grasped=false", "lifted=false"],
            "predicate_residual": ["missing:grasped", "missing:lifted"],
            "retry_count": 1,
            "attempted_recoveries": sequence,
            "last_recovery_result": "SUCCESS",
        },
        "recovery_execution": {
            "sequence": sequence,
            "steps_executed": sequence,
            "public_final_predicates": ["grasped=true", "lifted=true"],
            "successful": True,
            "retry_count": 1,
        },
        "simulator_supervision": {
            "physical_failure_evidence": evidence("EMPTY_GRASP")
        },
    }
    assert validate_failure_recovery_episode(episode) == []


def test_entity_truth_in_public_observation_is_rejected() -> None:
    sequence = ["REOBSERVE", "REGRASP"]
    episode = {
        "observation_before": {"prim_path": "/World/M1B/cylinder_01"},
        "observation_after": {},
        "recovery_observations": [],
        "task_spec": {"target_track_id": "track-target"},
        "failure_context": {
            "failure_type": "EMPTY_GRASP",
            "last_skill": "GRASP",
            "previous_skill": "GRASP",
            "expected_predicates": ["grasped"],
            "observed_predicates": [],
            "predicate_residual": ["missing:grasped"],
            "retry_count": 1,
            "attempted_recoveries": sequence,
            "last_recovery_result": "SUCCESS",
        },
        "recovery_execution": {
            "sequence": sequence,
            "steps_executed": sequence,
            "public_final_predicates": ["grasped=true"],
            "successful": True,
            "retry_count": 1,
        },
        "simulator_supervision": {
            "physical_failure_evidence": evidence("EMPTY_GRASP")
        },
    }
    assert any("forbidden key" in item for item in validate_failure_recovery_episode(episode))


def test_failure_split_group_includes_injection_seed() -> None:
    assert failure_rich_group_key(4001, "EMPTY_GRASP", 7) == (
        "scene-4001:failure-EMPTY_GRASP:injection-7"
    )


def test_checked_in_failure_rich_schemas_match_models() -> None:
    for filename, model in (
        ("physical-failure-evidence-v2.schema.json", PhysicalFailureEvidenceV2),
        ("residual-correction-pair-v2.schema.json", ResidualCorrectionPairV2),
    ):
        observed = json.loads((ROOT / "schemas" / filename).read_text())
        assert observed == model.model_json_schema()
