"""Focused replay and tamper tests for the frozen V3 TRAIN audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_path_blocked_train_collection_v3.py"
EVIDENCE = Path("/Users/gl/tzb-m2c-evidence/m2c-s4-v3-complete-U3F4Hj/evidence")
SPEC = importlib.util.spec_from_file_location("m2c_train_collection_audit_v3", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _evidence_root() -> Path:
    if not EVIDENCE.is_dir():
        pytest.skip(f"frozen external V3 evidence is unavailable: {EVIDENCE}")
    return EVIDENCE


def _successful_attempt_root() -> Path:
    roots = list((_evidence_root() / "batch01-retry1").glob("train/*/collection-job-v3.json"))
    assert len(roots) == 1
    return roots[0].parent


def test_complete_415_file_replay_is_strictly_zero_eligible() -> None:
    report = AUDIT.build_report(_evidence_root(), project=ROOT)

    assert report["status"] == "BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES"
    assert report["evidence_root_inventory"] == {
        "regular_file_count": 415,
        "canonical_path_sha256_map_digest": (
            "dc1d236ba4b2cff6af00291f8435fa7eba3da02917def440f6e359fda09f7062"
        ),
        "all_regular_files_byte_hashed": True,
    }
    assert report["scope"]["execution_attempt_directories"] == 9
    assert report["scope"]["unique_train_keys_attempted"] == 8
    assert report["scope"]["unique_sdf_sha256_covered"] == 3
    assert report["observed_counts"] == {
        "raw_v3_eight_step_chains": 7,
        "raw_final_false_contact_gate_rejected": 5,
        "raw_final_false_pregrasp_ik_gate_rejected": 2,
        "infrastructure_stage_exit_139": 1,
        "pre_kit_tzdata_guard_failure": 1,
        "training_samples_packaged": 0,
        "training_samples_eligible": 0,
    }
    assert report["execution_boundaries"]["training_executed"] is False
    assert report["execution_boundaries"]["model_rollout_executed"] is False
    assert report["execution_boundaries"]["formal_q_b_evaluation_executed"] is False
    assert report["execution_boundaries"]["pure_model_success_episodes"] is None
    assert (
        sum(attempt["evidence_tree"]["regular_file_count"] for attempt in report["attempts"]) == 415
    )


def test_candidate_payload_tamper_fails_closed(tmp_path: Path) -> None:
    source = _successful_attempt_root()
    probe = tmp_path / "probe"
    probe.mkdir()
    shutil.copy2(source / "probe/actuation-probe.json", probe / "actuation-probe.json")
    shutil.copytree(source / "probe/m2b_public_rgbd", probe / "m2b_public_rgbd")
    stage = tmp_path / "stage/m1b_physics_scene.usdc"
    stage.parent.mkdir()
    shutil.copy2(source / "stage/m1b_physics_scene.usdc", stage)

    raw_path = probe / "actuation-probe.json"
    raw_path.chmod(0o600)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    candidates = raw["m2c_path_blocked_physical_chain"]["steps"][0]["observation"][
        "candidate_payload"
    ]["candidates"]
    candidates.reverse()
    raw_path.write_text(json.dumps(raw), encoding="utf-8")

    job = json.loads((source / "collection-job-v3.json").read_text(encoding="utf-8"))
    manifest = AUDIT.load_v3_training_manifest(ROOT / AUDIT.MANIFEST_PATH)
    record = next(
        item.model_dump(mode="json")
        for item in manifest.training_keys
        if item.matched_key == job["matched_key"]
    )
    with pytest.raises(ValueError, match="candidates are not host-recomputable"):
        AUDIT.validate_raw_chain(raw_path, record=record, stage_path=stage)


def test_any_evidence_byte_change_changes_tree_digest(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    artifact = evidence / "console.log"
    artifact.write_bytes(b"terminal receipt\n")
    original = AUDIT.canonical_sha256(AUDIT._regular_file_hashes(evidence))

    artifact.write_bytes(b"terminal receipt tampered\n")
    tampered = AUDIT.canonical_sha256(AUDIT._regular_file_hashes(evidence))

    assert original != tampered
