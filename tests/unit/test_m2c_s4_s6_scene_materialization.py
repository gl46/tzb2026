from __future__ import annotations

import json
from pathlib import Path

import pytest

from m2c.materialize_s4_s6_scenes import (
    materialize,
    records_for_role,
    records_for_versioned_train,
)


ROOT = Path(__file__).parents[2]


def test_smoke_scene_sources_materialize_with_frozen_hashes(tmp_path: Path) -> None:
    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    evaluation = json.loads((ROOT / "configs/m2c_s6_evaluation_keys.json").read_text())
    output = tmp_path / "smoke"
    result = materialize(
        records_for_role(training, evaluation, "SMOKE"),
        output_root=output,
    )
    assert result["status"] == "MATERIALIZED_OFFLINE_NO_ISAAC_EXECUTION"
    assert [record["scene_seed"] for record in result["records"]] == [
        15054,
        15075,
        15076,
    ]
    assert all(Path(record["sdf"]).is_file() for record in result["records"])
    assert all(Path(record["supervision"]).is_file() for record in result["records"])
    assert Path(result["controlled_urdf"]).is_file()
    assert (
        result["controlled_urdf_sha256"]
        == "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
    )
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        materialize(
            records_for_role(training, evaluation, "SMOKE"),
            output_root=output,
        )


def test_v4_extension_scene_sources_materialize_offline_but_do_not_authorize_collection(
    tmp_path: Path,
) -> None:
    training = json.loads((ROOT / "configs/m2c_s4_v4_training_keys_extension1.json").read_text())
    records = records_for_versioned_train(training, revision="V4", limit=3)
    assert [record["scene_seed"] for record in records] == [22001, 22002, 22007]

    result = materialize(
        records,
        output_root=tmp_path / "extension1",
        collection_authorization_status="NOT_AUTHORIZED_FOR_COLLECTION",
    )
    assert result["status"] == "MATERIALIZED_OFFLINE_NO_ISAAC_EXECUTION"
    assert result["collection_authorization_status"] == "NOT_AUTHORIZED_FOR_COLLECTION"
    assert len(result["records"]) == 3


def test_versioned_materializer_rejects_self_consistent_unknown_v4_manifest() -> None:
    training = json.loads((ROOT / "configs/m2c_s4_v4_training_keys_extension1.json").read_text())
    training["schema_version"] = "M2CS4V4TrainingKeyExtensionManifestV2"
    with pytest.raises(ValueError, match="requires its frozen TRAIN manifest"):
        records_for_versioned_train(training, revision="V4", limit=1)
