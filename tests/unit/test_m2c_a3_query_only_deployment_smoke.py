from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from m2c.run_a3_query_only_deployment_smoke import (
    DeploymentSmokeFailure,
    EXPECTED_BUILDER_IMAGE_ID,
    EXPECTED_RUNTIME_IMAGE_ID,
    HOME_OPEN_STATE,
    SCHEMA_VERSION,
    write_create_only,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts/m2c/run_a3_query_only_deployment_smoke.py"


def test_query_only_smoke_contract_has_no_isaac_scene_or_execution_import() -> None:
    source = SCRIPT.read_text()
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }.union(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom))

    assert not any(name == "isaacsim" or name.startswith("isaacsim.") for name in imported)
    assert not any(name == "omni" or name.startswith("omni.") for name in imported)
    assert "SimulationApp" not in source
    assert "simulation_app.update" not in source
    assert "set_joint" not in source
    assert "set_dof" not in source
    assert len(HOME_OPEN_STATE) == 9
    assert EXPECTED_RUNTIME_IMAGE_ID.startswith("sha256:")
    assert EXPECTED_BUILDER_IMAGE_ID.startswith("sha256:")
    assert SCHEMA_VERSION == "M2CA3QueryOnlyDeploymentSmokeV1"


def test_smoke_receipt_is_create_only_canonical_payload(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    payload = b'{"schema_version":"M2CA3QueryOnlyDeploymentSmokeV1"}\n'
    write_create_only(output, payload)

    assert output.read_bytes() == payload
    assert json.loads(output.read_bytes())["schema_version"] == SCHEMA_VERSION
    with pytest.raises(FileExistsError):
        write_create_only(output, payload)


def test_smoke_output_parent_must_preexist(tmp_path: Path) -> None:
    with pytest.raises(DeploymentSmokeFailure, match="parent"):
        write_create_only(tmp_path / "absent/receipt.json", b"{}\n")
