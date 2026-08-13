from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s4_v4_batch07_pre_timeline_proprio_failure.py"
REPORT = ROOT / "reports/m2c-s4-v4-batch07-pre-timeline-proprio-failure.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("batch07_pre_timeline_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_batch07_report_is_pre_timeline_and_nonphysical() -> None:
    report = json.loads(REPORT.read_text())
    assert report["schema_version"] == "M2CS4V4Batch07PreTimelineProprioFailureAuditV1"
    assert report["status"] == "BLOCKED_PRE_TIMELINE_PROPRIOCEPTION_READ"
    assert len(report["attempts"]) == 1
    attempt = report["attempts"][0]
    assert attempt["stage_acceptance_passed"] is True
    assert attempt["stage_simulation_app_started"] is True
    assert attempt["probe_simulation_app_started"] is True
    assert attempt["probe_timeline_started"] is False
    assert attempt["physical_action_executed"] is False
    assert attempt["training_sample_eligible"] is False
    assert report["observed_counts"]["physical_actions"] == 0
    assert report["pure_model_success_episodes"] is None
    assert report["fix"]["failed_key_retried"] is False
    expected = v4_auth.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[
        "reports/m2c-s4-v4-batch07-pre-timeline-proprio-failure.json"
    ]
    assert expected == (
        "bf42d1b1d0703c7007255a20e52d0e661bf40461e4ec0ebc52ed053f0bf12fae",
        "M2CS4V4Batch07PreTimelineProprioFailureAuditV1",
        1,
    )


def test_build_report_rejects_empty_evidence(tmp_path: Path) -> None:
    audit = _load_module()
    with pytest.raises(audit.Batch07AuditError, match="evidence file is missing"):
        audit.build_report(evidence_root=tmp_path)
