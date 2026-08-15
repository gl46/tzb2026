from __future__ import annotations

import ast
from pathlib import Path

import pytest

from m2c import build_terminal_regrasp_diagnostic_prereg_v4 as builder
from m2c.derive_terminal_regrasp_diagnostic_probe_v3 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v3,
)
from m2c.derive_terminal_regrasp_diagnostic_probe_v4 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v4,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    DIAGNOSTIC_CONDITIONS,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    DIRECT_PUBLIC_RGBD_CONTRACT,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v4 import (
    CAMPAIGN_ID,
    ISAAC_IMAGE_ID,
    M2CTerminalDiagnosticAuthorizationBindingV4,
    M2CTerminalRegraspDiagnosticRawV4,
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


def test_v4_direct_branch_precedes_every_inherited_chain_action() -> None:
    upstream = UPSTREAM.read_bytes()
    v3 = derive_terminal_regrasp_diagnostic_probe_bytes_v3(upstream).decode()
    v4 = derive_terminal_regrasp_diagnostic_probe_bytes_v4(upstream).decode()
    compile(v4, "terminal-regrasp-diagnostic-v4.py", "exec")
    for function in (
        "_setup_m2b_public_rgbd",
        "_capture_m2b_public_rgbd",
        "_execute_m2b_public_regrasp",
        "_m2c_terminal_collision_or_safety_violations",
    ):
        assert _function_text(v3, function) == _function_text(v4, function)
    main = v4.index("def main() -> int:")
    direct = v4.index("direct_result = _execute_m2b_public_regrasp(", main)
    inherited_guard = v4.index("M2C chain requires public blocker and task-target tracks", main)
    first_chain_capture = v4.index("m2c_grasp_tracks, m2c_grasp_observation", main)
    assert direct < inherited_guard < first_chain_capture
    assert v4.count("direct_result = _execute_m2b_public_regrasp(") == 1
    assert "bind_diagnostic_claim_to_raw_session_v4" in v4
    assert '"schema_version": "M2CTerminalRegraspDiagnosticRawV4"' in v4


def test_v4_fresh_selection_is_paired_and_disjoint_from_prior_sentinel() -> None:
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
    assert [record["condition"] for record in runs] == [
        condition for _ in range(12) for condition in DIAGNOSTIC_CONDITIONS
    ]
    assert len({record["scene_seed"] for record in runs}) == 36
    assert len({record["failure_seed"] for record in runs}) == 36
    assert len({record["matched_key"] for record in runs}) == 36


def _authorization() -> dict[str, object]:
    return {
        "schema_version": "M2CTerminalDiagnosticAuthorizationBindingV4",
        "campaign_id": CAMPAIGN_ID,
        "condition": "C1_NO_BLOCKER",
        "run_id": "run",
        "matched_key": "key",
        "ordinal": 0,
        "scene_seed": 1,
        "failure_seed": 2,
        "probe_mode": "DIRECT_TERMINAL",
        "expected_local_blockers": [],
        "terminal_target_blocker_surface_gap_m": None,
        "direct_public_rgbd_enabled": True,
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


def test_v4_authorization_campaign_is_not_v3() -> None:
    model = M2CTerminalDiagnosticAuthorizationBindingV4.model_validate(_authorization())
    assert model.campaign_id == CAMPAIGN_ID
    altered = _authorization()
    altered["campaign_id"] = "m2c-s4-terminal-regrasp-diagnostic-v3"
    with pytest.raises(ValueError):
        M2CTerminalDiagnosticAuthorizationBindingV4.model_validate(altered)


def test_v4_raw_rejects_missing_terminal_execution() -> None:
    raw = {
        "schema_version": "M2CTerminalRegraspDiagnosticRawV4",
        "authorization": _authorization(),
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
        M2CTerminalRegraspDiagnosticRawV4.model_validate(raw)
