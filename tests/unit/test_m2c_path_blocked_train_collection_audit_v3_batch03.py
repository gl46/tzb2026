"""Focused replay and tamper tests for the frozen V3 TRAIN batch-03 audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_path_blocked_train_collection_v3_batch03.py"
EVIDENCE = Path("/Users/gl/tzb-m2c-evidence/m2c-s4-v3-batch03-complete-uKktog")
SPEC = importlib.util.spec_from_file_location("m2c_train_collection_audit_v3_batch03", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _evidence_root() -> Path:
    if not EVIDENCE.is_dir():
        pytest.skip(f"frozen external V3 batch-03 evidence is unavailable: {EVIDENCE}")
    return EVIDENCE


def _attempt_root(attempt_id: str) -> Path:
    jobs = list((_evidence_root() / attempt_id).glob("train/*/collection-job-v3.json"))
    assert len(jobs) == 1
    return jobs[0].parent


def _record(attempt_root: Path) -> dict[str, object]:
    job = json.loads((attempt_root / "collection-job-v3.json").read_text(encoding="utf-8"))
    manifest = AUDIT.cumulative.load_v3_training_manifest(ROOT / AUDIT.cumulative.MANIFEST_PATH)
    return next(
        item.model_dump(mode="json")
        for item in manifest.training_keys
        if item.matched_key == job["matched_key"]
    )


def _copy_raw_fixture(tmp_path: Path, attempt_id: str) -> tuple[Path, Path, dict[str, object]]:
    source = _attempt_root(attempt_id)
    probe = tmp_path / "probe"
    probe.mkdir()
    shutil.copy2(source / "probe/actuation-probe.json", probe / "actuation-probe.json")
    shutil.copytree(source / "probe/m2b_public_rgbd", probe / "m2b_public_rgbd")
    stage = tmp_path / "stage/m1b_physics_scene.usdc"
    stage.parent.mkdir()
    shutil.copy2(source / "stage/m1b_physics_scene.usdc", stage)
    raw_path = probe / "actuation-probe.json"
    raw_path.chmod(0o600)
    return raw_path, stage, _record(source)


def test_complete_164_file_replay_is_strictly_zero_eligible() -> None:
    report = AUDIT.build_report(_evidence_root(), project=ROOT)

    assert report["status"] == "BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES_BATCH03"
    assert report["evidence_root_inventory"] == {
        "regular_file_count": 164,
        "canonical_path_sha256_map_digest": (
            "28fb5d4c189f3dfdb0a5ee31d304351a973d2372fcdb7aa67817a243d580e06e"
        ),
        "all_regular_files_byte_hashed": True,
    }
    assert report["scope"]["batch03_execution_attempt_directories"] == 3
    assert report["scope"]["batch03_unique_train_keys_attempted"] == 3
    assert report["scope"]["batch03_retry_attempts"] == 0
    assert report["scope"]["batch03_replacement_attempts"] == 0
    assert report["scope"]["batch03_unique_sdf_sha256_covered"] == 3
    assert report["observed_counts"] == {
        "raw_v3_eight_step_chains": 3,
        "raw_lifted_but_public_predicate_rejected": 1,
        "raw_final_false_contact_gate_rejected": 1,
        "raw_final_false_pregrasp_ik_gate_rejected": 1,
        "training_samples_packaged": 0,
        "training_samples_eligible": 0,
    }
    assert [attempt["classification"] for attempt in report["attempts"]] == [
        AUDIT.RAW_LIFTED_PUBLIC_REJECT,
        AUDIT.RAW_CONTACT_REJECT,
        AUDIT.RAW_PREGRASP_REJECT,
    ]
    assert [attempt["evidence_tree"]["regular_file_count"] for attempt in report["attempts"]] == [
        56,
        54,
        54,
    ]
    assert report["execution_boundaries"]["training_executed"] is False
    assert report["execution_boundaries"]["model_rollout_executed"] is False
    assert report["execution_boundaries"]["formal_q_b_evaluation_executed"] is False
    assert report["execution_boundaries"]["pure_model_success_episodes"] is None
    assert report["extrapolation"] == {
        "claims_about_unobserved_keys": None,
        "claims_about_model_performance": None,
        "claims_about_q_b_performance": None,
    }


def test_scene_16073_lifted_is_not_promoted_past_public_predicate() -> None:
    report = AUDIT.build_report(_evidence_root(), project=ROOT)
    attempt = report["attempts"][0]

    assert attempt["identity"]["scene_seed"] == 16073
    assert attempt["classification"] == AUDIT.RAW_LIFTED_PUBLIC_REJECT
    assert attempt["classification_evidence"]["step_7_controller_gate"] == "PASS"
    assert attempt["classification_evidence"]["step_7_status"] == "LIFTED"
    assert attempt["classification_evidence"]["step_7_object_lift_m"] > 0.0
    assert attempt["classification_evidence"]["public_success_predicate_accepted"] is False
    assert attempt["classification_evidence"]["final_task_success"] is False
    assert attempt["training_sample_eligible"] is False
    assert attempt["counted_as_pure_model_success"] is False


def test_public_predicate_tamper_fails_closed(tmp_path: Path) -> None:
    raw_path, stage, record = _copy_raw_fixture(tmp_path, "batch03-01")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    predicate = raw["m2b_recovery"]["wrong_object"]["public_regrasp_predicates"]
    predicate["carried_public_track_id"] = predicate["task_target_track_id"]
    predicate["predicates"] = ["grasped=true", "lifted=true"]
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="public predicate rejection changed"):
        AUDIT._validate_raw_chain(raw_path, record=record, stage_path=stage)


def test_capture_asset_byte_tamper_fails_closed(tmp_path: Path) -> None:
    raw_path, stage, record = _copy_raw_fixture(tmp_path, "batch03-01")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    capture = raw["m2b_public_rgbd"]["captures"][-1]
    asset = raw_path.parent / capture["rgb_uri"].removeprefix("dataset://")
    asset.chmod(0o600)
    asset.write_bytes(asset.read_bytes() + b"tamper")

    with pytest.raises(ValueError, match="capture journal asset hash mismatch"):
        AUDIT._validate_raw_chain(raw_path, record=record, stage_path=stage)


def test_physical_receipt_hash_tamper_fails_closed(tmp_path: Path) -> None:
    raw_path, stage, record = _copy_raw_fixture(tmp_path, "batch03-02")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["m2c_path_blocked_physical_chain"]["steps"][0]["physical_receipts"][0][
        "completed_at_ns"
    ] += 1
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="physical receipt hash mismatch"):
        AUDIT._validate_raw_chain(raw_path, record=record, stage_path=stage)


def test_any_evidence_byte_change_changes_tree_digest(tmp_path: Path) -> None:
    evidence = tmp_path / "batch03"
    evidence.mkdir()
    artifact = evidence / "console.log"
    artifact.write_bytes(b"terminal receipt\n")
    original = AUDIT.cumulative.canonical_sha256(AUDIT.cumulative._regular_file_hashes(evidence))

    artifact.write_bytes(b"terminal receipt tampered\n")
    tampered = AUDIT.cumulative.canonical_sha256(AUDIT.cumulative._regular_file_hashes(evidence))

    assert original != tampered
