from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from m2c import replay_s4_v4_scene19083_raw_capacity as replay


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = Path("/Users/gl/tzb-m2c-evidence/m2c-s4-v4-batch08-complete")
REPORT_JSON = ROOT / "reports/m2c-s4-v4-scene19083-offline-raw-capacity-replay.json"
REPORT_MD = ROOT / "reports/m2c-s4-v4-scene19083-offline-raw-capacity-replay.md"


def _raw_probe() -> dict[str, object]:
    return json.loads((EVIDENCE_ROOT / replay.RAW_PROBE_RELATIVE).read_text())


def test_committed_report_preserves_failure_and_k8() -> None:
    report = json.loads(REPORT_JSON.read_text())
    assert report["status"] == ("PASS_OFFLINE_REPLAY_EXCLUDED_UNCHANGED_PHYSICAL_FAILURE")
    assert report["authorization"] == {
        "adr_commit": replay.ADR_COMMIT,
        "adr_path": replay.ADR_PATH,
        "adr_sha256": replay.ADR_SHA256,
        "max_raw_public_detections": 32,
        "numeric_provenance": "4_X_FROZEN_INDUSTRIAL_CYLINDER_SCENE_MAX_8_ENTITIES",
        "offline_replay_only": True,
        "outcome_reinterpretation_authorized": False,
        "physical_retry_or_replacement_authorized": False,
        "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
        "selected_option": "A",
    }
    assert report["schema_upgrade"]["raw_detection_counts"] == [
        7,
        13,
        11,
        7,
        8,
        9,
        10,
        10,
    ]
    assert all(
        item["truncated_or_filtered"] is False
        for item in report["schema_upgrade"]["transformations"]
    )
    assert report["host_replay"]["passed"] is True
    assert report["host_replay"]["final_candidate_k"] == 8
    assert max(report["host_replay"]["candidate_counts"]) == 8
    assert report["unchanged_outcome"]["source_final_task_success"] is False
    assert report["unchanged_outcome"]["replayed_final_task_success"] is False
    assert report["unchanged_outcome"]["training_sample_eligible"] is False
    assert report["unchanged_outcome"]["persisted_training_sample_count"] == 0
    assert report["training_executed"] is False
    assert report["formal_q_b_evaluation_executed"] is False
    assert report["teacher_used"] is False
    assert report["privileged_truth_policy_input"] is False


def test_report_binds_its_offline_only_implementation() -> None:
    report = json.loads(REPORT_JSON.read_text())
    script = ROOT / report["implementation"]["report_script_path"]
    assert (
        hashlib.sha256(script.read_bytes()).hexdigest()
        == report["implementation"]["report_script_sha256"]
    )
    source = script.read_text()
    assert "SimulationApp" not in source
    assert "offline-only" in source
    assert 'physical_retry_or_replacement_authorized": False' in source


@pytest.mark.skipif(not EVIDENCE_ROOT.is_dir(), reason="immutable scene 19083 evidence absent")
def test_capture_upgrade_rejects_receipt_tamper_and_over_capacity() -> None:
    probe = _raw_probe()
    chain = probe["m2c_path_blocked_physical_chain"]
    captures = probe["m2c_v4_raw_association_captures"]
    upgraded_chain, upgraded, transformations = replay._upgrade_captures(chain, captures)
    assert len(upgraded_chain["steps"]) == len(upgraded) == len(transformations) == 8
    assert [len(item["detections"]) for item in upgraded] == replay.EXPECTED_DETECTION_COUNTS

    bad_chain = copy.deepcopy(chain)
    bad_chain["steps"][0]["observation"]["capture_receipt_sha256"] = "0" * 64
    with pytest.raises(replay.Scene19083ReplayError, match="original V1 capture"):
        replay._upgrade_captures(bad_chain, captures)

    bad_captures = copy.deepcopy(captures)
    bad_captures[0]["detections"] = [
        copy.deepcopy(bad_captures[0]["detections"][0]) for _ in range(33)
    ]
    bad_chain = copy.deepcopy(chain)
    bad_chain["steps"][0]["observation"]["capture_receipt_sha256"] = replay.canonical_sha256(
        bad_captures[0]
    )
    with pytest.raises(replay.Scene19083ReplayError, match="ADR-0025 schema"):
        replay._upgrade_captures(bad_chain, bad_captures)


@pytest.mark.skipif(not EVIDENCE_ROOT.is_dir(), reason="immutable scene 19083 evidence absent")
def test_committed_report_replays_exact_immutable_evidence() -> None:
    regenerated = replay.build_report(evidence_root=EVIDENCE_ROOT, project_root=ROOT)
    assert replay.report_bytes(regenerated) == REPORT_JSON.read_bytes()
    assert replay.markdown_bytes(regenerated) == REPORT_MD.read_bytes()
