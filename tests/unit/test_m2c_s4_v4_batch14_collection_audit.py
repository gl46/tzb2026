from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s4_v4_batch14_collection.py"
REPORT = ROOT / "reports/m2c-s4-v4-batch14-collection.json"
EVIDENCE = Path("/Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch14-complete")


def _load_module():
    spec = importlib.util.spec_from_file_location("batch14_collection_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_batch14_report_preserves_zero_eligible_outcome() -> None:
    report = json.loads(REPORT.read_bytes())
    assert report["schema_version"] == "M2CS4V4Batch14CollectionAuditV1"
    assert report["status"] == "BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH14"
    assert [item["classification"] for item in report["attempts"]] == [
        "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED",
        "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED",
        "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED",
    ]
    assert [item["raw_capture_detection_counts"] for item in report["attempts"]] == [
        [7, 7, 9, 8, 9, 12, 12, 14],
        [7, 6, 7, 7, 8, 11, 11, 11],
        [7, 13, 10, 7, 8, 9, 10, 10],
    ]
    assert all(item["raw_detection_capacity"] == 32 for item in report["attempts"])
    assert all(item["host_replay_passed"] is True for item in report["attempts"])
    assert all(item["offline_dataset_status"] == "EMPTY" for item in report["attempts"])
    assert all(item["offline_dataset_sample_count"] == 0 for item in report["attempts"])
    assert report["attempts"][2]["offline_dataset_exclusion_reasons"] == [
        "FINAL_TASK_NOT_SUCCESSFUL",
        "STEP_1:PUBLIC_TARGET_OUTSIDE_V4_K8",
        "STEP_7:CONTROLLER_GATE_NOT_PASSING",
    ]
    assert report["observed_counts"] == {
        "collision_or_safety_violations": 0,
        "consumed_unique_train_keys": 3,
        "host_replay_passes": 3,
        "physical_skill_receipts": 24,
        "probe_process_invocations": 3,
        "raw_physical_chains": 3,
        "stage_acceptance_passes": 3,
        "terminal_contact_gate_rejections": 2,
        "terminal_pregrasp_ik_gate_rejections": 1,
        "training_samples_eligible": 0,
        "training_samples_packaged": 0,
    }
    assert report["evidence_inventory"]["regular_file_count"] == 168
    assert report["evidence_inventory"]["canonical_path_sha256_map_digest"] == (
        "56db4b1dfff9bafbc8e34611f12a1f39fc95a1a696dd4ea7be940fe2fca573a0"
    )
    assert report["training_executed"] is False
    assert report["model_rollout_executed"] is False
    assert report["formal_q_b_evaluation_executed"] is False
    assert report["pure_model_success_episodes"] is None


def test_build_report_rejects_empty_evidence(tmp_path: Path) -> None:
    audit = _load_module()
    with pytest.raises((audit.Batch14AuditError, FileNotFoundError)):
        audit.build_report(evidence_root=tmp_path)


@pytest.mark.skipif(not EVIDENCE.is_dir(), reason="immutable Batch-14 evidence is absent")
def test_local_immutable_batch14_evidence_replays_exact_report() -> None:
    audit = _load_module()
    actual = audit.report_bytes(audit.build_report(evidence_root=EVIDENCE))
    assert actual == REPORT.read_bytes()


def test_preregistration_bytes_equal_the_introduction_commit_blob() -> None:
    audit = _load_module()
    committed = audit._git_blob(
        project_root=ROOT,
        commit=audit.PREREG_COMMIT,
        relative_path=audit.PREREG_RELATIVE,
    )
    assert committed == (ROOT / audit.PREREG_RELATIVE).read_bytes()
