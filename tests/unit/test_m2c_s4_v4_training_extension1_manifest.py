from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from m2c.build_s4_v4_training_extension1_manifest import build_manifest, manifest_bytes
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2CS4V4TrainingKeyExtensionManifestV1,
    load_v4_training_manifest,
    v4_manifest_file_sha256,
    v4_manifest_key,
)


ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "configs/m2c_s4_v4_training_keys.json"
EXTENSION = ROOT / "configs/m2c_s4_v4_training_keys_extension1.json"


def _identities(payload: dict[str, object]) -> tuple[set[int], set[int], set[str]]:
    records = payload["training_keys"]
    assert isinstance(records, list)
    return (
        {int(item["scene_seed"]) for item in records},
        {int(item["failure_seed"]) for item in records},
        {str(item["matched_key"]) for item in records},
    )


def test_extension_builder_reproduces_exact_frozen_bytes() -> None:
    built = build_manifest()
    assert manifest_bytes(built) == EXTENSION.read_bytes()
    manifest = load_v4_training_manifest(EXTENSION)
    assert isinstance(manifest, M2CS4V4TrainingKeyExtensionManifestV1)
    assert len(manifest.training_keys) == 36
    assert v4_manifest_file_sha256(manifest) == (
        "9fcc971f5bdf0787692b6d2de9be81885fe164e4b78b34fac214d6467c64e164"
    )
    assert v4_manifest_key(manifest) == "M2C_S4_V4_FROZEN_TRAIN_KEYS_EXTENSION1"


def test_extension_is_identity_disjoint_and_outcome_blind() -> None:
    original = json.loads(ORIGINAL.read_bytes())
    extension = json.loads(EXTENSION.read_bytes())
    original_scenes, original_failures, original_keys = _identities(original)
    scenes, failures, keys = _identities(extension)
    assert len(scenes) == len(failures) == len(keys) == 36
    assert not (scenes & original_scenes)
    assert not (failures & original_failures)
    assert not (keys & original_keys)
    assert extension["selection_uses_rollout_outcomes"] is False
    assert extension["any_selected_key_collection_observed_before_freeze"] is False
    assert extension["collection_executed"] is False
    assert extension["training_executed"] is False
    assert extension["teacher_used"] is False
    assert extension["privileged_truth_policy_input"] is False


def test_extension_first_sdf_balanced_batch_is_fixed() -> None:
    manifest = load_v4_training_manifest(EXTENSION)
    first_per_sdf: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for item in manifest.training_keys:
        if item.sdf_sha256 in seen:
            continue
        seen.add(item.sdf_sha256)
        first_per_sdf.append((item.scene_seed, item.failure_seed, item.matched_key))
        if len(first_per_sdf) == 3:
            break
    assert first_per_sdf == [
        (
            22001,
            220017,
            "m2c-s4-v4-train-0b06ce4cf5f2573c6406f88441951fe421d149909f515ce0dc1ddd47165467df",
        ),
        (
            22002,
            220027,
            "m2c-s4-v4-train-f9907adeb10cb0e056a6d0b17f72e09e76e59d0a178c8257c5ad208be088e4cc",
        ),
        (
            22007,
            220077,
            "m2c-s4-v4-train-44f97a37597aad15dd7ec9fdcc531a7b9a732ebcaf72146a6c1083c11e833911",
        ),
    ]


def test_extension_loader_rejects_self_consistent_unfrozen_manifest(tmp_path: Path) -> None:
    payload = copy.deepcopy(json.loads(EXTENSION.read_bytes()))
    payload["written_date_asia_shanghai"] = "2099-01-01"
    payload_without_hash = {
        key: value for key, value in payload.items() if key != "manifest_sha256"
    }
    from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import canonical_sha256

    payload["manifest_sha256"] = canonical_sha256(payload_without_hash)
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(payload, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="not frozen"):
        load_v4_training_manifest(forged)
