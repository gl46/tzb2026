from __future__ import annotations

import pytest

from m2b.build_coarse_training_v2 import _source_relative, coarse_sample
from m2b.summarize_coarse_ablation import summarize
from m2b.validate_coarse_training_v2 import validate
from xh_agent.policy.qrm_lite.coarse_inference import (
    prediction_from_probabilities,
)
from xh_agent.policy.qrm_lite.coarse_prompt import coarse_prompt


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
        "last_carried_track_id": "carried",
    }
    return {
        "episode_id": "m2b-test-wrong-1",
        "injection_seed": 17,
        "split": "train",
        "split_group": "scene-4025",
        "dataset_version": "isaac-industrial-v2-failure-rich",
        "observation_before": {
            "tracks": [
                {
                    "track_id": "carried",
                    "category": "industrial_cylinder",
                    "visual_color": "yellow",
                    "position_world_m": [1.5, 2.5, 3.5],
                    "confidence": 0.9,
                }
            ]
        },
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
    assert sample.coarse_intent.target_track_id == "carried"
    assert sample.continuous_action_target_available is False
    assert "nominal_action_chunk" not in payload
    assert "target_action_chunk" not in payload
    assert sample.observation.camera_extrinsics_base_T_cam == []
    assert sample.observation.perception_tracks[0].pose_xyzquat[:3] == [
        1.0,
        2.0,
        3.0,
    ]
    retained = sample.observation.perception_tracks[-1]
    assert retained.track_id == "carried"
    assert retained.confidence == 0.0
    assert retained.pose_xyzquat is None
    assert sample.provenance["base_to_camera_extrinsics"] == (
        "ABSENT_NOT_GUESSED"
    )


def test_coarse_asset_uri_cannot_escape_evidence() -> None:
    with pytest.raises(ValueError, match="escapes evidence root"):
        _source_relative("dataset://../secret")


def test_formal_training_gate_rejects_tiny_but_valid_dataset(tmp_path) -> None:
    sample = coarse_sample(
        _episode(),
        rgb_uri="dataset://episodes/m2b-test/rgb/after.png",
        depth_uri="dataset://episodes/m2b-test/depth/after.npy",
    )
    dataset = tmp_path / "coarse.jsonl"
    dataset.write_text(sample.model_dump_json() + "\n")
    report = validate(dataset)
    assert report["status"] == "NOT_READY"
    assert report["samples"] == 1
    assert report["limited_failure_coverage"] is False
    assert report["findings"] == []


def test_ablation_summary_requires_matched_two_seed_improvement() -> None:
    def training_report(seed: int, fc: str, accuracy: float, macro_f1: float):
        return {
            "status": "PASS",
            "failure_context": fc,
            "seed": seed,
            "n_train": 120,
            "n_eval": 30,
            "eval_split": "val",
            "labels": [
                "REOBSERVE",
                "RETRY_RELEASE",
                "SAFE_PLACE_NON_TARGET",
            ],
            "eval_accuracy": accuracy,
            "eval_metrics": {"macro_f1": macro_f1},
        }

    off = [
        training_report(1, "off", 0.5, 0.4),
        training_report(2, "off", 0.55, 0.45),
    ]
    on = [
        training_report(1, "on", 0.6, 0.5),
        training_report(2, "on", 0.65, 0.55),
    ]
    report = summarize(off, on, dataset_sha256="d" * 64)
    assert report["failure_context_supported_offline"] is True
    assert report["formal_ablation"] is True
    assert len(report["pairs"]) == 2


def test_shared_prompt_masks_fc_and_prediction_maps_to_recovery() -> None:
    sample = coarse_sample(
        _episode(),
        rgb_uri="dataset://episodes/m2b-test/rgb/after.png",
        depth_uri="dataset://episodes/m2b-test/depth/after.npy",
    )
    no_fc = coarse_prompt(
        sample.observation,
        use_failure_context=False,
        allowed_skills=["REOBSERVE", "SAFE_PLACE_NON_TARGET"],
    )
    with_fc = coarse_prompt(
        sample.observation,
        use_failure_context=True,
        allowed_skills=["REOBSERVE", "SAFE_PLACE_NON_TARGET"],
    )
    assert '"failure_type": "NONE"' in no_fc
    assert '"failure_type": "WRONG_OBJECT"' in with_fc
    prediction = prediction_from_probabilities(
        sample.observation,
        {"REOBSERVE": 0.2, "SAFE_PLACE_NON_TARGET": 0.8},
        use_failure_context=True,
    )
    assert prediction.coarse.skill_type == "SAFE_PLACE_NON_TARGET"
    assert prediction.coarse.target_track_id == "carried"
    assert prediction.recovery_skill == "SAFE_PLACE_NON_TARGET"
    assert prediction.confidence == 0.8
