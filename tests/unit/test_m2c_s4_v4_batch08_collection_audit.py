from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s4_v4_batch08_collection.py"
REPORT = ROOT / "reports/m2c-s4-v4-batch08-collection.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("batch08_collection_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_batch08_report_separates_permissions_from_schema_gate() -> None:
    report = json.loads(REPORT.read_text())
    assert report["schema_version"] == "M2CS4V4Batch08CollectionAuditV1"
    assert report["status"] == "BLOCKED_RAW_DETECTION_CAPACITY_SCHEMA_DECISION_REQUIRED"
    assert [item["classification"] for item in report["attempts"]] == [
        "ISAAC_STAGE_PROCESS_EXIT_139",
        "ISAAC_STAGE_PROCESS_EXIT_139",
        "RAW_CHAIN_COMPLETE_HOST_SCHEMA_CAPACITY_REJECTED",
    ]
    physical = report["attempts"][2]
    assert physical["raw_capture_detection_counts"] == [7, 13, 11, 7, 8, 9, 10, 10]
    assert physical["physical_skill_receipts"] == 8
    assert physical["physical_action_executed"] is True
    assert physical["collision_or_safety_violations"] == 0
    assert physical["final_controller_gate"] == "REJECTED"
    assert physical["final_execution_status"] == "CONTACT_GATE_REJECTED"
    assert physical["training_sample_eligible"] is False
    assert physical["training_sample_packaged"] is False
    assert report["root_cause"]["permission_failure"] is False
    assert report["root_cause"]["schema_max_raw_detections"] == 8
    assert report["root_cause"]["final_candidate_count_bound_changed"] is False
    assert report["observed_counts"]["training_samples_eligible"] == 0
    assert report["observed_counts"]["training_samples_packaged"] == 0
    assert report["pure_model_success_episodes"] is None
    expected = v4_auth.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[
        "reports/m2c-s4-v4-batch08-collection.json"
    ]
    assert expected == (
        "226761a056c6c3a127784019147e49b3e6e301f72d4b9711e222cd7c939a2894",
        "M2CS4V4Batch08CollectionAuditV1",
        3,
    )


def test_build_report_rejects_empty_evidence(tmp_path: Path) -> None:
    audit = _load_module()
    with pytest.raises(FileNotFoundError):
        audit.build_report(evidence_root=tmp_path)


def test_historical_contract_replay_reads_preregistered_git_blob() -> None:
    audit = _load_module()
    contract = audit._read_git_blob(
        project_root=ROOT,
        commit=audit.PREREG_COMMIT,
        relative_path=audit.COLLECTION_CONTRACT_PATH,
    )
    assert hashlib.sha256(contract).hexdigest() == audit.COLLECTION_CONTRACT_SHA256
    assert contract != (ROOT / audit.COLLECTION_CONTRACT_PATH).read_bytes()
