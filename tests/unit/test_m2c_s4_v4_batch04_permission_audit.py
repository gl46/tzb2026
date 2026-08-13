from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s4_v4_batch04_permission_failure.py"
REPORT = ROOT / "reports/m2c-s4-v4-batch04-permission-failure.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("batch04_permission_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_permission_failure_classifier_is_exact() -> None:
    audit = _load_module()
    exact = (audit.PERMISSION_FAILURE + "\n").encode()
    assert audit._permission_failure_count(exact) == 1
    assert audit._permission_failure_count(b"PermissionError\n") == 0


def test_claim_semantic_hash_rejects_tamper() -> None:
    audit = _load_module()
    core = {
        "schema_version": "M2CS4V4CollectionConsumptionReceiptV1",
        "ledger_sequence": 0,
    }
    claim = {**core, "receipt_sha256": audit.canonical_sha256(core)}
    assert audit._claim_core_is_valid(claim)
    tampered = copy.deepcopy(claim)
    tampered["ledger_sequence"] = 1
    assert not audit._claim_core_is_valid(tampered)


def test_committed_report_is_fail_closed_and_not_physical_evidence() -> None:
    report = json.loads(REPORT.read_text())
    assert report["schema_version"] == "M2CS4V4Batch04InfrastructureFailureAuditV1"
    assert report["status"] == "BLOCKED_PRE_KIT_STAGE_OUTPUT_PERMISSION_FAILURE"
    assert len(report["attempts"]) == 3
    assert len({item["identity"]["matched_key"] for item in report["attempts"]}) == 3
    assert report["observed_counts"] == {
        "consumed_unique_train_keys": 3,
        "stage_builder_invocations": 3,
        "stage_permission_failures": 3,
        "probe_launches": 0,
        "physical_actions": 0,
        "training_samples_eligible": 0,
        "training_samples_packaged": 0,
    }
    assert report["permission_fix"]["batch04_retried"] is False
    assert report["permission_fix"]["replacement_authorized"] is False
    assert report["teacher_used"] is False
    assert report["privileged_truth_policy_input"] is False
    assert report["pure_model_success_episodes"] is None
    assert report["audit_implementation"]["path"] == SCRIPT.relative_to(ROOT).as_posix()
    assert len(report["audit_implementation"]["sha256"]) == 64
    assert v4_auth.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[
        "reports/m2c-s4-v4-batch04-permission-failure.json"
    ] == (
        "a80cb5891a88bba124725f7588e658eb15282ba38e455bc9befb65ceb39e751a",
        "M2CS4V4Batch04InfrastructureFailureAuditV1",
        3,
    )


def test_build_report_rejects_missing_evidence(tmp_path: Path) -> None:
    audit = _load_module()
    (tmp_path / "ledger").mkdir()
    (tmp_path / "raw").mkdir()
    with pytest.raises(audit.Batch04AuditError, match="evidence file is missing"):
        audit.build_report(evidence_root=tmp_path)
