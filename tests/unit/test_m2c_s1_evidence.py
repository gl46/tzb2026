from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from m2c.export_s1_evidence import (
    capture_remote_path,
    select_successful_wrong_object_fc,
    validated_remote_path,
)


def episode(episode_id: str, *, success: bool = True) -> dict[str, object]:
    digest = "a" * 64
    return {
        "episode_id": episode_id,
        "matched_key": "m2b-match-key",
        "method": "QRM_COARSE_FC",
        "scene_seed": 4017,
        "failure_type": "WRONG_OBJECT",
        "initial_success": False,
        "final_success": success,
        "recovery_attempted": True,
        "recovery_success": success,
        "retries": 0,
        "task_time_s": 1.0,
        "decisions": [
            {
                "decision_id": f"{episode_id}-decision",
                "step_id": 0,
                "selected_skill": "SAFE_PLACE_NON_TARGET",
                "previous_failed_skill": "GRASP",
                "model_decision": True,
                "mapping_status": "VALID",
                "ik_gate": "PASS",
                "collision_gate": "PASS",
                "safety_gate": "PASS",
                "execution_source": "MODEL_SELECTED_B0_SKILL",
                "executed_skill": "SAFE_PLACE_NON_TARGET",
                "registry_sha256": digest,
                "model_checkpoint_sha256": digest,
                "model_input_sha256": digest,
                "model_output_sha256": digest,
                "mapping_result_sha256": digest,
                "gate_evidence_sha256": {
                    "ik": digest,
                    "collision": digest,
                    "safety": digest,
                },
            }
        ],
    }


def test_selection_is_success_only_and_deterministic() -> None:
    selected = select_successful_wrong_object_fc(
        [episode("z"), episode("failed", success=False), episode("a")]
    )
    assert selected.episode_id == "a"
    with pytest.raises(ValueError, match="no successful"):
        select_successful_wrong_object_fc([episode("failed", success=False)])


def test_remote_evidence_is_confined_to_frozen_m2b_root() -> None:
    valid = validated_remote_path(
        "/var/tmp/xh-data/isaac-industrial/m2b/matched-closed-loop-v1/gpu0/evidence.json"
    )
    assert valid.name == "evidence.json"
    with pytest.raises(ValueError, match="escapes frozen M2B root"):
        validated_remote_path("/var/tmp/xh-data/isaac-industrial/m2c/output.json")


def test_capture_uri_cannot_escape_evidence_directory() -> None:
    evidence = PurePosixPath(
        "/var/tmp/xh-data/isaac-industrial/m2b/matched-closed-loop-v1/gpu0/attempt/actuation-probe.json"
    )
    capture = capture_remote_path(
        evidence,
        "dataset://m2b_public_rgbd/rgb/frame.png",
    )
    assert capture == evidence.parent / "m2b_public_rgbd/rgb/frame.png"
    with pytest.raises(ValueError, match="escapes evidence directory"):
        capture_remote_path(evidence, "dataset://../secret")
