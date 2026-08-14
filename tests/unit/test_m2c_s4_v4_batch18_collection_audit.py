from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s4_v4_batch18_collection.py"
REPORT = ROOT / "reports/m2c-s4-v4-batch18-collection.json"
EVIDENCE = Path("/Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch18-complete")


def _load_module():
    spec = importlib.util.spec_from_file_location("batch18_collection_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_batch18_report_preserves_final_zero_eligible_outcome() -> None:
    report = json.loads(REPORT.read_bytes())
    assert report["schema_version"] == "M2CS4V4Batch18CollectionAuditV1"
    assert report["status"] == "BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH18"
    assert len(report["attempts"]) == 1
    attempt = report["attempts"][0]
    assert attempt["identity"]["scene_seed"] == 19307
    assert attempt["classification"] == ("RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED")
    assert attempt["raw_capture_detection_counts"] == [7, 7, 6, 8, 9, 12, 13, 12]
    assert attempt["raw_detection_capacity"] == 32
    assert attempt["host_replay_passed"] is True
    assert attempt["offline_dataset_status"] == "EMPTY"
    assert attempt["offline_dataset_sample_count"] == 0
    assert attempt["offline_dataset_exclusion_reasons"] == [
        "FINAL_TASK_NOT_SUCCESSFUL",
        "STEP_7:CONTROLLER_GATE_NOT_PASSING",
    ]
    assert report["observed_counts"] == {
        "collision_or_safety_violations": 0,
        "consumed_unique_train_keys": 1,
        "host_replay_passes": 1,
        "physical_skill_receipts": 8,
        "probe_process_invocations": 1,
        "raw_physical_chains": 1,
        "stage_acceptance_passes": 1,
        "terminal_contact_gate_rejections": 0,
        "terminal_pregrasp_ik_gate_rejections": 1,
        "training_samples_eligible": 0,
        "training_samples_packaged": 0,
    }
    assert report["evidence_inventory"] == {
        "canonical_path_sha256_map_digest": (
            "5e0fa4ede6374d0103a7bb00b465d20890515cc4fdf6eec64ee0b68ecb88fd28"
        ),
        "regular_file_count": 56,
        "total_file_bytes": 52954878,
    }
    assert report["training_executed"] is False
    assert report["model_rollout_executed"] is False
    assert report["formal_q_b_evaluation_executed"] is False
    assert report["pure_model_success_episodes"] is None


def test_build_report_rejects_empty_evidence(tmp_path: Path) -> None:
    audit = _load_module()
    with pytest.raises((audit.Batch18AuditError, FileNotFoundError)):
        audit.build_report(evidence_root=tmp_path)


@pytest.mark.skipif(not EVIDENCE.is_dir(), reason="immutable Batch-18 evidence is absent")
def test_local_immutable_batch18_evidence_replays_exact_report() -> None:
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
