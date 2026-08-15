from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from m2c import build_terminal_regrasp_diagnostic_prereg_v3 as builder
from m2c.derive_terminal_regrasp_diagnostic_probe_v2 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v2,
)
from m2c.derive_terminal_regrasp_diagnostic_probe_v3 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v3,
)
from m2c.run_terminal_regrasp_diagnostic_v3 import _probe_command_v3
from m2c.s4_scene_family import materialize_scene
from xh_agent.data.isaac_m1b import load_m1b_isaac_generated_scene
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    DIAGNOSTIC_CONDITIONS,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    materialize_diagnostic_scene_v2,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    CAMPAIGN_ID,
    DIRECT_PUBLIC_RGBD_CONTRACT,
    ISAAC_IMAGE_ID,
    M2CTerminalDiagnosticAuthorizationBindingV3,
    M2CTerminalRegraspDiagnosticRawV3,
)


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
TEMPLATE = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"


def _function_text(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name
    )
    result = ast.get_source_segment(source, node)
    assert result is not None
    return result


def test_v3_changes_only_diagnostic_measurement_setup_and_binding() -> None:
    upstream = UPSTREAM.read_bytes()
    v2 = derive_terminal_regrasp_diagnostic_probe_bytes_v2(upstream).decode()
    v3 = derive_terminal_regrasp_diagnostic_probe_bytes_v3(upstream).decode()
    compile(v3, "terminal-regrasp-diagnostic-v3.py", "exec")
    for function in (
        "_capture_m2b_public_rgbd",
        "_execute_m2b_public_regrasp",
        "_m2c_terminal_collision_or_safety_violations",
    ):
        assert _function_text(v2, function) == _function_text(v3, function)
    v2_setup = _function_text(v2, "_setup_m2b_public_rgbd")
    v3_setup = _function_text(v3, "_setup_m2b_public_rgbd")
    assert "diagnostic_direct_measurement" not in v2_setup
    assert "diagnostic_direct_measurement" in v3_setup
    assert 'ARGS.m2c_chain_role == "DIAGNOSTIC"' in v3_setup
    assert '"C1_NO_BLOCKER"' in v3_setup
    assert '"C2_RETAINED_BLOCKER"' in v3_setup
    assert '"C3_FULL_V4"' not in v3_setup
    assert "bind_diagnostic_claim_to_raw_session_v3" in v3
    assert '"schema_version": "M2CTerminalRegraspDiagnosticRawV3"' in v3
    assert (
        v3.index("require_pre_freeze(")
        < v3.index("bind_diagnostic_claim_to_raw_session(")
        < v3.index("from isaacsim import SimulationApp")
    )


def test_v3_still_materializes_six_object_scenes(tmp_path: Path) -> None:
    full = materialize_scene(TEMPLATE.read_text(), 280112, (-0.115, 0.13))
    assert full is not None
    for index, condition in enumerate(DIAGNOSTIC_CONDITIONS, start=1):
        sdf, supervision = materialize_diagnostic_scene_v2(
            full_v4_sdf_bytes=full[0],
            full_v4_supervision_bytes=full[1],
            scene_seed=2_801_000 + index,
            source_base_seed=280112,
            condition=condition,
        )
        root = ET.fromstring(sdf)
        world = root.find("world")
        assert world is not None
        assert [
            model.get("name")
            for model in world.findall("model")
            if model.get("name", "").startswith("cylinder_")
        ] == [f"cylinder_{number:02d}" for number in range(1, 7)]
        sdf_path = tmp_path / f"{condition}.sdf"
        supervision_path = tmp_path / f"{condition}.json"
        sdf_path.write_bytes(sdf)
        supervision_path.write_bytes(supervision)
        assert load_m1b_isaac_generated_scene(sdf_path, supervision_path).cylinder_count == 6


def test_v3_seed_selection_is_fresh_fixed_and_paired() -> None:
    external = {
        "scene_seed": {1},
        "failure_seed": {2},
        "matched_key": {"external"},
    }
    runs = builder._select_runs(
        template=TEMPLATE.read_text(),
        external=external,
    )
    assert len(runs) == 36
    assert [record["ordinal"] for record in runs] == list(range(36))
    assert [record["condition"] for record in runs] == [
        condition for _ in range(12) for condition in DIAGNOSTIC_CONDITIONS
    ]
    assert len({record["scene_seed"] for record in runs}) == 36
    assert len({record["failure_seed"] for record in runs}) == 36
    assert len({record["matched_key"] for record in runs}) == 36


def test_v3_probe_command_enables_direct_measurement_only_for_c1_c2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = [
        "docker",
        "run",
        "--m2c-docker-command-sha256",
        "0" * 64,
    ]
    monkeypatch.setattr(
        "m2c.run_terminal_regrasp_diagnostic_v3._probe_command",
        lambda **_kwargs: list(base),
    )
    for condition, expected in (
        ("C1_NO_BLOCKER", True),
        ("C2_RETAINED_BLOCKER", True),
        ("C3_FULL_V4", False),
    ):
        command = _probe_command_v3(run=SimpleNamespace(condition=condition))
        assert ("--m2c-direct-terminal-public-rgbd" in command) is expected
        digest = command[command.index("--m2c-docker-command-sha256") + 1]
        assert len(digest) == 64 and digest != "0" * 64


def _authorization(*, condition: str, direct: bool) -> dict[str, object]:
    return {
        "schema_version": "M2CTerminalDiagnosticAuthorizationBindingV3",
        "campaign_id": CAMPAIGN_ID,
        "condition": condition,
        "run_id": "run",
        "matched_key": "key",
        "ordinal": 0,
        "scene_seed": 1,
        "failure_seed": 2,
        "probe_mode": (
            "FULL_V4_PREAMBLE_TERMINAL" if condition == "C3_FULL_V4" else "DIRECT_TERMINAL"
        ),
        "expected_local_blockers": [],
        "terminal_target_blocker_surface_gap_m": None,
        "direct_public_rgbd_enabled": direct,
        "public_rgbd_setup_contract": DIRECT_PUBLIC_RGBD_CONTRACT,
        "consumption_receipt_sha256": "1" * 64,
        "prereg_sha256": "2" * 64,
        "source_sdf_sha256": "3" * 64,
        "source_supervision_sha256": "4" * 64,
        "source_urdf_sha256": ("6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"),
        "upstream_v4_probe_sha256": (
            "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
        ),
        "derived_probe_sha256": "5" * 64,
        "container_image_id": ISAAC_IMAGE_ID,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def test_v3_authorization_rejects_direct_mode_on_c3() -> None:
    with pytest.raises(ValueError, match="direct public RGB-D mode"):
        M2CTerminalDiagnosticAuthorizationBindingV3.model_validate(
            _authorization(condition="C3_FULL_V4", direct=True)
        )


def test_v3_raw_cannot_claim_success_without_execution() -> None:
    auth = _authorization(condition="C1_NO_BLOCKER", direct=True)
    raw = {
        "schema_version": "M2CTerminalRegraspDiagnosticRawV3",
        "authorization": auth,
        "run_id": "run",
        "matched_key": "key",
        "scene_seed": 1,
        "failure_seed": 2,
        "condition": "C1_NO_BLOCKER",
        "public_rgbd_setup_contract": DIRECT_PUBLIC_RGBD_CONTRACT,
        "terminal_measurement_valid": True,
        "terminal_execution_status": "LIFTED",
        "pregrasp_ik_passed": True,
        "contact_gate_passed": True,
        "selected_free_gap_yaw_rad": 0.0,
        "terminal_target_blocker_surface_gap_m": None,
        "public_predicates": ["grasped=true", "lifted=true"],
        "terminal_success": True,
        "physical_action_executed": True,
        "collision_or_safety_violations": 0,
        "public_capture_evidence": [],
        "terminal_regrasp_execution": None,
        "actuation_probe_source_sha256": "5" * 64,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    with pytest.raises(ValueError, match="terminal-valid"):
        M2CTerminalRegraspDiagnosticRawV3.model_validate(raw)


def test_v3_builder_seed_origin_is_outside_v1_v2_ranges() -> None:
    assert builder.CANDIDATE_BASE_SEED_START == 280100
    assert hashlib.sha256(str(builder.CANDIDATE_BASE_SEED_START).encode()).hexdigest()
