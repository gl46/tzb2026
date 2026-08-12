from __future__ import annotations

import ast
import json
from pathlib import Path

from m2c.derive_model_owned_chain_probe import (
    build_collection_manifests,
    derive_probe_bytes,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
)


ROOT = Path(__file__).parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")


def test_derived_probe_has_exact_eight_public_physical_steps() -> None:
    derived = derive_probe_bytes(UPSTREAM.read_bytes()).decode()
    ast.parse(derived)
    for index, skill in enumerate(
        (
            "GRASP",
            "LIFT",
            "MOVE",
            "PLACE",
            "RELEASE",
            "REOBSERVE",
            "REASSOCIATE_TARGET",
            "REGRASP",
        )
    ):
        assert f'step_index={index}, skill="{skill}"' in derived
    assert derived.count("m2c_chain_steps.append(_m2c_step(") == 8
    assert "M2C_MODEL_CHAIN_MOVE" in derived
    assert "M2C_MODEL_CHAIN_PLACE" in derived
    assert "M2C_MODEL_CHAIN_GRASP_PREGRASP" in derived
    assert derived.count("M2C_MODEL_CHAIN_GRASP_CONTACT_DESCENT") == 2
    assert '"execution_measurements": measurements' in derived
    assert "del measurements" not in derived
    assert '"capture_receipt_sha256": m2c_reobserve_observation' in derived
    assert '"reassociated_public_track_id": reassociated_id' in derived
    assert "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION" in derived
    assert "formal_q_b_evaluation" not in derived


def test_projected_collection_manifests_are_strict_and_disjoint() -> None:
    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    evaluation = json.loads((ROOT / "configs/m2c_s6_evaluation_keys.json").read_text())
    collection, s6 = build_collection_manifests(
        training,
        evaluation,
        runtime_registry_sha256="a" * 64,
    )
    parsed_collection = FrozenPathBlockedCollectionManifestV2.model_validate(collection)
    parsed_s6 = FrozenS6ExclusionManifestV2.model_validate(s6)
    assert len(parsed_collection.keys) == 39
    assert len(parsed_s6.keys) == 30
    assert not (
        {record.matched_key for record in parsed_collection.keys}
        & {record.matched_key for record in parsed_s6.keys}
    )
    assert not (
        {record.scene_seed for record in parsed_collection.keys}
        & {record.scene_seed for record in parsed_s6.keys}
    )
