from __future__ import annotations

import pytest

from m2b.build_coarse_training_v2 import _source_relative, coarse_sample


def _episode() -> dict:
    context = {
        "schema_version": "FailureContextV1",
        "last_skill": "GRASP",
        "previous_skill": "GRASP",
        "expected_predicates": ["carried_target_match=true"],
        "observed_predicates": ["carried_target_match=false"],
        "predicate_residual": ["target mismatch"],
        "failure_type": "WRONG_OBJECT",
        "retry_count": 1,
        "attempted_recoveries": [
            "SAFE_PLACE_NON_TARGET",
            "REASSOCIATE_TARGET",
            "REGRASP",
        ],
        "last_recovery_result": "SUCCESS",
        "last_action_summary": "public physical probe",
        "last_target_track_id": "target",
    }
    return {
        "episode_id": "m2b-test-wrong-1",
        "injection_seed": 17,
        "split": "train",
        "dataset_version": "isaac-industrial-v2-failure-rich",
        "observation_after": {
            "label": "after_physical_lift",
            "timestamp_ns": 42,
            "tracks": [
                {
                    "track_id": "target",
                    "category": "industrial_cylinder",
                    "visual_color": "red",
                    "position_world_m": [2.0, 3.0, 4.0],
                    "confidence": 0.9,
                }
            ],
        },
        "public_camera": {
            "camera_frame": "m2b_policy_rgbd_optical",
            "camera_intrinsics": [1.0] * 9,
            "camera_to_world_optical": [
                1.0,
                0.0,
                0.0,
                1.0,
                0.0,
                1.0,
                0.0,
                1.0,
                0.0,
                0.0,
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ],
        },
        "task_spec": {
            "instruction": "Recover the public target safely.",
            "target_track_id": "target",
        },
        "failure_context": context,
        "recovery_sequence": [
            "SAFE_PLACE_NON_TARGET",
            "REASSOCIATE_TARGET",
            "REGRASP",
        ],
        "simulator_supervision": {"training_and_evaluation_only": True},
        "provenance": {"evidence_sha256": "a" * 64},
    }


def test_coarse_v2_has_no_fabricated_continuous_action_target() -> None:
    sample = coarse_sample(
        _episode(),
        rgb_uri="dataset://episodes/m2b-test/rgb/after.png",
        depth_uri="dataset://episodes/m2b-test/depth/after.npy",
    )
    payload = sample.model_dump(mode="json")
    assert sample.coarse_intent.skill_type == "SAFE_PLACE_NON_TARGET"
    assert sample.continuous_action_target_available is False
    assert "nominal_action_chunk" not in payload
    assert "target_action_chunk" not in payload
    assert sample.observation.camera_extrinsics_base_T_cam == []
    assert sample.observation.perception_tracks[0].pose_xyzquat[:3] == [
        1.0,
        2.0,
        3.0,
    ]
    assert sample.provenance["base_to_camera_extrinsics"] == (
        "ABSENT_NOT_GUESSED"
    )


def test_coarse_asset_uri_cannot_escape_evidence() -> None:
    with pytest.raises(ValueError, match="escapes evidence root"):
        _source_relative("dataset://../secret")
