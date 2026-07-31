from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from m2b.build_prospective_runtime_decisions import canonical_sha256
from m2b.run_prospective_preflight_batch import (
    expected_first_runtime_action,
    model_run_key,
    preflight_command,
    scene_root_from_evidence,
    selected_action_is_physically_supported,
    target_entities,
    validate_batch_inputs,
    validated_source_hashes,
    verify_bytes_sha256,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    RuntimeSkillRequestV1,
    load_registry,
    validate_runtime_mapping,
)


ROOT = Path(__file__).parents[2]
REGISTRY_PATH = ROOT / "configs/qrm_runtime_mapping.yaml"
REGISTRY = load_registry(REGISTRY_PATH)


def test_preflight_routes_only_declared_first_recovery_actions() -> None:
    assert selected_action_is_physically_supported(
        REGISTRY, "EMPTY_GRASP", "HOLD_AND_CAPTURE_PUBLIC_RGBD"
    )
    assert selected_action_is_physically_supported(
        REGISTRY, "WRONG_OBJECT", "B0_SAFE_PLACE_NON_TARGET"
    )
    assert selected_action_is_physically_supported(
        REGISTRY, "RELEASE_FAILURE", "B0_RELEASE_RETRY"
    )
    assert not selected_action_is_physically_supported(
        REGISTRY, "WRONG_OBJECT", "B0_PUBLIC_GEOMETRY_REGRASP"
    )
    assert (
        expected_first_runtime_action(REGISTRY, "WRONG_OBJECT")
        == REGISTRY.skills["SAFE_PLACE_NON_TARGET"].runtime_action
    )


def test_preflight_reuses_hash_bound_injection_entities_and_scene() -> None:
    payload = {
        "attached_entity": "cylinder_04",
        "m2b_wrong_object_injection": {
            "attached_entity_id": "cylinder_10",
            "task_target_entity_id": "cylinder_07",
        },
    }
    assert target_entities(payload, "WRONG_OBJECT") == (
        "cylinder_10",
        "cylinder_07",
    )
    root = scene_root_from_evidence(
        "/data/worker1/scene-4029/failures/wrong/attempt/evidence.json",
        4029,
    )
    assert str(root) == "/data/worker1/scene-4029"


def test_preflight_command_is_single_attempt_zero_residual() -> None:
    command = preflight_command(
        project_root="/project",
        source_root="/source",
        stage="/data/scene/stage.usdc",
        scene_seed=4029,
        failure_type="WRONG_OBJECT",
        gpu=1,
        output_root="/output",
        injection_entity="cylinder_10",
        task_target_entity="cylinder_07",
        container_prefix="m2b-preflight",
    )
    assert command[command.index("--max-attempts") + 1] == "1"
    assert command[command.index("--failures") + 1] == "WRONG_OBJECT"
    assert (
        command[command.index("--public-regrasp-offset-camera-xyz-m") + 1]
        == "0,0,0"
    )


def valid_batch_fixture() -> tuple[list[dict], dict[str, dict]]:
    episode_id = "m2b-empty-0001"
    failure_type = "EMPTY_GRASP"
    request = {
        "schema_version": "RuntimeSkillRequestV1",
        "model_output_schema": "CoarseIntentV1",
        "model_class_id": "coarse.recovery.REOBSERVE",
        "skill": "REOBSERVE",
        "task_target_track_id": "track-1",
        "model_target_track_id": None,
        "available_track_ids": ["track-1"],
        "parameters": {},
        "coordinate_frame": "policy_rgbd_optical",
        "units": "none",
        "current_phase": "RECOVERY",
        "confidence": 0.9,
        "residual_values": None,
    }
    mapping = validate_runtime_mapping(
        RuntimeSkillRequestV1.model_validate(request),
        REGISTRY,
    ).model_dump(mode="json")
    model_input = {
        "observation": {
            "episode_id": episode_id,
            "failure_context": {"failure_type": failure_type},
        },
        "rgb_sha256": "a" * 64,
    }
    model_output = {"coarse": {"skill_type": "REOBSERVE"}}
    record = {
        "sample_id": f"{episode_id}:coarse-recovery-0",
        "episode_id": episode_id,
        "failure_type": failure_type,
        "model_input": model_input,
        "model_output": model_output,
        "request": request,
        "mapping": mapping,
        "registry_sha256": hashlib.sha256(
            REGISTRY_PATH.read_bytes()
        ).hexdigest(),
        "model_checkpoint_sha256": "b" * 64,
        "model_input_sha256": canonical_sha256(model_input),
        "model_output_sha256": canonical_sha256(model_output),
        "request_sha256": canonical_sha256(request),
        "mapping_result_sha256": canonical_sha256(mapping),
    }
    episode = {
        "episode_id": episode_id,
        "failure_context": {"failure_type": failure_type},
    }
    return [record], {episode_id: episode}


def test_batch_validates_all_hashes_and_episode_binding_before_runs() -> None:
    records, episodes = valid_batch_fixture()
    validate_batch_inputs(
        records,
        episodes,
        registry=REGISTRY,
        registry_sha256=records[0]["registry_sha256"],
    )
    tampered = json.loads(json.dumps(records))
    tampered[0]["mapping"]["runtime_action"] = "B0_SAFE_HOLD"
    with pytest.raises(ValueError, match="mapping_result_sha256 mismatch"):
        validate_batch_inputs(
            tampered,
            episodes,
            registry=REGISTRY,
            registry_sha256=records[0]["registry_sha256"],
        )


def test_batch_rejects_dataset_failure_mismatch_before_runs() -> None:
    records, episodes = valid_batch_fixture()
    episodes[records[0]["episode_id"]]["failure_context"][
        "failure_type"
    ] = "WRONG_OBJECT"
    with pytest.raises(ValueError, match="dataset failure type mismatch"):
        validate_batch_inputs(
            records,
            episodes,
            registry=REGISTRY,
            registry_sha256=records[0]["registry_sha256"],
        )


def test_physical_source_hashes_are_required_and_verified() -> None:
    raw = b"physical-evidence"
    digest = hashlib.sha256(raw).hexdigest()
    assert validated_source_hashes(
        {"source_hashes": {"scene.sdf": digest}}
    ) == {"scene.sdf": digest}
    verify_bytes_sha256(raw, digest, "scene")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_bytes_sha256(raw, "0" * 64, "scene")


def test_preflight_run_key_separates_adapter_checkpoints() -> None:
    first = {"sample_id": "sample-1", "model_checkpoint_sha256": "a" * 64}
    second = {"sample_id": "sample-1", "model_checkpoint_sha256": "b" * 64}
    assert model_run_key(first) != model_run_key(second)
