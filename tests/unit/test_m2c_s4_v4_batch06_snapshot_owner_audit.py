from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s4_v4_batch06_snapshot_owner_failure.py"
REPORT = ROOT / "reports/m2c-s4-v4-batch06-snapshot-owner-failure.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("batch06_owner_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_batch06_report_is_prekit_and_nonphysical() -> None:
    report = json.loads(REPORT.read_text())
    assert report["schema_version"] == "M2CS4V4Batch06SnapshotOwnerFailureAuditV1"
    assert report["status"] == "BLOCKED_PRE_KIT_SOURCE_SNAPSHOT_OWNER_FALSE_REJECTION"
    assert len(report["attempts"]) == 1
    attempt = report["attempts"][0]
    assert attempt["stage_acceptance_passed"] is True
    assert attempt["stage_simulation_app_started"] is True
    assert attempt["probe_process_invoked"] is True
    assert attempt["probe_simulation_app_started"] is False
    assert attempt["physical_action_executed"] is False
    assert attempt["training_sample_eligible"] is False
    assert report["observed_counts"]["physical_actions"] == 0
    assert report["pure_model_success_episodes"] is None
    assert report["fix"]["failed_key_retried"] is False
    assert v4_auth.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[
        "reports/m2c-s4-v4-batch06-snapshot-owner-failure.json"
    ] == (
        "415364cb1478f812da42c9aa4c81f47690348ae53ab9d067d0950c3a19ac9d68",
        "M2CS4V4Batch06SnapshotOwnerFailureAuditV1",
        1,
    )


def test_build_report_rejects_empty_evidence(tmp_path: Path) -> None:
    audit = _load_module()
    with pytest.raises(audit.Batch06AuditError, match="evidence file is missing"):
        audit.build_report(evidence_root=tmp_path)
