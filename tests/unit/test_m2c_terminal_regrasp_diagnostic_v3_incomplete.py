from __future__ import annotations

import json
from pathlib import Path

from m2c.audit_terminal_regrasp_diagnostic_v3_incomplete import (
    EXPECTED_PROBE_ERROR,
)
from m2c.derive_terminal_regrasp_diagnostic_probe_v3 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v3,
)


UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
ROOT = Path(__file__).resolve().parents[2]


def test_v3_incomplete_cause_precedes_terminal_primitive() -> None:
    source = derive_terminal_regrasp_diagnostic_probe_bytes_v3(UPSTREAM.read_bytes()).decode()
    assert source.index(f'raise RuntimeError("{EXPECTED_PROBE_ERROR}")') < source.index(
        "direct_result = _execute_m2b_public_regrasp("
    )
    assert source.index("SimulationManager.setup_simulation(") < source.index(
        f'raise RuntimeError("{EXPECTED_PROBE_ERROR}")'
    )


def test_published_v3_incomplete_report_withholds_ablation_decision() -> None:
    report = json.loads(
        (ROOT / "reports/m2c-s4-terminal-regrasp-diagnostic-v3-incomplete.json").read_bytes()
    )
    assert report["status"] == "BLOCKED_INCOMPLETE_INHERITED_V4_CHAIN_PRECONDITION"
    assert report["valid_terminal_measurements"] == 0
    assert report["decision"] is None
    assert report["failed_run"]["controller_initialized"] is True
    assert report["failed_run"]["terminal_primitive_called"] is False
    assert report["further_v3_execution_authorized"] is False
