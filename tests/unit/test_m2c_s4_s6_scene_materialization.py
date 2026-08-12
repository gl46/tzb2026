from __future__ import annotations

import json
from pathlib import Path

import pytest

from m2c.materialize_s4_s6_scenes import materialize, records_for_role


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
