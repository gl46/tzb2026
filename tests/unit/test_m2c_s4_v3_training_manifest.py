from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/m2c/build_s4_v3_training_manifest.py"
SPEC = importlib.util.spec_from_file_location("m2c_s4_v3_manifest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def _identities(payload: object) -> tuple[set[int], set[int], set[str]]:
    scenes: set[int] = set()
    failures: set[int] = set()
    keys: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("scene_seed"), int):
                scenes.add(value["scene_seed"])
            if isinstance(value.get("failure_seed"), int):
                failures.add(value["failure_seed"])
            if isinstance(value.get("matched_key"), str):
                keys.add(value["matched_key"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return scenes, failures, keys


def test_manifest_is_36_new_train_only_v3_keys_and_is_deterministic() -> None:
    first = BUILDER.build_manifest()
    second = BUILDER.build_manifest()
    assert first == second
    assert first["schema_version"] == "M2CS4V3TrainingKeyManifestV1"
    assert first["status"] == "FROZEN_TRAIN_ONLY_BEFORE_ANY_V3_COLLECTION"
    assert len(first["training_keys"]) == 36
    assert first["physical_prerequisite_smoke_keys"] == []
    assert first["smoke_collection_authorized"] is False
    assert first["evaluation_collection_authorized"] is False
    assert first["train_only"] is True
    assert first["candidate_contract_revision"] == "PublicTrackCandidateV3"
    assert first["checkpoint_architecture_revision"] == "M2C_Q012_V3"
    assert first["declared_target_attribute"] == "yellow"
    assert first["recapture_policy"] == "NONE"
    assert first["collection_executed"] is False
    assert first["training_executed"] is False
    assert first["teacher_used"] is False
    assert first["privileged_truth_policy_input"] is False
    for record in first["training_keys"]:
        assert 16_000 <= record["scene_seed"] < 19_000
        assert record["split"] == "train"
        assert record["role"] == "TRAIN"
        assert record["previously_executed"] is False
        assert record["outcome_observed_during_selection"] is False
        assert record["candidate_contract_revision"] == "PublicTrackCandidateV3"
        assert record["checkpoint_architecture_revision"] == "M2C_Q012_V3"
        assert record["declared_target_attribute"] == "yellow"


def test_scene_failure_and_matched_key_are_disjoint_from_every_frozen_scope() -> None:
    manifest = BUILDER.build_manifest()
    new_scenes, new_failures, new_keys = _identities(manifest["training_keys"])
    assert len(new_scenes) == len(new_failures) == len(new_keys) == 36
    for relative in (
        "configs/m2c_s4_training_keys.json",
        "configs/m2c_headroom_domain_v4.json",
        "configs/m2c_s6_evaluation_keys.json",
    ):
        frozen = json.loads((ROOT / relative).read_text())
        scenes, failures, keys = _identities(frozen)
        assert not new_scenes & scenes
        assert not new_failures & failures
        assert not new_keys & keys


def test_category_audit_and_all_frozen_sources_are_hash_bound() -> None:
    manifest = BUILDER.build_manifest()
    bindings = manifest["source_bindings"]
    assert bindings["reports/m2c-s3-public-category-vocabulary-audit.json"] == (
        "7946d610b677981ac56b223067cd63fdd10ccde140ae6dccc13ffb4688b90bfa"
    )
    assert bindings["docs/decisions/ADR-0021-m2c-public-semantic-candidate-contract.md"]
    assert bindings["configs/m2c_s4_training_keys.json"]
    assert bindings["configs/m2c_headroom_domain_v4.json"]
    assert bindings["configs/m2c_s6_evaluation_keys.json"]
    assert manifest["exclusion_contract"]["identity_dimensions"] == [
        "scene_seed",
        "failure_seed",
        "matched_key",
    ]


def test_builder_fails_closed_on_source_hash_or_nonpassing_category_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        BUILDER.EXPECTED_SOURCE_HASHES,
        "configs/m2c_s4_training_keys.json",
        "0" * 64,
    )
    with pytest.raises(ValueError, match="source hash mismatch"):
        BUILDER.build_manifest()


def test_output_is_create_only(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    manifest = BUILDER.build_manifest()
    BUILDER.write_create_only(output, manifest)
    with pytest.raises(FileExistsError):
        BUILDER.write_create_only(output, manifest)
