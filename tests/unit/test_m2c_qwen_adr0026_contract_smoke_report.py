from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/m2c-s4-qwen-adr0026-decision-contract-smoke.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_adr0026_qwen_contract_report_binds_current_bytes_and_stays_blocked() -> None:
    report = json.loads(REPORT.read_text())
    assert report["status"] == (
        "PASS_DECISION_DATA_AND_TRAINING_CONTRACT_BLOCKED_BEFORE_REAL_TRAINING"
    )
    for binding in [
        report["accepted_adr"],
        report["dataset"]["packaging_report"],
        report["dataset"]["dataset_manifest"],
        report["dataset"]["v3_excluded_shard"],
        report["dataset"]["v4_shard"],
        report["dataset"]["s6_evaluation_manifest"],
        *report["dataset"]["v4_training_manifests"],
        *report["implementation"],
    ]:
        assert _sha256(ROOT / binding["path"]) == binding["sha256"]
    smoke = report["contract_smoke"]
    assert (smoke["rows_checked"], smoke["episodes_checked"]) == (273, 39)
    assert smoke["pointer_rows_supervised"] + smoke["pointer_rows_masked"] == 273
    assert smoke["optimizer_steps"] == 0
    assert smoke["checkpoint_written"] is False
    assert smoke["training_executed"] is False
    assert smoke["teacher_used"] is False
    assert smoke["privileged_truth_policy_input"] is False
    assert report["blockers"] == [
        "ADR0026_DECISION_BUNDLE_RUNTIME_NOT_IN_FORMAL_DEPLOYMENT_CLOSURE",
        "FORMAL_PHYSICAL_RUNNER_BINDING_UNSET",
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING_UNSET",
    ]
    assert all(value is None for value in report["phase2_binding_state"].values())
